"""企业落地冒烟：一台目标机上做 go / no-go，交回一张表与一个退出码。

这一支刻意**只用标准库**（`urllib` + `subprocess`），因为客户机器上没有这个仓库、
也没有 `httpx`。它打的全是产品对外的那扇门：`/v1` 的 HTTP 与 `agentcut tokens` 那条 CLI。
默认起的是随包的冻结引擎，`--engine` 可以指到 `AgentCut.exe` 那一支便携版。

十条腿，一条都不能含糊：

① 引擎起得来（ready 行报得出台数、额度、底线、租约；`/health` 200）
② 一台数据目录只服一台（第二台被拒，而且没碰令牌、没抢租约）
③ 素材进得来（造一段 4 秒有声源，`/v1/media/import` 交回现场探测的时长）
④ 一刀配方跑到交付（`/v1/agent/recipes/cut-from-media/run`，预设从现场读，不写死）
⑤ 交付文件由引擎自己验（`/v1/jobs/{id}/verify` 的 verdict 为真、checks 每条都 ok）
⑥ 台账写得出那一行（`/v1/agent/audit` 里有写操作，点名是谁）
⑦ 只读令牌被拒得对（403 `SCOPE_DENIED`）
⑧ 吊销立刻生效（同一枚令牌变 401）
⑨ 排队现数读得出（`/v1/metrics` 三张表都在，`jobs.by_status.succeeded` ≥ 1）
⑩ 输出盘底线拒得对（底线抬到天上，投单 503 `OUTPUT_DISK_TIGHT` 并点名是哪个根）

跑法：`python scripts/enterprise_smoke.py`（加 `--json out.json` 交回机器可读的结果）。
判它的是 `tests/enterprise_smoke_check.py`。
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "desktop/resources/bin/agentcut/agentcut.exe"
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
# 令牌的规矩是「至少 32 个字符才认」（`__main__.load_token`）：短了就被静默忽略、改用文件里
# 现生成的那一枚，冒烟会读成「令牌不认」——所以这里给一枚够长的。
TOKEN = "smoke-" + secrets.token_hex(32)

ROWS: list[dict[str, object]] = []


def leg(name: str, ok: bool, evidence: object = "") -> bool:
    ROWS.append({"name": name, "ok": bool(ok), "evidence": repr(evidence)[:300]})
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {str(evidence)[:150]}")
    return bool(ok)


def base_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra or {})
    return env


def start(command: list[str], seconds: float = 180.0) -> tuple[subprocess.Popen, dict]:
    proc = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env=base_env(), cwd=str(ROOT),
        creationflags=0x08000000,
    )
    deadline = time.time() + seconds
    while time.time() < deadline:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line and proc.poll() is not None:
            return proc, {}
        if line and '"event": "ready"' in line:
            return proc, json.loads(line.strip())
    stop(proc)
    return proc, {}


def engine_command(folder: Path, engine: Path, *extra: str) -> list[str]:
    return [
        str(engine), "api", "--port", "0", "--json",
        "--data-dir", str(folder / "engine"), "--cache-dir", str(folder / "cache"),
        "--output-dir", str(folder / "out"), "--media-root", str(folder),
        "--token-file", str(token_file(folder)),
        "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE), *extra,
    ]


def token_file(folder: Path) -> Path:
    return folder / "engine/agentcut.token"


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=60)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()


def call(base: str, method: str, path: str, body: dict | None = None,
         token: str | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {token or TOKEN}"})
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=300) as reply:
            payload = reply.read()
    except urllib.error.HTTPError as error:
        payload = error.read()
        return error.code, json.loads(payload or b"{}")
    return 200, json.loads(payload or b"{}")


def cli(engine: Path, folder: Path, *args: str) -> dict:
    done = subprocess.run(
        [str(engine), "tokens", "--data-dir", str(folder / "engine"), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=base_env(), cwd=str(ROOT), timeout=180,
    )
    out = (done.stdout or "").strip().splitlines()
    return json.loads(out[-1]) if out and out[-1].startswith("{") else {"raw": out,
                                                                        "stderr": done.stderr}


def build_source(folder: Path) -> Path:
    target = folder / "smoke-source.mp4"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-nostdin",
         "-f", "lavfi", "-i", "color=c=red:s=320x180:r=30:d=4",
         "-f", "lavfi", "-i", "sine=frequency=440:r=48000:d=2",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=2",
         "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "48000", "-shortest", str(target)],
        check=True, capture_output=True, timeout=600, creationflags=0x08000000,
    )
    return target


def pick_preset(presets: list) -> dict:
    """从现场读到的预设里挑一支 mp4 + H.264 的，优先代理那一档。

    文件名要跟容器的后缀对上：挑了 webm 那档却交 `smoke-out.mp4`，引擎会 422 拒掉——
    这一手冒烟自己先踩过一次。
    """
    video = [row for row in presets if row.get("container") == "mp4" and row.get("codec")]
    preferred = [row for row in video if any(word in str(row.get("id"))
                                              for word in ("source", "540", "fast"))]
    pool = preferred or video
    return pool[0] if pool else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default="", help="引擎可执行文件；默认用随包那支冻结引擎")
    parser.add_argument("--json", default="", help="把结果表写成 JSON")
    parser.add_argument("--keep", action="store_true", help="保留临时目录（默认用完就删）")
    arguments = parser.parse_args()
    engine = Path(arguments.engine) if arguments.engine else ENGINE
    if not engine.is_file():
        print(f"FAIL  引擎不存在：{engine}（先按 README 的重建链产一份，或用 --engine 指）")
        return 2
    if not (FFMPEG.is_file() and FFPROBE.is_file()):
        print(f"FAIL  随包媒体程序不见了：{FFMPEG} / {FFPROBE}")
        return 2
    folder = Path(tempfile.mkdtemp(prefix="agentcut-enterprise-smoke-"))
    first: subprocess.Popen | None = None
    second: subprocess.Popen | None = None
    third: subprocess.Popen | None = None
    try:
        data_dir = folder / "engine"
        data_dir.mkdir(parents=True, exist_ok=True)
        lease = data_dir / "engine.lock"
        token_path = token_file(folder)
        # 令牌走文件那一条路：这样「第二台没碰令牌」才是量得出来的——环境里那枚会让文件根本不生成。
        token_path.write_text(TOKEN, encoding="utf-8")
        first, ready = start(engine_command(folder, engine))
        summary = {key: ready.get(key) for key in ("port", "slots", "max_queue",
                                                  "min_free_mb", "pid", "lease")}
        ok_start = leg("① 引擎起得来", bool(ready.get("base_url")), summary)
        if not ok_start:
            return 1
        base = str(ready["base_url"])
        health = urllib.request.urlopen(base + "/health", timeout=30).status
        leg("① 引擎起得来（/health 真答）", health == 200, health)

        token_before = token_path.read_bytes() if token_path.is_file() else b""
        record = json.loads(lease.read_text(encoding="utf-8")) if lease.is_file() else {}
        lease_pid = record.get("pid")
        second, refused = start(engine_command(folder, engine), seconds=60.0)
        code = second.wait(timeout=60)
        out = (second.stdout.read() or "") if second.stdout else ""
        leg("② 第二台在同一份数据目录上被拒", code != 0 and not refused, (code, out[-120:]))
        after_lease = json.loads(lease.read_text(encoding="utf-8")) if lease.is_file() else {}
        after_token = token_path.read_bytes() if token_path.is_file() else b""
        leg("② 被拒那一台没碰令牌、没抢租约",
            after_token == token_before and after_lease.get("pid") == lease_pid,
            (len(token_before), lease_pid, after_lease.get("pid")))

        source = build_source(folder)
        made = call(base, "POST", "/v1/media/import", {"path": str(source)})
        probe = (made[1].get("verified") or {}) if made[0] == 200 else {}
        leg("③ 素材进得来（现场探测交回可信记录）",
            made[0] == 200 and bool(probe.get("probe_id")), (made[0], sorted(probe)[:8]))
        ticks = int(probe.get("duration_ticks") or 0)
        leg("③ 探测交回了时长与画幅", ticks > 0 and probe.get("width") == 320,
            (ticks, probe.get("width"), probe.get("height")))

        presets = call(base, "GET", "/v1/render-presets")
        chosen = pick_preset(presets[1].get("presets") or [])
        preset = str(chosen.get("id") or "")
        out_name = f"smoke-out.{chosen.get('container') or 'mp4'}"
        manifest = call(base, "GET", "/v1/agent/manifest")
        recipes = (manifest[1].get("recipes") or []) if manifest[0] == 200 else []
        cut = next((row for row in recipes if row.get("id") == "cut-from-media"), {})
        body = {"request_id": "smoke-recipe-1", "name": "冒烟",
                "files": [str(source)], "preset_id": preset, "filename": out_name}
        ran = call(base, "POST", "/v1/agent/recipes/cut-from-media/run", body)
        steps = (ran[1].get("steps") or []) if ran[0] == 200 else []
        job = ran[1].get("job") or {}
        output = Path(str(ran[1].get("output_path") or ""))
        leg("④ 一刀配方跑到交付（预设现场取）",
            ran[0] == 200 and bool(cut.get("runnable")) and len(steps) >= 10 and preset,
            (ran[0], len(steps), preset, (ran[1].get("error") or {}).get("code")))
        job_id = job.get("id")
        # 配方那一刀交回的是「排上了」，不是「渲完了」——交付文件在渲到一半时就在盘上，只是 0 字节。
        # 冒烟等的是终态这件事本身（等来的，不是睡出来的），否则④⑤两腿读到的就是空气。
        status = str(job.get("status") or "")
        deadline = time.time() + 240.0
        while job_id and status not in ("succeeded", "failed", "cancelled"):
            if time.time() >= deadline:
                break
            got = call(base, "GET", f"/v1/jobs/{job_id}")
            status = str(((got[1].get("job") or {}).get("status")) or status)
            time.sleep(1.0)
        leg("④ 那一单自己走到终态（succeeded）",
            status == "succeeded" and ran[1].get("timed_out") is not True,
            (status, ran[1].get("waited_ms"), ran[1].get("timed_out")))
        leg("④ 交付文件真在盘上", output.is_file() and output.stat().st_size > 10_000,
            (str(output), output.stat().st_size if output.is_file() else 0))

        verify = call(base, "GET", f"/v1/jobs/{job_id}/verify") if job_id else (0, {})
        checks = verify[1].get("checks") or []
        leg("⑤ 引擎自己把那份交付验了（每条都 ok）",
            verify[0] == 200 and verify[1].get("verdict") is True and len(checks) >= 2
            and all(row.get("ok") for row in checks),
            (verify[0], verify[1].get("verdict"), checks[:3]))

        audit = call(base, "GET", "/v1/agent/audit?limit=50")
        events = audit[1].get("events") or []
        writes = [row for row in events if str(row.get("method", "")).upper() == "POST"]
        leg("⑥ 台账写得出那一行并点名是谁",
            audit[0] == 200 and writes and all(row.get("actor") for row in writes),
            (audit[0], len(events), len(writes)))

        issued = cli(engine, folder, "--add-label", "smoke-readonly", "--scopes", "read")
        read_token = str(issued.get("token") or "")
        denied = call(base, "POST", "/v1/projects",
                      {"request_id": "smoke-readonly-create", "name": "不该成"}, token=read_token)
        code_text = json.dumps(denied[1], ensure_ascii=False)
        leg("⑦ 只读令牌做写操作被拒得对", denied[0] == 403 and "SCOPE_DENIED" in code_text,
            (denied[0], denied[1].get("error", {}).get("code")))

        cli(engine, folder, "--revoke-label", "smoke-readonly")
        after = call(base, "POST", "/v1/projects",
                     {"request_id": "smoke-revoked-create", "name": "不该成"}, token=read_token)
        leg("⑧ 吊销之后立刻不认", after[0] in (401, 403), (after[0],
            after[1].get("error", {}).get("code")))

        metrics = call(base, "GET", "/v1/metrics")
        tables = metrics[1] if metrics[0] == 200 else {}
        leg("⑨ 排队现数读得出三张表",
            all(key in tables for key in ("queue", "jobs", "outputs")), sorted(tables))
        by_status = ((tables.get("jobs") or {}).get("by_status") or {})
        leg("⑨ 那一单在账里算成了交付", int(by_status.get("succeeded") or 0) >= 1, by_status)

        third, tight = start(engine_command(folder, engine, "--min-free-mb", "999999999",
                                            "--allow-shared-data-dir"), seconds=180.0)
        tight_base = str(tight.get("base_url") or "")
        project_id = ran[1].get("project_id")
        tight_body = {"request_id": "smoke-disk-tight", "expected_revision": ran[1].get("revision"),
                      "preset_id": preset, "filename": f"tight.{chosen.get('container') or 'mp4'}"}
        refused_render = (call(tight_base, "POST", f"/v1/projects/{project_id}/renders", tight_body)
                          if tight_base else (0, {}))
        text = json.dumps(refused_render[1], ensure_ascii=False)
        leg("⑩ 输出盘低于底线拒在排队之前",
            refused_render[0] == 503 and "OUTPUT_DISK_TIGHT" in text
            and "free_bytes" in text and "reserve_bytes" in text,
            (refused_render[0], refused_render[1].get("error", {}).get("code")))
    finally:
        for proc in (first, second, third):
            if proc is not None:
                stop(proc)
        if arguments.json:
            Path(arguments.json).write_text(json.dumps(ROWS, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        if not arguments.keep:
            shutil.rmtree(folder, ignore_errors=True)
    failed = [row for row in ROWS if not row["ok"]]
    print(f"\n冒烟：{len(ROWS) - len(failed)}/{len(ROWS)} 条通过"
          + ("" if not failed else "，红的：" + "、".join(str(row["name"]) for row in failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
