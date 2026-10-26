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
# 装机窗口里那五颗工具胶囊的名字，按屏幕上的顺序点出来。1.294 把「历史与视图 / 加轨道」
# 两胶囊收进「更多」（复制属性、按标记切开、加轨道、适应窗口都在那份菜单里，走的还是同一批
# store 函数），1.296 又给「更多」补上自己的胶囊——名单跟着改，但少一颗、换名字、调顺序仍红。
LABELS = ("工具", "剪辑", "吸附与标记", "历史", "更多")


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def main() -> None:
    for path, why in ((EXE, "发布包没有解包目录（先 cd desktop && npm run dist）"),
                      (PROBE, "量具脚本不见了")):
        if not Path(path).exists():
            fail(f"{why}：{path}")
    # 窗口收干净之后，Chromium 仍可能压着 profile 里那份词典文件不放，rmtree 会在最后一秒报
    # WinError 32。含糊不得：忽略清理错误的同时，下面当场量一次「机器上还剩几个 AgentCut 进程」——
    # 残留的进程才是真问题，删不掉的临时目录只是它的影子。
    with tempfile.TemporaryDirectory(
        prefix="agentcut-packaged-ui-", ignore_cleanup_errors=True
    ) as raw:
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

        # ⓪ 1.308 打开窗口那一下：画出来的是外壳，不是那块全屏门；工程列表还没读到，
        # 那一格是待填的骨架而不是「还没有工程」这句假话。引擎是这腿的第一记真点击叫起来的
        # （令牌在场与否由量具当场查过，不在就红）。
        opened = facts["openState"]
        assert opened["shell"] is True and opened["bootScreen"] is False, opened
        assert opened["skeleton"] >= 1, f"没读到工程时该留待填的骨架：{opened}"

        # ① 窗口与引擎说的是同一版。
        assert facts["versionOnScreen"] == APP_VERSION, facts["versionOnScreen"]
        assert facts["engineVersion"] == APP_VERSION, facts["engineVersion"]

        # ② 拾起来的表面：三块卡片与时间线都走大圆角，宽窗里有 10px 呼吸位。
        assert editor["panelRadius"] >= 15, editor["panelRadius"]
        assert editor["timelineRadius"] >= 15, editor["timelineRadius"]
        assert editor["mathGutter"] == 10, editor["mathGutter"]
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

        # ⑤′ 关掉软件不该留下一台引擎：窗口自己走完关闭那一路之后，机器上一台都不许在。
        assert facts.get("engineAfterQuit") == 0, ("关掉窗口后机器上还留着 " + str(facts.get("engineAfterQuit")) + " 台引擎进程")
        # ⑤ 字号地板：正文仍是 14px（不是小字）。
        assert editor["bodyFont"] >= 13.5, editor["bodyFont"]

        # ⑥ 证据照片写得出来，且不是一张空白。
        size = shot.stat().st_size if shot.is_file() else 0
        assert shot.is_file() and size > 20_000, size

    # 临时目录删不掉是影子，进程还挂着才是问题：这一腿跑完机器上一台 AgentCut 都不该留下。
    left = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq AgentCut.exe"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout
    assert "AgentCut.exe" not in left, "装机腿跑完机器上还挂着窗口：" + left[:220]

    print(
        f"PASS: 发布包真窗口（{APP_VERSION}）里工作台是圆角卡片 + 10px 呼吸位 + 五枚工具胶囊，"
        "走带是胶囊，轨道头只有锁定/显隐/更多三颗，正文 14px，截图已落盘"
    )


if __name__ == "__main__":
    main()
