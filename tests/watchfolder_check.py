"""1.324 素材入口这一档：引擎自己盯目录收素材，收不了的要按名字说得出为什么。

企业把剪辑交给 agent 之后，第一段路一直是人家的脚本在管：素材丢进共享目录 → 外面有人盯着 →
调 `media_import`。那一脚本看不见「文件还在拷」这件事，也记不住「这个我收过了」——于是引擎这边
收到的经常是半截内容，或者同一份素材被收两遍。这一档把入口挪进引擎，并要求每一手都有账。

① 判据本身（用产品那一个类，走 `MediaService.import_file` 那唯一的一条路）：
   第一次看见只记观察、大小变了重新等、静默期没过不收、第二次稳定观察才收、收过的不重复收、
   不支持的后缀只计数不记账、0 字节与坏文件按名字拒（`MEDIA_EMPTY` 之类）；
② 真引擎真盯：丢一条 2 秒片子进去 → `/v1/watch` 读出 `imported` 且带 `probe_id`，
   那份记录从 `GET /v1/media/{probe_id}` 读得回来，缓存里那些派生件（缩略图/波形）也真在盘上；
③ 盯到的目录自动成为一个媒体根（`/v1/info` 的 `media_roots` 说得出它，且不重复登记）；
④ **重启不重收也不漏收**：A 收过的第二台不许再收一遍（`probe_id` 不变），A 没看见的那一份
   第二台要补上；
⑤ 读数同源：`/v1/metrics` 的 `watch` 那一格与 `/v1/watch` 的 `config` 是同一份现算，
   令牌不对就是 401；
⑥ 配错不起：目录不存在、给的是相对路径、给的是文件——都不起，且与「非本机要加密」
   「非本机要令牌」一起在同一句里点名（1.322 的规矩）；**盯到输出目录上、或盯的目录盖住它**
   同样不起（watch 是递归扫的，交付件与代理都会落进 ALLOWED_SUFFIXES，引擎会自己喂自己）；
   反向那一腿钉住「同级的目录照样起得来」；
⑦ 没配就没有这一面：`configured: false`、一条账也没有、也不起线程；
⑧ 扫描成本有读数：1000 个已收过的文件一趟在 250 ms 以内（`watch.py` 那句性能断言的出处）。

跑法：空闲机器单跑 `uv run python tests/watchfolder_check.py`（要随包那两支媒体程序）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import reaper
import scratch
from fastapi.testclient import TestClient
from ops_check import FFMPEG, FFPROBE, Rig, source

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import TIMEBASE  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.media import MediaService  # noqa: E402
from agentcut.watch import Watcher, connect_watch  # noqa: E402

TOKEN = "watch-check-" + "w" * 40 + "-token"
FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")


def env_for(**extra: str) -> dict:
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["AGENTCUT_TOKEN"] = TOKEN
    env.update(extra)
    return env


def spawn(rig: Rig, *extra: str, **env_add: str) -> subprocess.Popen:
    # 媒体根与盯的目录**分开**：两者重合时「盯的目录自动成为媒体根」这一手根本没被测到
    # （1.324 的 W4 刀就是这么漏过去的——它只红了读数组，收素材那一腿照绿）。
    return reaper.note(subprocess.Popen(
        [sys.executable, "-m", "agentcut", "api", "--port", "0", "--json",
         "--data-dir", str(rig.data_dir), "--media-root", str(rig.folder / "lib"),
         "--output-dir", str(rig.out), "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE),
         *extra],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=env_for(**env_add),
    ))


def ready_line(proc: subprocess.Popen, seconds: float = 90.0) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return {}
        line = proc.stdout.readline() if proc.stdout else ""
        if line and '"event": "ready"' in line:
            return json.loads(line)
    return {}


def wait_exit(proc: subprocess.Popen, seconds: float = 40.0) -> tuple[int | None, str]:
    deadline = time.time() + seconds
    while time.time() < deadline and proc.poll() is None:
        time.sleep(0.2)
    code = proc.poll()
    if code is None:
        stop(proc)
        return None, ""
    return code, (proc.stdout.read() or "") + (proc.stderr.read() or "")


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=60)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def api(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, headers={"Authorization": f"Bearer {TOKEN}"},
                        timeout=60.0)


def rows_of(base: str) -> dict[str, dict]:
    with api(base) as hub:
        body = hub.get("/v1/watch").json()
    return {str(row["name"]): row for row in body.get("watch") or []}


def wait_row(base: str, name: str, want: str, seconds: float = 90.0) -> dict:
    """等的是「这一份到了某个状态」，不是睡一会儿——机器忙的时候等待要有读数说话。"""
    deadline = time.time() + seconds
    row: dict = {}
    while time.time() < deadline:
        row = rows_of(base).get(name) or {}
        if row.get("state") == want:
            return row
        time.sleep(0.4)
    return row


def settle_watcher(folder: Path, grace: float = 0.2) -> tuple[Watcher, Path]:
    inbox = folder / "media" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    db = folder / "watch.sqlite3"
    media = MediaService(db, [folder / "media"], folder / "cache", FFMPEG, FFPROBE)
    return Watcher(db, media, [str(inbox)], interval_seconds=0.3,
                   grace_seconds=grace), inbox


def predicate_leg() -> None:
    """① 判据本身：两趟稳定观察才收，收过不重收，拒的时候要按名字。"""
    folder = scratch.make("agentcut-watchpredicate-")
    watcher, inbox = settle_watcher(folder)
    clip = source(folder, 2)
    target = inbox / "drop.mp4"
    target.write_bytes(clip.read_bytes()[:4000])
    watcher.scan_once()
    first = watcher.recent(9)[0]
    check("第一次看见只记观察，不收（半拷的文件就在这一步被挡下）",
          first["state"] == "pending" and first["size_bytes"] == 4000, first)
    target.write_bytes(clip.read_bytes())
    watcher.scan_once()
    grew = watcher.recent(9)[0]
    check("大小变了就重新等一次稳定观察（拿旧读数收就是收半截）",
          grew["state"] == "pending" and grew["size_bytes"] == clip.stat().st_size, grew)
    time.sleep(0.25)
    watcher.scan_once()
    done = watcher.recent(9)[0]
    check("第二次稳定观察才真收，且交回一个能读的 probe_id",
          done["state"] == "imported" and bool(done["probe_id"]), done)
    touched = watcher.scan_once()
    again = watcher.recent(9)[0]
    check("收过的那一份不重复收（否则一份素材会有两个 probe）",
          touched == 0 and watcher.summary()["imported"] == 1
          and again["probe_id"] == done["probe_id"], (touched, again, watcher.summary()))
    # 静默期是第二道闸：两次观察一致但文件还在被写（mtime 一直刷新）时也不许收。
    # 宽限期这里给 1.5 秒：两次背靠背的扫描只有几十毫秒，拿 0.2 秒去赌会飘。
    patient, pin = settle_watcher(folder / "patient", grace=1.5)
    (pin / "stillcopying.mp4").write_bytes(clip.read_bytes())
    patient.scan_once()
    patient.scan_once()
    early = patient.recent(9)[0]
    check("两次观察一致但静默期没过，仍然不收（这一道闸也得有读数）",
          early["state"] == "pending" and patient.summary()["imported"] == 0,
          (early, patient.summary()))
    time.sleep(patient.grace_seconds + 0.2)
    patient.scan_once()
    settled = patient.recent(9)[0]
    check("静默期一过就收（这一格不是因为永远 pending 而绿）",
          settled["state"] == "imported", settled)
    (inbox / "notes.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n喂\n", encoding="utf-8")
    (inbox / "junk.mp4").write_bytes(b"not really an mp4 " * 40)
    (inbox / "empty.mp4").write_bytes(b"")
    for _ in range(4):
        time.sleep(0.25)
        watcher.scan_once()
    rows = watcher.recent(9)
    states = {str(row["name"]): row for row in rows}
    check("0 字节的媒体文件按名字拒，不是一直挂着没人说原因",
          states.get("empty.mp4", {}).get("state") == "failed"
          and "MEDIA_EMPTY" in str(states.get("empty.mp4", {}).get("detail")),
          states.get("empty.mp4"))
    check("坏文件按名字拒（探测就是那一手做的判断）",
          states.get("junk.mp4", {}).get("state") == "failed"
          and str(states.get("junk.mp4", {}).get("detail")), states.get("junk.mp4"))
    summary = watcher.summary()
    check("不支持的后缀只计数、不进这本账（旁挂字幕不是失败）",
          summary["ignored_unsupported"] >= 1 and "notes.srt" not in states,
          (summary, sorted(states)))
    bare = Watcher(folder / "bare.sqlite3", None, [])  # 没配目录：一次扫描都不会发生
    check("没配目录就没有这一面：configured=false 且一条账都不记",
          bare.summary()["configured"] is False and bare.recent(5) == [], bare.summary())


def engine_leg(rig: Rig) -> None:
    """②③⑤ 真引擎盯真目录：收进来的那份要能从正常的读路径读回并用到。"""
    inbox = rig.folder / "dropbox"
    inbox.mkdir(parents=True, exist_ok=True)
    proc = spawn(rig, "--watch-dir", str(inbox), "--watch-interval", "0.5",
                 "--watch-grace", "0.2")
    ready = ready_line(proc)
    base = str(ready.get("base_url") or "")
    check("配了 watch 也起得来（起不来后面全是空跑）", bool(base), ready)
    if not base:
        stop(proc)
        return
    try:
        clip = source(rig.folder, 2)
        time.sleep(0.3)
        (inbox / "dropped.mp4").write_bytes(clip.read_bytes())
        row = wait_row(base, "dropped.mp4", "imported", seconds=60.0)
        check("丢进目录的素材被引擎自己收了（外面不用再写一个 watcher）",
              row.get("state") == "imported" and bool(row.get("probe_id")), row)
        probe_id = str(row.get("probe_id") or "")
        with api(base) as hub:
            record = hub.get(f"/v1/media/{probe_id}")
            body = record.json()
            verified = body.get("verified") or {}
            check("收进来的那份从正常读路径读得回来，读数是探出来的",
                  record.status_code == 200 and int(verified.get("width") or 0) == 1280
                  and int(verified.get("duration_ticks") or 0) > TIMEBASE,
                  (record.status_code, {key: verified.get(key) for key in
                                        ("width", "duration_ticks", "video_codec")}))
            urls = body.get("urls") or {}
            shots = list(urls.get("thumbnails") or [])
            thumb = httpx.get(shots[0], timeout=30.0) if shots else None
            wave_url = str(urls.get("waveform") or "")
            wave = httpx.get(wave_url, timeout=30.0) if wave_url else None
            peaks = wave.json() if wave is not None else None
            check("派生件真在盘上（缩略图与波形是导入那一步建的，不是之后补的）",
                  thumb is not None and thumb.status_code == 200 and len(thumb.content) > 0
                  and wave is not None and wave.status_code == 200 and isinstance(peaks, list)
                  and bool(peaks),
                  (None if thumb is None else (thumb.status_code, len(thumb.content)),
                   None if peaks is None else (wave.status_code, len(peaks))))
            #  differential：同一份文件，HTTP 那一路 import 与 watch 这一路必须给出同一件东西。
            #  「一样」才是「走的是同一条路」的读数；只量「收进了一个 probe」不够。
            again = hub.post("/v1/media/import", json={"path": str(inbox / "dropped.mp4")})
            second = again.json()
            two_v = second.get("verified") or {}
            same = {key: two_v.get(key) == verified.get(key) for key in
                    ("content_sha256", "duration_ticks", "width", "height", "video_codec")}
            check("watch 走的就是 HTTP 那条导入路：同一份文件探出来的读数一模一样",
                  again.status_code == 200 and all(same.values())
                  and len(second.get("thumbnails") or []) == len(body.get("thumbnails") or []),
                  (again.status_code, same))
            info = hub.get("/v1/info").json()
            echo = info.get("info") if isinstance(info.get("info"), dict) else info
            roots = [str(item) for item in (echo.get("media_roots") or [])]
            hits = [item for item in roots if Path(item).name == "dropbox"]
            check("盯的目录自动成为一个媒体根，且不重复登记",
                  len(hits) == 1, roots)
            check("/v1/info 说得出这台在盯哪个目录",
                  str(inbox) in [str(item) for item in (echo.get("watch_dirs") or [])],
                  echo.get("watch_dirs"))
            metrics = hub.get("/v1/metrics").json().get("watch") or {}
            listed = hub.get("/v1/watch").json().get("config") or {}
            check("metrics 里那一格与 /v1/watch 同源：imported 一致、没欠账",
                  metrics.get("imported") == listed.get("imported") == 1
                  and metrics.get("pending") == 0, (metrics, listed))
            with httpx.Client(base_url=base, headers={"Authorization": "Bearer wrong-token"},
                              timeout=20.0) as stranger:
                check("不是谁都能读这本账：令牌不对就是 401",
                      stranger.get("/v1/watch").status_code == 401,
                      stranger.get("/v1/watch").status_code)
            # 中文客户的文件名就是中文：空格、方括号、# 号一起上，走的还是同一条路
            # （rglob → 记账 → import_file → ffprobe 子进程 → 缩略图）。这一段刻意放在
            # 「imported 一致」那条后面：它会让这一台的 imported 从 1 变成 2。
            cjk_name = "素材-第1集[高清] #2.mp4"
            (inbox / cjk_name).write_bytes(source(rig.folder, 3).read_bytes())
            cjk_row = wait_row(base, cjk_name, "imported", seconds=90.0)
            cjk_id = str(cjk_row.get("probe_id") or "")
            cjk_read = hub.get(f"/v1/media/{cjk_id}") if cjk_id else None
            cjk_body = cjk_read.json() if cjk_read is not None else {}
            check("中文文件名（带空格、方括号与 #）也走通同一条路",
                  cjk_row.get("state") == "imported" and cjk_read is not None
                  and cjk_read.status_code == 200
                  and bool((cjk_body.get("urls") or {}).get("thumbnails"))
                  and int((cjk_body.get("verified") or {}).get("duration_ticks") or 0) > 0,
                  (cjk_row, None if cjk_read is None else cjk_read.status_code))
        # ④ A 收过的不许重收，A 没看见的第二台要补上。
        probe_before = probe_id
        time.sleep(0.3)
        second = source(rig.folder, 4)
        (inbox / "late.mp4").write_bytes(second.read_bytes())
    finally:
        stop(proc)
    proc2 = spawn(rig, "--watch-dir", str(inbox), "--watch-interval", "0.5",
                  "--watch-grace", "0.2")
    base2 = str(ready_line(proc2).get("base_url") or "")
    try:
        if not base2:
            check("第二台起不来", False, "没有 base_url")
            return
        row2 = wait_row(base2, "late.mp4", "imported", seconds=60.0)
        check("A 没看见的那一份，B 补上了（账是活的，不是一次性的）",
              row2.get("state") == "imported", row2)
        again = rows_of(base2).get("dropped.mp4") or {}
        check("A 收过的那一份不被重收：probe_id 还是那一个",
              again.get("state") == "imported" and again.get("probe_id") == probe_before,
              (again, probe_before))
    finally:
        stop(proc2)


def doors_leg(rig: Rig) -> None:
    """⑥ 配错不起，而且与别的门一起点名。"""
    missing = spawn(rig, "--watch-dir", str(rig.folder / "不在这里"))
    code, out = wait_exit(missing)
    check("目录不存在就停下，那句点名那一个路径",
          code not in (None, 0) and "不在这里" in out, (code, out[-200:]))
    relative = spawn(rig, "--watch-dir", "dropbox")
    code, out = wait_exit(relative)
    check("相对路径要停下（引擎按路径记账，相对路径会跟着启动目录一起漂）",
          code not in (None, 0) and "绝对路径" in out, (code, out[-200:]))
    a_file = rig.folder / "当目录用的文件.mp4"
    a_file.write_bytes(b"x" * 10)
    wrong = spawn(rig, "--watch-dir", str(a_file))
    code, out = wait_exit(wrong)
    check("给的是文件不是目录，也要停下",
          code not in (None, 0) and "不是一个目录" in out, (code, out[-200:]))
    triple = spawn(rig, "--host", "0.0.0.0", "--watch-dir", str(rig.folder / "也没有"),
                   AGENTCUT_TOKEN="")
    code, out = wait_exit(triple)
    named = all(needle in out for needle in ("--watch-dir", "TLS", "AGENTCUT_TOKEN"))
    check("几道门都没过就一句点名全部，谁也不许把谁演没了（1.322 那一刀的规矩）",
          code not in (None, 0) and named, (code, out[-300:]))
    # 1.324 自己喂自己：watch 是递归扫的，交付件（mp4/mov）与代理（也是 mp4）都落在
    # ALLOWED_SUFFIXES 里——盯到输出目录上，引擎会把自己刚写出来的东西当新素材再收一遍。
    # 实测过这一手：watch 目录＝输出目录，一刀配方跑完，交付件当场被记成 imported。
    self_feed = spawn(rig, "--watch-dir", str(rig.out))
    code, out = wait_exit(self_feed)
    check("盯到输出目录上就停下，那句同时点名盯的目录与写出的目录",
          code not in (None, 0) and "罩住了这台自己写交付的地方" in out
          and str(rig.out) in out, (code, out[-240:]))
    parent = spawn(rig, "--watch-dir", str(rig.folder))
    code, out = wait_exit(parent)
    check("盯的目录盖住输出目录的父目录也停下（递归扫，父目录一样看得见）",
          code not in (None, 0) and "罩住了这台自己写交付的地方" in out, (code, out[-240:]))
    # 反向那一腿：与写出目录同级的目录必须照常起得来。只证「挡得住」不证「没挡坏」，
    # 是半个断言——一个把 watch 全关掉的实现也能过上面两条。
    sibling = rig.folder / "incoming-sibling"
    sibling.mkdir(parents=True, exist_ok=True)
    proc = spawn(rig, "--watch-dir", str(sibling))
    ready = ready_line(proc)
    stop(proc)
    check("与写出目录同级的目录照样起得来（这一手挡的是自喂，不是所有目录）",
          bool(ready.get("base_url")), ready)


def cost_leg(rig: Rig) -> None:
    """⑧ 扫描成本：1000 个已收过的文件，一趟多少毫秒——`watch.py` 那句性能断言的读数。

    上限 250 ms：整趟共用一条连接之后实测 76 ms，一文件一条连接的旧写法是 445 ms；
    250 夹在中间，忙的机器上抖不到红线，把连接开回去的那种退化却一定过不去。
    """
    root = rig.folder / "bulk"
    root.mkdir(parents=True, exist_ok=True)
    for index in range(1000):
        (root / f"clip-{index:04d}.mp4").write_bytes(b"\x00" * 64)
    db_path = rig.folder / "bulk.sqlite3"
    media = MediaService(db_path, [root], rig.folder / "bulkcache", FFMPEG, FFPROBE)
    watcher = Watcher(db_path, media, [str(root)], interval_seconds=1.0, grace_seconds=1.0)
    db = connect_watch(db_path)
    try:
        now = time.time()
        for index in range(1000):
            path = root / f"clip-{index:04d}.mp4"
            stat = path.stat()
            watcher._write(db, path, stat.st_size, stat.st_mtime, "imported",
                           f"bulk-{index}", "", now)
    finally:
        db.close()
    timings: list[float] = []
    touched = -1
    for _ in range(5):
        started = time.perf_counter()
        touched = watcher.scan_once()
        timings.append((time.perf_counter() - started) * 1000.0)
    median = sorted(timings)[len(timings) // 2]
    check("1000 个已收过的文件，一趟扫描在 250 ms 以内（实测 76 ms；一文件一连接 445 ms）",
          touched == 0 and median < 250.0,
          (round(median, 1), [round(row, 1) for row in timings], touched))


def unconfigured_leg(rig: Rig) -> None:
    """⑦ 没配 watch 的引擎：这一面说得出「没配」，而不是缺一个键。"""
    rig.data_dir.mkdir(parents=True, exist_ok=True)
    media = MediaService(rig.db, [rig.folder], rig.folder / "cache", FFMPEG, FFPROBE)
    app = create_app(rig.db, TOKEN, media=media, jobs=rig.runtime())
    with TestClient(app, base_url="http://127.0.0.1",
                    headers={"Authorization": f"Bearer {TOKEN}"}) as hub:
        listed = hub.get("/v1/watch")
        config = listed.json().get("config") or {}
        check("没配目录时这一面照样答得出来：configured=false、目录表是空的",
              listed.status_code == 200 and config.get("configured") is False
              and listed.json().get("dirs") == [], listed.json())
        metrics = hub.get("/v1/metrics").json().get("watch") or {}
        check("metrics 那一格也说实话（不是没这一格）",
              metrics.get("configured") is False, metrics)


def main() -> None:
    try:
        predicate_leg()
    except Exception as error:  # noqa: BLE001 判据炸了也要把已量到的交出来
        check("① 判据那一腿半路炸了", False, f"{type(error).__name__}: {str(error)[:200]}")
    for tag, leg in (("engine", engine_leg), ("doors", doors_leg), ("cost", cost_leg),
                     ("unconfigured", unconfigured_leg)):
        try:
            leg(Rig(scratch.make(f"agentcut-watch{tag}-")))
        except (Exception, SystemExit) as error:  # noqa: BLE001
            check(f"{tag} 那一腿半路就炸了（这不是判不过，是根本没判完）", False,
                  f"{type(error).__name__}: {str(error)[:200]}")
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: 素材丢进目录引擎自己收下（半拷的挡在门外、收过的不重收、拒的按名字说得出），"
          "重启不重收不漏收，配错不起且与别的门一起点名")


if __name__ == "__main__":
    main()
