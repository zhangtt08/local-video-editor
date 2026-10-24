"""1.278：时间线右键菜单——真窗口里右键、真点一项、真看焦点落在哪。

为什么要有这一档：`keymap.ts` 里 `duplicate` 那条命令的孪生说明一直写着「片段右键菜单」，
可菜单从来没画出来过。壳检只能钉住「源码里有 onContextMenu」，钉不出「右键那一下选择了这一段」
「菜单整个盒子在视口里」「Escape 之后焦点回到片段上」「点一项真的写进去一个版本」。这些只有
真 DOM 量得到，所以这里起随包引擎 + 构建好的渲染层，用 Edge 的 CDP 发真的鼠标右键与键盘。

跑法：空闲机器单跑 `uv run python tests/contextmenu_check.py`（要渲染层构建产物、node、Edge、
随包 ffmpeg；缺一样就点名，不许静悄悄跳过）。
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
PROBE = ROOT / "scripts/ui_menu_probe.cjs"
EDGE = Path(
    os.environ.get(
        "AGENTCUT_EDGE",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    )
)
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TOKEN = "contextmenucheck" + "c" * 32
SECOND = 70_560_000
FONT_FLOOR = 12.5
# 菜单上的那几条必须与 keymap 那张表说同一句话——这里不抄字面量，判据是「读到的标签里有它」。
WANTED = ("在播放头处剪开选中片段", "复制选中的片段组", "粘贴到播放头", "追加整组副本",
          "删除选中片段，留空隙", "删除并向左补齐", "组合", "取消组合", "音画链接", "解除音画链接")
LANE_WANTED = ("粘贴到播放头", "选中全部片段", "在播放头记一个标记")

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


def seed_project(token: str) -> str:
    """两段四秒的图板：右键落在第二段上时，第一段还画在左边——「选中变没变」才看得出来。"""
    made = request("/v1/projects", token, {"request_id": "menu-new", "name": "右键菜单"}, "POST")
    pid = made["project"]["id"]
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {"op": "asset.register", "asset": {"id": "m", "kind": "image", "label": "图板", "reference": "untrusted"}},
    ]
    for index, clip_id in enumerate(("k1", "k2")):
        commands.append({
            "op": "clip.add",
            "clip": {
                "id": clip_id, "asset_id": "m", "track_id": "v",
                "position_ticks": index * 4 * SECOND, "duration_ticks": 4 * SECOND,
            },
        })
    request(
        f"/v1/projects/{pid}/edits",
        token,
        {"request_id": "menu-seed", "expected_revision": made["project"]["revision"], "commands": commands},
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
            json.loads(line)
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


def menu_by_label(menu: dict | None, label: str) -> dict:
    assert menu, "菜单没有画出来"
    for item in menu["items"]:
        if item["label"] == label:
            return item
    raise AssertionError(f"菜单里没有「{label}」：{[item['label'] for item in menu['items']]}")


def main() -> None:
    global PORT
    for path, why in ((RENDERER, "渲染层没有构建（cd desktop && npm run build:renderer）"),
                      (PROBE, "量具脚本不见了"),
                      (EDGE, "没有 Edge"),
                      (FFMPEG, "随包 ffmpeg 不见了")):
        if not Path(path).exists():
            fail(f"{why}：{path}")
    PORT = free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-menu-") as raw:
        folder = Path(raw)
        engine = run_engine(folder)
        try:
            pid = seed_project(TOKEN)
            out = folder / "menu.json"
            ran = subprocess.run(
                [
                    "node", str(PROBE),
                    "--renderer", str(RENDERER),
                    "--engine", f"http://127.0.0.1:{PORT}",
                    "--token", TOKEN,
                    "--project", pid,
                    "--size", "1456x808",
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
                fail("量具没跑完：" + (ran.stderr or ran.stdout)[-800:])
            facts = json.loads(out.read_text(encoding="utf-8"))
            assert facts.get("clipsOnScreen", 0) >= 2, facts.get("clipsOnScreen")
            page = facts.get("menu")
            assert page, "右键之后菜单没有画出来"
            print(f"   菜单 {page['rect']['width']}×{page['rect']['height']}，圆角 {page['radius']}px，"
                  f"{len(page['items'])} 项，焦点在「{page['focusedLabel']}」")

            # ① 身份与标题：这是「片段操作」，标题写的是被点的那一段。
            assert page["role"] == "menu", page["role"]
            assert page["label"] == "片段操作", page["label"]
            assert page["title"] == "图板", page["title"]
            assert page["titleFont"] >= FONT_FLOOR, page["titleFont"]
            assert page["radius"] >= 12, f"菜单圆角 {page['radius']}px——苹果那套是抬起来的圆角面板"

            # ② 每一条都在，且与 keymap 那张表说同一句话；键位提示也是那一份。
            labels = [item["label"] for item in page["items"]]
            for wanted in WANTED:
                assert wanted in labels, f"菜单少了「{wanted}」：{labels}"
            duplicate = menu_by_label(page, "追加整组副本")
            assert duplicate["hint"].startswith("Ctrl / ⌘ + "), duplicate["hint"]
            assert menu_by_label(page, "粘贴到播放头")["hint"].endswith("V"), menu_by_label(page, "粘贴到播放头")
            assert duplicate["font"] >= FONT_FLOOR, duplicate["font"]
            assert all(item["height"] >= 34 for item in page["items"]), [item["height"] for item in page["items"]]

            # ③ 焦点进得去、方向键在能按的项之间走、回来还在原处。
            assert page["focused"] == "menuitem", page["focused"]
            assert facts.get("afterArrowDown") and facts.get("afterArrowDown") != page["focusedLabel"], facts.get("afterArrowDown")
            assert facts.get("afterArrowUp") == page["focusedLabel"], (facts.get("afterArrowUp"), page["focusedLabel"])

            # ④ 右键落在没选中的片段上：选中的是它，且只有它。
            assert facts.get("selectedAfterRightClick") == 1, facts.get("selectedAfterRightClick")
            assert facts.get("clipPressedAfterRightClick") == "true", facts.get("clipPressedAfterRightClick")

            # ⑤ 菜单整个盒子在视口里。
            box, size = page["rect"], facts["viewport"]
            assert box["left"] >= 0 and box["top"] >= 0, box
            assert box["right"] <= size["width"] and box["bottom"] <= size["height"], (box, size)

            # ⑥ 点一项真的写进去：追加整组副本 → 一个版本、一段新片段、菜单自己关掉。
            assert facts.get("menuAfterRun") is None, "点完之后菜单还开着"
            before, after = facts["before"], facts["after"]
            assert after["revision"] == before["revision"] + 1, (before, after)
            assert after["clips"] == before["clips"] + 1, (before, after)

            # ⑦ Escape 关掉，焦点交回那个片段。
            assert facts.get("menuBeforeEscape"), "第二次右键没开出来"
            assert facts.get("menuAfterEscape") is None, "Escape 没关掉菜单"
            assert facts.get("focusAfterEscape") == facts["clip"]["id"], facts.get("focusAfterEscape")

            # ⑧ 空白处是另一份菜单，标题写明是哪一轨。
            lane = facts.get("laneMenu")
            assert lane, "空白处右键没有菜单"
            assert lane["label"] == "时间线空白处操作", lane["label"]
            assert "空白处" in lane["title"], lane["title"]
            lane_labels = [item["label"] for item in lane["items"]]
            for wanted in LANE_WANTED:
                assert wanted in lane_labels, f"空白处菜单少了「{wanted}」：{lane_labels}"

            # ⑨ 右下角打开：翻到指针上方，整个盒子仍在窗口里。
            corner = facts.get("cornerMenu")
            assert corner, "右下角那一格没有菜单"
            rect, size = corner["rect"], facts["cornerTarget"]
            assert rect["right"] <= size["w"] - 7, (rect, size)
            assert rect["bottom"] <= size["h"] - 3, (rect, size)
            assert rect["top"] >= 8, rect
            assert rect["bottom"] <= size["h"] - 4 + 1, "没有翻到指针上方"
            assert facts.get("menuAtEnd") is None, "最后那一份菜单没收掉"
            print(f"   右下角：菜单翻到指针上方，右缘 {rect['right']} ≤ {size['w'] - 8}，"
                  f"下缘 {rect['bottom']} ≤ {size['h'] - 4}")
            print(f"   Escape 之后焦点回到片段 {facts['focusAfterEscape']}；"
                  f"追加副本 revision {before['revision']} → {after['revision']}、"
                  f"片段 {before['clips']} → {after['clips']}")
        finally:
            stop(engine)

    print(
        f"PASS: 右键菜单在真窗口里画得出来（{APP_VERSION}）——右键选中被点的那一段、"
        "焦点进得去且 Escape 交得回、右下角翻到指针上方且整个盒子在视口里、"
        "点「追加整组副本」一个版本一段新片段、空白处是另一份写明轨道名的菜单；"
        "每一条标签与键位都读 keymap 那一份，菜单自己不造第二个名字"
    )


if __name__ == "__main__":
    main()
