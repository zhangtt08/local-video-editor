"""1.285：EDL 剪辑表的真页面验收——轨道头菜单里那一项、点得动、工程一个字节都不动。

`edl_check.py` 证明文本与时码对；壳检证明只有一处实现。
这一档补上「人点得到、点完不改工程」：
菜单项在真 DOM 里、命中点可点，点完 revision 不动，口播提示要么说复制了几条、要么说剪贴板不可用。

跑法：空闲机器单跑 `uv run python tests/edlui_check.py`
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
        "/v1/projects", harness.TOKEN, {"request_id": "edlui-new", "name": "剪辑表"}, "POST"
    )
    pid = made["project"]["id"]
    probe = harness.request(
        "/v1/media/import", harness.TOKEN, {"path": str(source)}, "POST"
    )["verified"]
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {
            "op": "asset.import", "asset_id": "s", "label": "solid.mp4",
            "probe_id": probe["probe_id"], "verified": probe,
        },
        {
            "op": "clip.add",
            "clip": {"id": "a", "asset_id": "s", "track_id": "v",
                     "position_ticks": 0, "duration_ticks": 3 * SECOND},
        },
    ]
    harness.request(
        f"/v1/projects/{pid}/edits",
        harness.TOKEN,
        {
            "request_id": "edlui-seed",
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
    with tempfile.TemporaryDirectory(prefix="agentcut-edlui-") as raw:
        folder = Path(raw)
        solid = folder / "solid.mp4"
        subprocess.run(
            [
                str(harness.FFMPEG), "-v", "error", "-y", "-nostdin",
                "-f", "lavfi", "-i", "color=c=0x334455:s=320x180:r=30:d=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(solid),
            ],
            capture_output=True,
            timeout=300,
        )
        engine = harness.run_engine(folder)
        try:
            pid = seed(folder, solid)
            out = folder / "edl.json"
            shot = folder / "edl.png"
            ran = subprocess.run(
                [
                    "node", str(harness.PROBE),
                    "--renderer", str(harness.RENDERER),
                    "--engine", f"http://127.0.0.1:{harness.PORT}",
                    "--token", harness.TOKEN,
                    "--project", pid,
                    "--size", "1456x808",
                    "--action", "edl",
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

            item = facts.get("menu")
            assert item, "轨菜单里没有「复制这一轨的 EDL（剪辑表）」"
            assert item["text"].endswith("复制这一轨的 EDL（剪辑表）"), item["text"]
            assert item["disabled"] is False, item
            assert item["box"]["height"] >= 30, item["box"]
            assert item["box"]["width"] >= 160, item["box"]
            print(
                f"   菜单项 {item['box']['width']}×{item['box']['height']}px、可点：{item['text']}"
            )

            before, after = facts["before"], facts.get("after")
            assert after, "点完菜单之后读不到工程"
            assert after["revision"] == before["revision"], (
                "剪辑表是只读导出，revision 不该动",
                before["revision"],
                after["revision"],
            )
            toast = facts.get("toast") or ""
            assert "EDL" in toast or "剪贴板" in toast, toast
            assert len(facts["clips"]) == 1, facts["clips"]
            print(f"   revision 仍是 {after['revision']}；口播：{toast[:48]}")

            size = shot.stat().st_size if shot.is_file() else 0
            assert shot.is_file() and size > 20_000, size
        finally:
            harness.stop(engine)

    print(
        f"PASS: EDL 剪辑表在真页面里点得动（{APP_VERSION}）——轨道头菜单那一项可点，"
        "点完工程 revision 一动不动，口播说明复制或剪贴板状态，截图已落盘"
    )


if __name__ == "__main__":
    main()
