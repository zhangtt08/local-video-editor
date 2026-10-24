"""1.279：装机的界面那一腿——真发布包开起来，工作台是圆角卡片、工具是五枚胶囊、轨道头三颗按钮。

为什么要有这一档：`released_package_check` 证明 asar 里带着新的 CSS 与句子，`ui_shape_check`
量的是开发树那份渲染层；两者都说不出「装到机器上的那个 exe 画出来是什么形状」。
这一档开真包、用它自己的引擎建一个空工程、按命中点点开，读的是 getComputedStyle 与 DOM 计数。

跑法：空闲机器单跑 `uv run python tests/packaged_ui_check.py`。缺包、缺 node、缺 CDP 都点名，
不许静悄悄跳过。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import APP_VERSION  # noqa: E402

EXE = ROOT / "desktop/release/win-unpacked/AgentCut.exe"
PROBE = ROOT / "scripts/packaged_ui_probe.cjs"
LABELS = ("工具", "剪辑", "吸附与标记", "历史与视图", "加轨道")


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def main() -> None:
    for path, why in ((EXE, "发布包没有解包目录（先 cd desktop && npm run dist）"),
                      (PROBE, "量具脚本不见了")):
        if not Path(path).exists():
            fail(f"{why}：{path}")
    with tempfile.TemporaryDirectory(prefix="agentcut-packaged-ui-") as raw:
        folder = Path(raw)
        out = folder / "ui.json"
        shot = folder / "ui.png"
        ran = subprocess.run(
            [
                "node", str(PROBE),
                "--exe", str(EXE),
                "--profile", str(folder / "profile"),
                "--out", str(out),
                "--shot", str(shot),
                "--version", APP_VERSION,
                "--port", "9391",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=420,
            cwd=str(ROOT),
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        if ran.returncode != 0 or not out.is_file():
            fail("量具没跑完：" + (ran.stderr or ran.stdout)[-900:])
        facts = json.loads(out.read_text(encoding="utf-8"))
        editor = facts["editor"]
        print(
            f"   装机工作台 {editor['viewport']['width']}×{editor['viewport']['height']}："
            f"卡片圆角 {editor['panelRadius']}px、时间线 {editor['timelineRadius']}px、"
            f"走带胶囊 {editor['transportRadius']}px、呼吸位 {editor['mathGutter']}px、"
            f"工具胶囊 {editor['tools']} 枚、轨道头 {editor['trackButtons']} 颗按钮"
        )

        # ① 窗口与引擎说的是同一版。
        assert facts["versionOnScreen"] == APP_VERSION, facts["versionOnScreen"]
        assert facts["engineVersion"] == APP_VERSION, facts["engineVersion"]

        # ② 拾起来的表面：三块卡片与时间线都走大圆角，宽窗里有 8px 呼吸位。
        assert editor["panelRadius"] >= 15, editor["panelRadius"]
        assert editor["timelineRadius"] >= 15, editor["timelineRadius"]
        assert editor["mathGutter"] == 8, editor["mathGutter"]
        assert editor["transportRadius"] >= 100, editor["transportRadius"]

        # ③ 工具按事情分组：正好五枚胶囊，名字与那一排的 aria-label 一致。
        assert editor["tools"] == 5, editor["tools"]
        assert tuple(facts["toolLabels"]) == LABELS, facts["toolLabels"]

        # ④ 轨道头只剩三颗：锁定、显隐/静音、更多。
        assert editor["trackButtons"] == 3, editor["trackButtons"]
        names = facts["trackHeadNames"]
        assert len(names) == 3, names
        assert any("锁定" in name for name in names), names
        assert any("其它操作" in name for name in names), names

        # ⑤ 字号地板：正文仍是 14px（不是小字）。
        assert editor["bodyFont"] >= 13.5, editor["bodyFont"]

        # ⑥ 证据照片写得出来，且不是一张空白。
        size = shot.stat().st_size if shot.is_file() else 0
        assert shot.is_file() and size > 20_000, size

    print(
        f"PASS: 发布包真窗口（{APP_VERSION}）里工作台是圆角卡片 + 8px 呼吸位 + 五枚工具胶囊，"
        "走带是胶囊，轨道头只有锁定/显隐/更多三颗，正文 14px，截图已落盘"
    )


if __name__ == "__main__":
    main()
