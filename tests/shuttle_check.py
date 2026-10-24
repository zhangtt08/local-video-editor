"""1.281：J/K/L 走带的真页面验收——按 L 两次 2×、J 变 -1× 且时间码往回流、K 停下不动。

为什么要有这一档：壳检只证明源码里「时钟乘 rate、元素按 |rate| 播、变速静音」。真正的三件事
只有真键盘与真 DOM 才量得到：倍率牌画没画出来、时间码的方向对不对、停下之后还在不在动。

跑法：空闲机器单跑 `uv run python tests/shuttle_check.py`（要渲染层构建产物、node、Edge、
随包 ffmpeg；缺一样就点名）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import APP_VERSION  # noqa: E402

RENDERER = ROOT / "desktop/dist/renderer"
PROBE = ROOT / "scripts/ui_shuttle_probe.cjs"
EDGE = Path(
    os.environ.get(
        "AGENTCUT_EDGE", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    )
)
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TOKEN = "shuttlecheck" + "s" * 52
SECOND = 70_560_000
PORT = 0


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def request(path: str, token: str, payload=None, method="GET"):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:600]
        raise AssertionError(f"{method} {path} -> {error.code}: {detail}") from None


def seed(folder: Path) -> str:
    source = folder / "strip.mp4"
    done = subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y", "-nostdin",
            "-f", "lavfi", "-i", "color=c=0x224466:s=320x180:r=30:d=12",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        capture_output=True,
        timeout=180,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-500:]
    probe = request("/v1/media/import", TOKEN, {"path": str(source)}, "POST")["verified"]
    made = request("/v1/projects", TOKEN, {"request_id": "shuttle-new", "name": "走带"}, "POST")
    pid = made["project"]["id"]
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {
            "op": "asset.import", "asset_id": "s", "label": "strip",
            "probe_id": probe["probe_id"], "verified": probe,
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "c", "asset_id": "s", "track_id": "v",
                "position_ticks": 0, "duration_ticks": 12 * SECOND,
            },
        },
    ]
    request(
        f"/v1/projects/{pid}/edits",
        TOKEN,
        {
            "request_id": "shuttle-seed",
            "expected_revision": made["project"]["revision"],
            "commands": commands,
        },
        "POST",
    )
    return pid


def run_engine(data_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["AGENTCUT_TOKEN"] = TOKEN
    process = subprocess.Popen(
        [
            sys.executable, "-m", "agentcut", "api", "--port", str(PORT), "--json",
            "--data-dir", str(data_dir), "--cache-dir", str(data_dir / "cache"),
            "--output-dir", str(data_dir / "out"), "--media-root", str(data_dir),
            "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(ROOT),
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        line = process.stdout.readline() if process.stdout else ""
        if not line and process.poll() is not None:
            fail(f"引擎没起来（退出码 {process.returncode}）：{line[:200]}")
        if '"event": "ready"' in line:
            return process
    fail("引擎 120 秒内没有报 ready")
    raise SystemExit(1)


def stop(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        process.wait(timeout=20)
    except Exception:  # noqa: BLE001 - 收尾失败不该盖掉真正的红
        try:
            process.kill()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    global PORT
    for path, why in ((RENDERER, "渲染层没有构建（cd desktop && npm run build:renderer）"),
                      (PROBE, "量具脚本不见了"),
                      (EDGE, "没有 Edge"),
                      (FFMPEG, "随包 ffmpeg 不见了")):
        if not Path(path).exists():
            fail(f"{why}：{path}")
    PORT = free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-shuttleui-") as raw:
        folder = Path(raw)
        engine = run_engine(folder)
        try:
            pid = seed(folder)
            out = folder / "shuttle.json"
            ran = subprocess.run(
                [
                    "node", str(PROBE),
                    "--renderer", str(RENDERER),
                    "--engine", f"http://127.0.0.1:{PORT}",
                    "--token", TOKEN,
                    "--project", pid,
                    "--size", "1280x800",
                    "--out", str(out),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=420,
                cwd=str(ROOT),
            )
            if ran.returncode != 0 or not out.is_file():
                fail("量具没跑完：" + (ran.stderr or ran.stdout)[-900:])
            facts = json.loads(out.read_text(encoding="utf-8"))
            print(
                f"   倍率牌：停 {facts['idle']['chip']} → L {facts['afterL1']['chip']}"
                f" → L {facts['afterL2']['chip']} → J {facts['reverse']['chip']}；"
                f"倒放 {facts['reverse']['before']} → {facts['reverse']['after']}"
            )

            # ① 停着的时候没有牌子；L 一次 1x、再一次 2x。
            assert facts["idle"]["chip"] is None, facts["idle"]
            # 1x 正常走带不挂牌子——那枚牌子只说「现在不是 1x」。
            assert facts["afterL1"]["chip"] is None, facts["afterL1"]
            assert facts["afterL1"]["timecode"] != facts["idle"]["timecode"], facts["afterL1"]
            assert facts["afterL2"]["chip"] == "2x", facts["afterL2"]
            assert facts["afterL2"]["chipLabel"] == "播放速度 2 倍", facts["afterL2"]

            # ② J 之后牌子是 -1x，时间码真的往回走。
            reverse = facts["reverse"]
            assert reverse["chip"] == "-1x", reverse
            assert (
                reverse["beforeSeconds"] is not None and reverse["afterSeconds"] is not None
            ), reverse
            assert reverse["afterSeconds"] < reverse["beforeSeconds"] - 0.15, reverse

            # ③ K 之后牌子消失，两次采样时间码相同（不再动）。
            stopped = facts["stopped"]
            assert stopped["first"]["chip"] is None, stopped
            assert stopped["equal"] is True, stopped

            # ④ 在 0 处按 J：不启动，时间码停在 0，牌子不出现。
            start = facts["reverseAtStart"]
            assert start["chip"] is None, start
            assert start["timecode"].startswith("00:00:00:"), start
        finally:
            stop(engine)

    print(
        f"PASS: J/K/L 走带在真页面里可用（{APP_VERSION}）——L 两次 2x、J 变 -1x 且时间码回退、"
        "K 停下后两次采样不动、0 处按 J 不倒出时间线"
    )


if __name__ == "__main__":
    main()
