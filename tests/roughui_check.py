"""1.283：按镜头粗剪的真页面验收——选中三段镜头的那一段、按那颗按钮，再回引擎读切出来的三段。

为什么要有这一档：`roughcut_check.py` 证明计划与写入对；壳检证明源码里只有一套判断。
两者都说不出「检查器里真有那格秒数与那颗按钮、填了 1 秒按下去，工程里真的只剩 3 秒」。
这一档用真 DOM、真鼠标、真的键盘写入与真引擎量这三件事，判据是引擎回执、DOM 几何与命中点。

跑法：空闲机器单跑 `uv run python tests/roughui_check.py`（要渲染层构建产物、node、Edge、
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
PROBE = ROOT / "scripts/ui_scene_probe.cjs"
EDGE = Path(
    os.environ.get("AGENTCUT_EDGE", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
)
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TOKEN = "roughuicheck" + "r" * 52
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


def three_shots(folder: Path) -> Path:
    """2 s red, 2 s green, 2 s blue — red and green have (almost) the same luma on purpose."""
    target = folder / "shots.mp4"
    done = subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y", "-nostdin",
            "-f", "lavfi", "-i", "color=c=#ff0000:s=320x180:r=30:d=2",
            "-f", "lavfi", "-i", "color=c=#008000:s=320x180:r=30:d=2",
            "-f", "lavfi", "-i", "color=c=#0000ff:s=320x180:r=30:d=2",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
        ],
        capture_output=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-500:]
    return target


def seed(folder: Path, source: Path) -> str:
    made = request("/v1/projects", TOKEN, {"request_id": "roughui-new", "name": "粗剪"}, "POST")
    pid = made["project"]["id"]
    probe = request("/v1/media/import", TOKEN, {"path": str(source)}, "POST")["verified"]
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {
            "op": "asset.import", "asset_id": "s", "label": "三段",
            "probe_id": probe["probe_id"], "verified": probe,
        },
        {
            "op": "clip.add",
            "clip": {"id": "c", "asset_id": "s", "track_id": "v",
                     "position_ticks": 0, "duration_ticks": 6 * SECOND},
        },
    ]
    request(
        f"/v1/projects/{pid}/edits",
        TOKEN,
        {
            "request_id": "roughui-seed",
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
    with tempfile.TemporaryDirectory(prefix="agentcut-roughui-") as raw:
        folder = Path(raw)
        source = three_shots(folder)
        engine = run_engine(folder)
        try:
            pid = seed(folder, source)
            out = folder / "rough.json"
            shot = folder / "rough.png"
            ran = subprocess.run(
                [
                    "node", str(PROBE),
                    "--renderer", str(RENDERER),
                    "--engine", f"http://127.0.0.1:{PORT}",
                    "--token", TOKEN,
                    "--project", pid,
                    "--size", "1456x808",
                    "--action", "rough",
                    "--out", str(out),
                    "--shot", str(shot),
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

            # ① 那格秒数与按钮都画得出来、能按，而且在这一套刻度里。
            keep = facts.get("keep")
            assert keep, "检查器里没有「粗剪每镜」这一格"
            assert keep["placeholder"] == "1.5", keep
            assert keep["min"] == "0.1" and keep["max"] == "30", keep
            assert keep["value"] == "1", keep
            button = facts.get("button")
            assert button, "检查器里没有「粗剪」"
            assert button["text"] == "粗剪", button["text"]
            assert button["disabled"] is False, button
            assert button["hitSelf"] is True, ("按钮中心点不到自己", button)
            assert 28 <= button["box"]["height"] <= 46, button["box"]
            assert button["font"] >= 13, button["font"]
            assert button["radius"] >= 8, button["radius"]
            assert "镜头" in button["title"] or "每镜" in button["title"], button["title"]
            panel = (facts.get("button") or {}).get("panel")
            assert panel, ("量不到检查器那一栏的宽度", facts.get("button"))
            assert panel["scroll"] <= panel["client"] + 1, ("检查器横向溢出", panel)
            assert panel["buttonRight"] <= panel["right"], ("按钮超出面板右缘", panel)
            assert panel["cutButtons"] == 0, ("有按钮被面板右缘切掉", panel)
            print(
                f"   每镜留 {keep['value']} 秒"
                f"（占位 {keep['placeholder']}、{keep['min']}–{keep['max']}）；"
                f"按钮 {button['box']['width']}×{button['box']['height']}px、"
                f"字号 {button['font']}px、圆角 {button['radius']}px、命中点是自己"
            )

            # ② 按下去之后工程里只剩三个 1 秒的镜头，首尾相接。
            before, after = facts["before"], facts.get("after")
            assert after, "按了按钮之后读不到工程"
            assert after["revision"] == before["revision"] + 1, (
                before["revision"], after["revision"]
            )
            clips = facts["clips"]
            assert len(clips) == 3, clips
            assert clips[0]["position_ticks"] == 0, clips
            for left, right in zip(clips, clips[1:]):
                assert (
                    left["position_ticks"] + left["duration_ticks"] == right["position_ticks"]
                ), clips
            assert [clip["duration_ticks"] for clip in clips] == [SECOND] * 3, clips
            assert clips[-1]["position_ticks"] + clips[-1]["duration_ticks"] == 3 * SECOND, clips
            print(
                f"   r{before['revision']} → r{after['revision']}，三段各 "
                f"{[round(clip['duration_ticks'] / SECOND, 3) for clip in clips]} 秒首尾相接"
            )

            size = shot.stat().st_size if shot.is_file() else 0
            assert shot.is_file() and size > 20_000, size
        finally:
            stop(engine)

    print(
        f"PASS: 按镜头粗剪在真页面里按得动（{APP_VERSION}）——"
        "那格秒数的占位与上下限来自能力表、按钮在与正文同一套刻度里且命中点是自己；"
        "填 1 秒按下去，引擎一个 revision 之后只剩三段 1/1/1 秒首尾相接，截图已落盘"
    )


if __name__ == "__main__":
    main()
