"""1.284：整轨粗剪的真页面验收——轨道头「其它操作」→「按镜头粗剪这一轨」，再回引擎读三段。

为什么要有这一档：`roughcut_check.py` 的整轨那一节证明计划与写入对；
壳检证明代码里只有一条路。
两者都说不出「菜单里真有这一项、点得动、按下去真的把整条轨收好」。这一档用真 DOM、真鼠标与真引擎
量这三件事，判据是引擎回执、菜单命中点与截图。

跑法：空闲机器单跑 `uv run python tests/trackui_check.py`
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
# 整轨入口用能力表下发的默认值：1.5 秒。
KEEP = 3 * SECOND // 2


def seed(folder: Path) -> str:
    made = harness.request(
        "/v1/projects", harness.TOKEN, {"request_id": "trackui-new", "name": "整轨粗剪"}, "POST"
    )
    pid = made["project"]["id"]
    video = harness.request(
        "/v1/media/import", harness.TOKEN, {"path": str(folder / "solid.mp4")}, "POST"
    )["verified"]
    still = harness.request(
        "/v1/media/import", harness.TOKEN, {"path": str(folder / "still.png")}, "POST"
    )["verified"]
    commands = [
        {"op": "track.add", "track": {"id": "t", "kind": "video", "name": "画面"}},
        {
            "op": "asset.import", "asset_id": "v", "label": "v",
            "probe_id": video["probe_id"], "verified": video,
        },
        {
            "op": "asset.import", "asset_id": "i", "label": "i",
            "probe_id": still["probe_id"], "verified": still,
        },
        {
            "op": "clip.add",
            "clip": {"id": "a", "asset_id": "v", "track_id": "t",
                     "position_ticks": 0, "duration_ticks": 3 * SECOND},
        },
        {
            "op": "clip.add",
            "clip": {"id": "b", "asset_id": "v", "track_id": "t",
                     "position_ticks": 5 * SECOND, "duration_ticks": 3 * SECOND},
        },
        {
            "op": "clip.add",
            "clip": {"id": "s", "asset_id": "i", "track_id": "t",
                     "position_ticks": 9 * SECOND, "duration_ticks": 2 * SECOND},
        },
    ]
    harness.request(
        f"/v1/projects/{pid}/edits",
        harness.TOKEN,
        {
            "request_id": "trackui-seed",
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
    with tempfile.TemporaryDirectory(prefix="agentcut-trackui-") as raw:
        folder = Path(raw)
        solid = harness.solid(folder) if hasattr(harness, "solid") else None
        if solid is None:
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
        still = folder / "still.png"
        subprocess.run(
            [
                str(harness.FFMPEG), "-v", "error", "-y", "-nostdin",
                "-f", "lavfi", "-i", "color=c=0x884422:s=320x180", "-frames:v", "1", str(still),
            ],
            capture_output=True,
            timeout=300,
        )
        engine = harness.run_engine(folder)
        try:
            pid = seed(folder)
            out = folder / "track.json"
            shot = folder / "track.png"
            ran = subprocess.run(
                [
                    "node", str(harness.PROBE),
                    "--renderer", str(harness.RENDERER),
                    "--engine", f"http://127.0.0.1:{harness.PORT}",
                    "--token", harness.TOKEN,
                    "--project", pid,
                    "--size", "1456x808",
                    "--action", "track",
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

            # ① 轨道头的「其它操作」打开后，菜单里有这一项、点得到、不是灰的。
            more = facts.get("more")
            assert more and more["width"] >= 18 and more["height"] >= 18, more
            item = facts.get("menu")
            assert item, "轨菜单里没有「按镜头粗剪这一轨」"
            assert item["text"].endswith("按镜头粗剪这一轨"), item["text"]
            assert item["disabled"] is False, item
            assert item["box"]["height"] >= 30, item["box"]
            assert item["box"]["width"] >= 120, item["box"]
            print(
                f"   轨道头「其它操作」{more['width']}×{more['height']}px；"
                f"菜单项 {item['box']['width']}×{item['box']['height']}px、可点"
            )

            # ② 点下去：一个 revision；两段画面各留头 1 秒，图片跳过并被 ripple 带到 5 秒。
            before, after = facts["before"], facts.get("after")
            assert after, "点完菜单之后读不到工程"
            assert after["revision"] == before["revision"] + 1, (
                before["revision"], after["revision"]
            )
            clips = {clip["id"]: clip for clip in facts["clips"]}
            assert set(clips) == {"a", "b", "s"}, clips
            assert clips["a"]["position_ticks"] == 0, clips["a"]
            assert clips["a"]["duration_ticks"] == KEEP, clips["a"]
            assert clips["b"]["position_ticks"] == 7 * SECOND // 2, clips["b"]
            assert clips["b"]["duration_ticks"] == KEEP, clips["b"]
            assert clips["s"]["position_ticks"] == 6 * SECOND, clips["s"]
            assert clips["s"]["duration_ticks"] == 2 * SECOND, clips["s"]
            print(
                f"   r{before['revision']} → r{after['revision']}："
                "a 0..1.5、b 3.5..5、图片仍在且被带到 6..8（整轨入口用能力表默认 1.5 秒）"
            )

            size = shot.stat().st_size if shot.is_file() else 0
            assert shot.is_file() and size > 20_000, size
        finally:
            harness.stop(engine)

    print(
        f"PASS: 整轨粗剪在真页面里点得动（{APP_VERSION}）——轨道头「其它操作」打开菜单、"
        "「按镜头粗剪这一轨」可点；一个 revision 后两段画面各留头 1.5 秒、"
        "图片跳过并随 ripple 左移，"
        "截图已落盘"
    )


if __name__ == "__main__":
    main()
