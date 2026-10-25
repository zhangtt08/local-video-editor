"""1.289：深交互审计——选中、展开每一节、开菜单、开帮助、切页签，量每个按钮点不点得到。

为什么要有这一档：界面形状扫描不选片段、也不展开折叠节；两个真实交付缺陷（片段操作藏在闭合
details 里、检查器那一行把按钮撑出右缘）都是「真选中 + 真展开」才量到的。这一档把九个作用域
逐个数出来，判据是：可见按钮的中心点必须命中它自己、滚动容器不许横向溢出。

跑法：空闲机器单跑 `uv run python tests/deepui_check.py`
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
PROBE = ROOT / "scripts/ui_deep_probe.cjs"
SCOPES = (
    "clip",
    "multi",
    "track-menu",
    "clip-menu",
    "help",
    "help-search",
    "export",
    "scopes",
    "inspector",
)


def seed(folder: Path) -> str:
    source = harness.three_shots(folder)
    made = harness.request(
        "/v1/projects", harness.TOKEN, {"request_id": "deepui-new", "name": "深审计"}, "POST"
    )
    pid = made["project"]["id"]
    probe = harness.request(
        "/v1/media/import", harness.TOKEN, {"path": str(source)}, "POST"
    )["verified"]
    commands = [
        {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "机位一"}},
        {"op": "track.add", "track": {"id": "v2", "kind": "video", "name": "机位二"}},
        {
            "op": "asset.import", "asset_id": "s", "label": "shots.mp4",
            "probe_id": probe["probe_id"], "verified": probe,
        },
        {
            "op": "clip.add",
            "clip": {"id": "a", "asset_id": "s", "track_id": "v1",
                     "position_ticks": 0, "duration_ticks": 6 * SECOND},
        },
        {
            "op": "clip.add",
            "clip": {"id": "b", "asset_id": "s", "track_id": "v2",
                     "position_ticks": 7 * SECOND, "duration_ticks": 6 * SECOND},
        },
    ]
    harness.request(
        f"/v1/projects/{pid}/edits",
        harness.TOKEN,
        {
            "request_id": "deepui-seed",
            "expected_revision": made["project"]["revision"],
            "commands": commands,
        },
        "POST",
    )
    return pid


def main() -> None:
    for path, why in (
        (harness.RENDERER, "渲染层没有构建（cd desktop && npm run build:renderer）"),
        (PROBE, "量具脚本不见了"),
        (harness.EDGE, "没有 Edge"),
        (harness.FFMPEG, "随包 ffmpeg 不见了"),
    ):
        if not Path(path).exists():
            harness.fail(f"{why}：{path}")
    harness.PORT = harness.free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-deepui-") as raw:
        folder = Path(raw)
        engine = harness.run_engine(folder)
        try:
            pid = seed(folder)
            out = folder / "deep.json"
            shot = folder / "deep.png"
            ran = subprocess.run(
                [
                    "node", str(PROBE),
                    "--renderer", str(harness.RENDERER),
                    "--engine", f"http://127.0.0.1:{harness.PORT}",
                    "--token", harness.TOKEN,
                    "--project", pid,
                    "--size", "1456x808",
                    "--out", str(out),
                    "--shot", str(shot),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                cwd=str(ROOT),
            )
            if ran.returncode != 0 or not out.is_file():
                harness.fail("量具没跑完：" + (ran.stderr or ran.stdout)[-900:])
            facts = json.loads(out.read_text(encoding="utf-8"))
            scopes = facts.get("scopes") or {}
            missing = [scope for scope in SCOPES if scope not in scopes]
            assert not missing, f"这些作用域没量到：{missing}（量到 {sorted(scopes)}）"

            problems = []
            for scope in SCOPES:
                found = scopes[scope]
                assert found["buttons"] > 0, (scope, "一个可见按钮都没有")
                for item in found["cut"]:
                    where = item.get("by") or ""
                    problems.append(f"{scope}: 「{item['what']}」{item['why']} {where}")
                for item in found["overflow"]:
                    problems.append(
                        f"{scope}: {item['cls']} 横向溢出 {item['scroll']} > {item['client']}"
                    )
            assert not problems, "\n".join(problems)
            print(
                "   "
                + "；".join(f"{scope} {scopes[scope]['buttons']}" for scope in SCOPES)
                + " 个可见按钮，全部命中自己、无横向溢出"
            )

            size = shot.stat().st_size if shot.is_file() else 0
            assert shot.is_file() and size > 20_000, size
        finally:
            harness.stop(engine)

    print(
        f"PASS: 深交互审计（{APP_VERSION}）——选中/多选/轨菜单/片段右键/"
        "帮助与搜索/三个页签共 9 个作用域，每个可见按钮的中心点都命中自己，"
        "滚动容器没有横向溢出，截图已落盘"
    )


if __name__ == "__main__":
    main()
