"""1.325 无人值守：引擎崩了有人接着把它拉起来，而且说得出拉了几次。

为什么这一档最要紧：桌面外壳会重拉引擎，但它在第 5 次之后永久放弃，前提还是「有人坐在这台机器前」。
企业把引擎放到服务器上、agent 走 HTTP 调它时，这条路上什么都没有——进程死了就是死了。1.324 之后
这件事更危险：watch folder 会继续把素材收进一个没人服务的目录，回执也不投，现场表现是「片子上架了
但没剪」，没有一行错误。

① 看门人把引擎拉起来：ready 行、`/health` 200、`supervisor.json` 的 state=running 且 restarts=0；
② 按 PID 杀掉**我自己那一个**子进程 → 同一个端口重新答 200、child_pid 变了、restarts 记账；
③ 陈旧租约接得回来：重启后的 ready 行里的 pid 就是账上那个 child_pid（被租约挡住就没有 ready 行）；
④ `/v1/metrics` 的 `supervisor` 那一格与盘上那份 `supervisor.json` 同源；
⑤ 宕机期间丢进素材目录的那一份，起来之后被收下（且只收一次，probe_id 不变）；
⑥ 宕机之前欠着的回执跨崩溃活着：重启后 `/v1/callbacks` 里同一条还在、尝试次数没归零；
⑦ 崩溃风暴闸门：子进程永远起不来时看门人不退出，间隔抬到 30 秒、`storm` 为真（不是放弃）；
⑧ 干净收摊：放一个 `supervisor.stop` 文件 → 退出 0、state=stopped、端口不再答、没有孤儿引擎；
⑨ 收摊之后机器上不该留下带这个数据目录的进程（按命令行查，不按镜像名）。

跑法：空闲机器单跑 `uv run python tests/supervisor_check.py`（要随包那两支媒体程序）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import scratch
from ops_check import FFMPEG, FFPROBE

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
FAILURES: list[str] = []
TOKEN = "supervise-check-" + "s" * 40


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:500]}")


def env_for() -> dict:
    item = dict(os.environ)
    item.pop("ELECTRON_RUN_AS_NODE", None)
    item["PYTHONIOENCODING"] = "utf-8"
    item["AGENTCUT_TOKEN"] = TOKEN
    return item


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def health(port: int) -> int:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as reply:
            return reply.status
    except Exception:  # noqa: BLE001
        return 0


def call(port: int, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                     method=method,
                                     headers={"Authorization": f"Bearer {TOKEN}"})
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=120) as reply:
            payload = reply.read()
    except urllib.error.HTTPError as error:
        payload = error.read()
        return error.code, json.loads(payload or b"{}")
    except (urllib.error.URLError, OSError):
        # 引擎没起来/连不上时，这里要交回一个「读不到」而不是炸掉——门禁要把这件事
        # 判在具名的那一腿上，否则一把刀只会让整档崩掉、谁也不知道红在哪。
        return 0, {}
    return 200, json.loads(payload or b"{}")


def state_of(data: Path) -> dict:
    try:
        return json.loads((data / "supervisor.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wait_state(data: Path, want: str, seconds: float = 60.0, **fields: object) -> dict:
    deadline = time.time() + seconds
    payload: dict = {}
    while time.time() < deadline:
        payload = state_of(data)
        if payload.get("state") == want and all(
            payload.get(key) == value for key, value in fields.items()
        ):
            return payload
        time.sleep(0.3)
    return payload


def last_ready(data: Path) -> dict:
    """从看门人抄下来的 server.log 里取最后一条 ready 行——重启后的那一台到底起没起得来。"""
    try:
        lines = (data / "server.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        if '"event": "ready"' in line:
            try:
                return json.loads(line.strip())
            except ValueError:
                continue
    return {}


def pids_with(marker: str) -> list[int]:
    # 排除 powershell 自己：它这条查询命令的命令行里就带着 marker，不排掉就是自己抓自己。
    script = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
              f"'*{marker}*' -and $_.Name -ne 'powershell.exe' }} "
              "| ForEach-Object { $_.ProcessId }")
    done = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    return [int(row) for row in (done.stdout or "").split() if row.strip().isdigit()]


def kill(pid: int) -> None:
    if pid:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True,
                       timeout=60)


def engine_flags(folder: Path, data: Path, port: int, extra: list[str]) -> list[str]:
    return ["api", "--port", str(port), "--json", "--data-dir", str(data),
            "--media-root", str(folder / "lib"), "--output-dir", str(folder / "out"),
            "--cache-dir", str(folder / "cache"), "--ffmpeg", str(FFMPEG),
            "--ffprobe", str(FFPROBE), *extra]


def start(folder: Path, data: Path, flags: list[str]) -> subprocess.Popen:
    data.mkdir(parents=True, exist_ok=True)
    (folder / "lib").mkdir(parents=True, exist_ok=True)
    (folder / "out").mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [sys.executable, "-m", "agentcut", "supervise", "--", *flags],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", env=env_for(),
    )


def stop(sup: subprocess.Popen, data: Path, seconds: float = 90.0) -> int:
    (data / "supervisor.stop").write_text("stop", encoding="utf-8")
    try:
        return sup.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        kill(sup.pid)
        return -1


def make_clip(target: Path) -> None:
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-nostdin",
         "-f", "lavfi", "-i", "color=c=green:s=320x180:r=30:d=2",
         "-f", "lavfi", "-i", "sine=frequency=440:r=48000:d=2",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "48000", "-shortest", str(target)],
        check=True, capture_output=True, timeout=600, creationflags=0x08000000,
    )


def main() -> None:
    folder = scratch.make("agentcut-supervise-")
    data = folder / "engine"
    dropbox = folder / "dropbox"
    dropbox.mkdir(parents=True, exist_ok=True)
    port = free_port()
    dead_hook = free_port()  # 一个没人听的端口：连接被拒，回执必然欠着
    flags = engine_flags(folder, data, port, [
        "--watch-dir", str(dropbox), "--watch-interval", "0.5", "--watch-grace", "0.2",
        "--callback-url", f"http://127.0.0.1:{dead_hook}/hook",
        "--callback-attempts", "2", "--callback-timeout", "1",
    ])
    sup = start(folder, data, flags)
    try:
        payload = wait_state(data, "running", seconds=90.0)
        check("① 看门人把引擎拉起来（账上 state=running、restarts=0）",
              payload.get("state") == "running" and payload.get("restarts") == 0, payload)
        check("① /health 真的答 200", health(port) == 200, health(port))
        first = int(payload.get("child_pid") or 0)
        first_ready = last_ready(data)
        check("① 账上的 child_pid 有值、ready 行也说得出引擎自己的 pid",
              first > 0 and int(first_ready.get("pid") or 0) > 0,
              (first, first_ready.get("pid")))

        clip = folder / "lib" / "source.mp4"
        make_clip(clip)
        made = call(port, "POST", "/v1/media/import", {"path": str(clip)})
        check("② 这一台真能干活（导入一份素材拿回 probe）",
              made[0] == 200 and bool((made[1].get("verified") or {}).get("probe_id")),
              (made[0], sorted(made[1])[:6]))
        presets = call(port, "GET", "/v1/render-presets")[1].get("presets") or []
        chosen = next((row for row in presets if row.get("container") == "mp4"), {})
        ran = call(port, "POST", "/v1/agent/recipes/cut-from-media/run",
                   {"request_id": "supervise-1", "name": "看门人", "files": [str(clip)],
                    "preset_id": str(chosen.get("id") or ""), "filename": "watchdog.mp4"})
        job = (ran[1].get("job") or {})
        job_id = str(job.get("id") or "")
        status = str(job.get("status") or "")
        deadline = time.time() + 240
        while job_id and status not in ("succeeded", "failed", "cancelled"):
            if time.time() > deadline:
                break
            status = str((call(port, "GET", f"/v1/jobs/{job_id}")[1].get("job") or {})
                         .get("status") or status)
            time.sleep(1.0)
        owed = call(port, "GET", "/v1/callbacks")[1]
        rows = [row for row in (owed.get("callbacks") or []) if row.get("job_id") == job_id]
        check("② 宕机之前那一单终态了，回执欠着（地址是死的）",
              status == "succeeded" and bool(rows) and int(rows[0].get("attempts") or 0) >= 1,
              (status, rows[:1]))
        attempts_before = int(rows[0].get("attempts") or 0) if rows else 0

        # ③ 按 PID 杀掉**我自己那一个**子进程；宕机期间往素材目录里丢一份。
        kill(first)
        (dropbox / "during-outage.mp4").write_bytes(clip.read_bytes())
        payload = wait_state(data, "running", seconds=120.0, restarts=1)
        second = int(payload.get("child_pid") or 0)
        check("③ 子进程被杀之后它自己拉回来了（restarts=1，新的 child_pid）",
              payload.get("state") == "running" and payload.get("restarts") == 1
              and second > 0 and second != first,
              (payload.get("state"), payload.get("restarts"), first, second))
        check("③ 上一次的退出码记在账上", payload.get("last_exit_code") is not None, payload)
        healthy = 0
        deadline = time.time() + 120
        while time.time() < deadline and healthy != 200:
            healthy = health(port)
            time.sleep(0.3)
        check("③ 同一个端口重新答 200（企业侧地址不变）", healthy == 200, healthy)
        rebuilt = last_ready(data)
        check("④ 陈旧租约接得回来：重启后的 ready 行是另一台引擎（pid 变了）",
              int(rebuilt.get("pid") or 0) > 0
              and int(rebuilt.get("pid") or 0) != int(first_ready.get("pid") or 0),
              (first_ready.get("pid"), rebuilt.get("pid")))
        metrics_status, metrics_body = call(port, "GET", "/v1/metrics")
        metrics = metrics_body.get("supervisor") or {}
        disk = state_of(data)
        check("⑤ /v1/metrics 的 supervisor 与盘上那份同源",
              metrics_status == 200
              and metrics.get("restarts") == disk.get("restarts")
              and metrics.get("child_pid") == disk.get("child_pid")
              and metrics.get("state") == disk.get("state"),
              (metrics_status, metrics, disk))

        row: dict = {}
        deadline = time.time() + 90
        while time.time() < deadline:
            listed = call(port, "GET", "/v1/watch")[1].get("watch") or []
            row = next((item for item in listed
                        if item.get("name") == "during-outage.mp4"), {})
            if row.get("state") in ("imported", "failed"):
                break
            time.sleep(0.5)
        first_probe = str(row.get("probe_id") or "")
        check("⑥ 宕机期间丢进目录的那一份，起来之后被收下",
              row.get("state") == "imported" and bool(first_probe), row)
        time.sleep(1.5)
        again = next((item for item in (call(port, "GET", "/v1/watch")[1].get("watch") or [])
                      if item.get("name") == "during-outage.mp4"), {})
        check("⑥ 而且只收一次（probe_id 不变）", again.get("probe_id") == first_probe,
              (first_probe, again.get("probe_id")))

        owed_after = call(port, "GET", "/v1/callbacks")[1]
        rows_after = [row for row in (owed_after.get("callbacks") or [])
                      if row.get("job_id") == job_id]
        attempts_after = int(rows_after[0].get("attempts") or 0) if rows_after else -1
        check("⑦ 宕机之前欠着的回执跨崩溃活着，尝试次数没归零",
              bool(rows_after) and attempts_after >= attempts_before,
              (attempts_before, attempts_after, rows_after[:1]))

        stop(sup, data)
        final = state_of(data)
        check("⑧ 干净收摊：state=stopped、child_pid 清空、退出码 0",
              final.get("state") == "stopped" and final.get("child_pid") is None
              and sup.returncode == 0, (final, sup.returncode))
        check("⑧ 端口不再答", health(port) == 0, health(port))
        leftovers = pids_with(str(data))
        check("⑨ 收摊之后没有带这个数据目录的进程（按命令行查，不按镜像名）",
              leftovers == [], leftovers)
    finally:
        if sup.poll() is None:
            kill(sup.pid)

    # ⑨ 崩溃风暴：子进程永远起不来（一个不存在的旗标），看门人不许退出、间隔抬到 30 秒。
    storm_dir = folder / "storm"
    storm_port = free_port()
    storm = start(folder, storm_dir, engine_flags(folder, storm_dir, storm_port,
                                                  ["--no-such-flag-here"]))
    try:
        payload = wait_state(storm_dir, "restarting", seconds=120.0, restarts=4)
        check("⑩ 崩溃风暴里看门人不退出：还在，restarts≥4",
              storm.poll() is None and int(payload.get("restarts") or 0) >= 4, payload)
        check("⑩ 间隔抬到最长那一档、storm 为真（不是放弃，也不是空转）",
              float(payload.get("next_delay_seconds") or 0) == 30.0
              and payload.get("storm") is True, payload)
        code = stop(storm, storm_dir, seconds=120.0)
        check("⑩ 风暴里放 stop 文件也收得下来（退出 0）", code == 0, code)
    finally:
        if storm.poll() is None:
            kill(storm.pid)
    leftovers = pids_with(str(storm_dir))
    check("⑩ 风暴收摊之后也没有留下进程", leftovers == [], leftovers)

    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: 看门人把引擎拉起来、按 PID 杀掉之后自己拉回来（同一端口）、宕机期间的素材被补收、"
          "欠着的回执跨崩溃活着、崩溃风暴里不放弃（30 秒一档）、放 stop 文件干净收摊且不留孤儿")


if __name__ == "__main__":
    main()
