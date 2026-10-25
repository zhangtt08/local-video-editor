"""1.286：粗剪取法「挑动」的真页面验收——下拉切到挑动、填 1 秒、按下去。

素材是同一段六秒：前三秒冻住、后三秒才有画面变化（没有硬切）。判据是源入点：
留头会读 0 秒，挑动必须读到后三秒里那一段（这里量到 5 秒，因为 1 秒的窗只能落在 5..6）。

跑法：空闲机器单跑 `uv run python tests/livelyui_check.py`
（要渲染层构建产物、node、Edge、随包 ffmpeg）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import sceneui_check as harness  # noqa: E402

from agentcut.contracts import APP_VERSION  # noqa: E402

SECOND = harness.SECOND


def seed(folder: Path, source: Path) -> str:
    made = harness.request(
        "/v1/projects", harness.TOKEN, {"request_id": "livelyui-new", "name": "挑动"}, "POST"
    )
    pid = made["project"]["id"]
    probe = harness.request(
        "/v1/media/import", harness.TOKEN, {"path": str(source)}, "POST"
    )["verified"]
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {
            "op": "asset.import", "asset_id": "s", "label": "frozen.mp4",
            "probe_id": probe["probe_id"], "verified": probe,
        },
        {
            "op": "clip.add",
            "clip": {"id": "c", "asset_id": "s", "track_id": "v",
                     "position_ticks": 0, "duration_ticks": 6 * SECOND},
        },
    ]
    harness.request(
        f"/v1/projects/{pid}/edits",
        harness.TOKEN,
        {
            "request_id": "livelyui-seed",
            "expected_revision": made["project"]["revision"],
            "commands": commands,
        },
        "POST",
    )
    return pid


def main() -> None:
    for path, why in (
        (harness.RENDERER, "渲染层没有构建（cd desktop && npm run build:renderer）"),
        (harness.PROBE, "量具脚本不见了"),
        (harness.EDGE, "没有 Edge"),
        (harness.FFMPEG, "随包 ffmpeg 不见了"),
    ):
        if not Path(path).exists():
            harness.fail(f"{why}：{path}")
    harness.PORT = harness.free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-livelyui-") as raw:
        folder = Path(raw)
        source = folder / "frozen_move.mp4"
        subprocess.run(
            [
                str(harness.FFMPEG), "-v", "error", "-y", "-nostdin",
                "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3",
                "-vf", "tpad=start_duration=3:start_mode=clone", "-t", "6",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
            ],
            capture_output=True,
            timeout=300,
        )
        engine = harness.run_engine(folder)
        try:
            pid = seed(folder, source)
            out = folder / "lively.json"
            shot = folder / "lively.png"
            ran = subprocess.run(
                [
                    "node", str(harness.PROBE),
                    "--renderer", str(harness.RENDERER),
                    "--engine", f"http://127.0.0.1:{harness.PORT}",
                    "--token", harness.TOKEN,
                    "--project", pid,
                    "--size", "1456x808",
                    "--action", "roughlively",
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
                harness.fail("量具没跑完：" + (ran.stderr or ran.stdout)[-900:])
            facts = json.loads(out.read_text(encoding="utf-8"))

            place = facts.get("place")
            assert place, "检查器里没有「粗剪取法」"
            assert place["options"] == ["留头", "挑动", "居中"], place
            assert place["value"] == "lively", place
            seam = facts.get("seam")
            assert seam, "检查器里没有「粗剪接缝」"
            assert seam["options"][0] == "硬切", seam
            assert seam["options"][1].startswith("叠化"), seam
            assert seam["value"] == "0", seam
            button = facts.get("button")
            assert button and button["text"] == "粗剪", button
            assert button["disabled"] is False, button
            assert button["hitSelf"] is True, button
            panel = (facts.get("button") or {}).get("panel")
            assert panel and panel["cutButtons"] == 0, panel
            print(
                f"   取法：{'/'.join(place['options'])}，选中的是 {place['value']}；"
                f"按钮 {button['box']['width']}×{button['box']['height']}px"
            )

            before, after = facts["before"], facts.get("after")
            assert after, "按了按钮之后读不到工程"
            assert after["revision"] == before["revision"] + 1, (
                before["revision"], after["revision"]
            )
            clips = facts["clips"]
            assert len(clips) == 1, clips
            assert clips[0]["duration_ticks"] == SECOND, clips
            assert clips[0]["source_in_ticks"] == 5 * SECOND, clips
            print(
                f"   r{before['revision']} → r{after['revision']}：留下的 1 秒读源 "
                f"{clips[0]['source_in_ticks'] // SECOND}s（不是留头的 0s）"
            )

            size = shot.stat().st_size if shot.is_file() else 0
            assert shot.is_file() and size > 20_000, size
        finally:
            harness.stop(engine)

    print(
        f"PASS: 粗剪「挑动」在真页面里选得动（{APP_VERSION}）——下拉两档、选挑动后按粗剪，"
        "一个 revision 只留后三秒里那 1 秒（源入点 5 秒），截图已落盘"
    )


if __name__ == "__main__":
    main()
