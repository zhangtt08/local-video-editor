"""1.288：多机位对齐的真页面验收——多选两段、按「对齐多机位」，再回引擎读位置。

素材是同一段 0.1 秒的噪声，第二份晚 0.8 秒。判据是引擎里的位置：基准留在 2 秒，另一路到 1.2 秒。

跑法：空闲机器单跑 `uv run python tests/syncui_check.py`
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


def burst(folder: Path, name: str, offset_ms: int) -> Path:
    target = folder / name
    subprocess.run(
        [
            str(harness.FFMPEG), "-v", "error", "-y", "-nostdin",
            "-f", "lavfi", "-i", "anoisesrc=d=0.1:c=pink:r=48000:a=0.8:seed=1234",
            "-af", f"adelay={offset_ms}|{offset_ms},apad=whole_dur=5", "-t", "5", str(target),
        ],
        capture_output=True,
        timeout=300,
    )
    return target


def seed(folder: Path) -> str:
    made = harness.request(
        "/v1/projects", harness.TOKEN, {"request_id": "syncui-new", "name": "多机位"}, "POST"
    )
    pid = made["project"]["id"]
    commands = []
    for index, (clip_id, offset_ms, position) in enumerate((("a", 1000, 2), ("b", 1800, 4))):
        probe = harness.request(
            "/v1/media/import", harness.TOKEN,
            {"path": str(burst(folder, f"{clip_id}.wav", offset_ms))}, "POST",
        )["verified"]
        commands.extend(
            [
                {
                    "op": "track.add",
                    "track": {"id": f"t{index}", "kind": "audio", "name": f"机位{index}"},
                },
                {
                    "op": "asset.import", "asset_id": f"a{index}", "label": f"{clip_id}.wav",
                    "probe_id": probe["probe_id"], "verified": probe,
                },
                {
                    "op": "clip.add",
                    "clip": {"id": clip_id, "asset_id": f"a{index}", "track_id": f"t{index}",
                             "position_ticks": position * SECOND, "duration_ticks": 5 * SECOND},
                },
            ]
        )
    harness.request(
        f"/v1/projects/{pid}/edits",
        harness.TOKEN,
        {
            "request_id": "syncui-seed",
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
    with tempfile.TemporaryDirectory(prefix="agentcut-syncui-") as raw:
        folder = Path(raw)
        engine = harness.run_engine(folder)
        try:
            pid = seed(folder)
            out = folder / "sync.json"
            shot = folder / "sync.png"
            ran = subprocess.run(
                [
                    "node", str(harness.PROBE),
                    "--renderer", str(harness.RENDERER),
                    "--engine", f"http://127.0.0.1:{harness.PORT}",
                    "--token", harness.TOKEN,
                    "--project", pid,
                    "--size", "1456x808",
                    "--action", "sync",
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

            assert facts.get("selection") == 2, ("Ctrl 点选没有选中两段", facts.get("selection"))
            button = facts.get("button")
            assert button and button["text"] == "对齐多机位", button
            assert button["disabled"] is False, button
            assert button["hitSelf"] is True, button
            assert button["box"]["height"] >= 28, button["box"]
            print(
                f"   两段选中；按钮 {button['box']['width']}×{button['box']['height']}px、"
                "命中点是自己"
            )

            before, after = facts["before"], facts.get("after")
            assert after, "按了按钮之后读不到工程"
            assert after["revision"] == before["revision"] + 1, (
                before["revision"], after["revision"], facts.get("toast")
            )
            clips = {clip["id"]: clip for clip in facts["clips"]}
            assert clips["a"]["position_ticks"] == 2 * SECOND, clips["a"]
            assert clips["b"]["position_ticks"] == 2 * SECOND - 24 * 2_352_000, clips["b"]
            print(
                f"   r{before['revision']} → r{after['revision']}：a 仍在 2 秒、b 到 "
                f"{clips['b']['position_ticks'] / SECOND:.2f} 秒"
            )

            size = shot.stat().st_size if shot.is_file() else 0
            assert shot.is_file() and size > 20_000, size
        finally:
            harness.stop(engine)

    print(
        f"PASS: 多机位对齐在真页面里点得动（{APP_VERSION}）——Ctrl 多选两段、按钮可点，"
        "一个 revision 后基准不动、另一路对齐到 1.2 秒，截图已落盘"
    )


if __name__ == "__main__":
    main()
