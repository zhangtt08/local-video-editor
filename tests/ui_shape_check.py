"""跨屏形状扫描：把「画出来的东西」变成一条能失败的常驻门禁（1.216 入口第 1 条）。

为什么要有这一档：1.210 那两格 27px/25 行、1.211 那一行被挤成 68px 宽画 5 行，都是**装机截图**
才看出来的——源码里数得清字数，数不清它在屏幕上占几行、多宽、被不被切。既然只有量才知道，
那把尺就必须留在仓库里，而不是留在某一轮的工作目录里（那些目录会被清掉，这一轮的量具就是这样
丢过一次）。

量的五件事都是几何事实，逐条都能反证：

* 每一屏都要量到——点不开、亮了没换屏、探针抛异常，一律算红，不算「跳过」；
* 最小的字不低于样式表自己那一个下限（`--fs-micro` 一类的档位，尺从 CSS 里读，不另抄一份数）；
* 没有 1~5px 的尖角（圆润化定的那条曲线）；
* 没有文字被固定高的容器竖着切掉；
* 没有一个可见控件的中心点被别的元素挡住。

跑法：空闲机器单跑 `uv run python tests/ui_shape_check.py`。缺哪一样前置就点名哪一样
（渲染层没构建、没 node、没随包 FFmpeg、没 Edge），不许静悄悄跳过。
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

RENDERER = ROOT / "desktop/dist/renderer"
SWEEP = ROOT / "scripts/ui_shape_sweep.cjs"
PROBE = ROOT / "scripts/ui_shape_probe.js"
EDGE = Path(
    os.environ.get(
        "AGENTCUT_EDGE",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    )
)
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TOKEN = "uishapecheck" + "a" * 40
SIZES = ("1456x808", "1040x660")
# 右侧那一列的三页里挑两页扫（检查器 / 交付面板）——交付面板是 1.202 那轮欠的、也是这一档
# 第一次能失败的那一处；示波器那一页画的是图，量的还是那几行字。
PANELS = ("inspect", "export")
# 浮层那一档：真点开才画布，所以量之前要先点。1.205 那轮就是「点了没开起来」被当成量不到。
# 「画面中编辑」与「重置布局」是 1.223 补进来的两屏：前者把遮罩参考线与其上的三颗顶点操作
# 画进画面（点了才画的那类），后者把布局恢复默认之后再量一屏——两处的控件与文字以前都不在
# 任何一屏的取样里。
OVERLAYS = ("动画曲线", "示波器", "快捷键", "画面中编辑", "重置布局", "预合成选中片段", "字幕")
# 每一颗浮层该**画出**的那处东西（类名，构建后仍在）。判据写在这里而不是只数几何：
# 「点了才画」那一档，一颗换页的按钮和一颗什么都没干的按钮，字数能量出一样的数。
PAINTED = {
    "动画曲线": ".curve-plot",
    "示波器": ".scope-panel",
    "快捷键": ".help",
    "画面中编辑": ".mask-guide",
    "重置布局": ".clip",
    # 反方向：用户自己把那条边往上拖，时间线让不动了——这一句**必须**出现。
    "拖高时间线": ".timeline-clamped",
    # 那两扇弹层以前从没进过任何一屏的取样（1.227）：各认自己的标题，点开一扇错的也算不过。
    "预合成选中片段": 'div.dialog[aria-label="预合成选中片段"]',
    "字幕": 'div.dialog[aria-label="导入 SRT 字幕"]',
    # 文字层那一屏（1.227）：只有选中一条文字片段才画得出那四颗色块。
    # 认色块而不是认「有字」——字在别的屏上一样有。
    "文字层": "input[type=color]",
    # 1.245：停在框点那一帧时，卡片上那五个数就是那一枚——认的是那块输入框真的画了出来，
    # 值与那一句由 --boxkey 那一腿在扫描里读（读不到就记成没量到）。
    "框点那一帧": "#stack-0-center_x",
    # 1.246：点第二张调色卡才展开的那一格（矩阵系数）。
    "调色节点": "#grade-matrix-0-0",
    # 1.251：真点「复制第 1 块」之后画出来的第三块（它的宽度那一格）。
    "复制再叠遮罩": "#stack-2-width",
    # 1.252：选中一块之后画面里那颗柄拖出来的虚线框。
    "画面拖再叠遮罩": ".mask-extra-outline",
    # 1.255：停在两枚框点之间也画那一框（引擎窗表执行的那一格），拖它新打一枚。
    "画面打新框点": ".mask-extra-outline",
    # 1.256：Alt 拖出来的那一副本（检查器里第三块的宽度那一格）。
    "画面Alt拖出副本": "#stack-2-width",
    # 1.257：框点选了贝塞尔之后，那一行四格画出来才算这一屏画了东西。
    "框点带贝塞尔": "div.mask-stack-bezier",
}
# 反过来：某一屏**不许**出现的那一行。「重置布局」按下去之后还挂着「窗口太矮」，
# 说的是应用自己要了一个这一屏装不下的数，再回头抱怨用户——那一行在别的屏上是诚实
# （用户把那条边拖高过），在重置之后就不是。
QUIET = {"剪辑": ".timeline-clamped", "重置布局": ".timeline-clamped"}
# 1.228：卡片里的字与针道分成上下两条带之后，「字压字」一处都不许有——不是一笔可以慢慢还的
# 账。两块不透明的字叠在一起，总有一块是读不到的（1.227 那张截图里 `图板` 只剩 `板`）。
# 读的人只需要前六条明细，但**总数照实要求为零**。
# 圆润化那一条曲线的下限与字号下限，都从 styles.css 里读；这里的两个数是**判断**：
# 字号地板不许低于 12.5px（1.216 之前量到的是 11.5px），曲线上不许出现 1~5px 的尖角。
FONT_FLOOR = 12.5


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def minimum_font_step() -> float:
    """样式表里最小的那一档字号——尺读产品自己声明的那一份，不另抄数。"""
    css = (ROOT / "desktop/src/styles.css").read_text(encoding="utf-8")
    steps = [float(value) for value in re.findall(r"--fs-[a-z]+:\s*([\d.]+)px", css)]
    if not steps:
        fail("desktop/src/styles.css 里没有 --fs-* 字号档位，这一档的尺失去来源")
    return min(steps)


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
        # 拒绝必须把自己说的那句话带回来，不然排查只能靠猜。
        detail = error.read().decode("utf-8", errors="replace")[:600]
        raise AssertionError(f"{method} {path} -> {error.code}: {detail}") from None


def seed_project(token: str) -> str:
    """一条视频轨 + 三段带针的片段 + 一条有中文名的合成——界面得有真东西才量得出形状。

    1.219 把这几段的长度改成**人真正会剪的那个数**：一秒 70_560_000 格（TIMEBASE），一格 2_352_000
    （默认 30 fps）。原来这里写的是 `4 * 2_352_000`——四**格**，0.13 秒：在默认缩放（60 px/s）下
    那一条片段只画 8 px 宽，于是边上的把手、针与转场牌子全挤在同一个 8 px 里。量出来的「重叠」
    是夹具自己造的，不是界面的。夹具不许说谎，这一档量的必须是真时间线。
    """
    made = request("/v1/projects", token, {"request_id": "shape-new", "name": "形状扫描"}, "POST")
    pid = made["project"]["id"]
    second = 70_560_000
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {"op": "asset.register", "asset": {
            "id": "m", "kind": "image", "label": "图板", "reference": "untrusted"}},
    ]
    for index, clip_id in enumerate(("k1", "k2", "k3")):
        commands.append({
            "op": "clip.add",
            "clip": {
                "id": clip_id, "asset_id": "m", "track_id": "v",
                "position_ticks": index * 4 * second, "duration_ticks": 4 * second,
                "keyframes": [
                    {"property": "x", "at_ticks": 0, "value": 0.05 + index / 20},
                    {"property": "opacity", "at_ticks": second, "value": 0.8},
                    {"property": "rotation", "at_ticks": 3 * second, "value": 12.0},
                ],
                "effects": {"blur": 0.04, "sharpen": 0.3},
            },
        })
    # 1.227：把上面那句账还掉——文字层那一片（四颗色块、三个下拉、字号与描边那几格）
    # 只有选中一条**文字**片段才会画出来，以前夹具里没有，所以整片从来没被任何一屏量过。
    commands += [
        {"op": "track.add", "track": {"id": "vt", "kind": "video", "name": "文字"}},
        {"op": "asset.register", "asset": {
            "id": "txt", "kind": "text", "label": "文字", "reference": "generated:text"}},
        {"op": "clip.add", "clip": {
            "id": "t1", "asset_id": "txt", "track_id": "vt",
            "position_ticks": 0, "duration_ticks": 4 * second,
            "text": {
                "body": "第一行标题，字数按人真会打的那一句来", "font_size": 0.06,
                "color": "#F2C66D", "align": "center", "outline_width": 0.04,
                "outline_color": "#101010", "shadow_x": 0.01, "shadow_y": -0.02,
                "shadow_color": "#0B0B0B", "box_color": "#1D2530", "box_opacity": 0.45},
            "effects": {"x": 0, "y": 0.35, "scale": 1, "rotation": 0, "opacity": 1,
                        "gain": 1, "blur": 0, "sharpen": 0, "sharpen_radius": 0.004,
                        "denoise": 0}}},
    ]
    request(
        f"/v1/projects/{pid}/edits",
        token,
        {"request_id": "shape-seed", "expected_revision": made["project"]["revision"],
         "commands": commands},
        "POST",
    )
    # 检查器最挤的那几格不能空着量：遮罩、调色链与转场装满之后，
    # 「22 屏 green」才说的是同一件事。
    # 22 屏 green 说的必须是「装满东西时也 green」，否则这一档只是在量一张白屏。
    dense = [
        {
            "op": "clip.mask",
            "clip_id": "k2",
            "mask": {
                "shape": "rectangle",
                "center_x": 0.5,
                "center_y": 0.45,
                "width": 0.42,
                "height": 0.5,
                "rotation": 12.5,
                "feather": 0.08,
            },
        },
        # 1.229：再叠的那几块自己有五个数与羽化/反转——这一格里一张卡两列，装满两块才量得出
        # 「输入框被挤成两行」或「勾选框压到下一列」这类只有画出来才看得见的形状。
        {
            "op": "clip.mask_stack",
            "clip_id": "k2",
            "masks": [
                {"shape": "rectangle", "center_x": 0.62, "center_y": 0.5, "width": 0.3,
                 "height": 0.34, "rotation": 0, "feather": 0.05, "inverted": False,
                 "keys": [
                     {"at_ticks": 0, "center_x": 0.62, "center_y": 0.5, "width": 0.3,
                      "height": 0.34, "rotation": 0, "interpolation": "linear"},
                     {"at_ticks": 2 * second, "center_x": 0.55, "center_y": 0.5,
                      "width": 0.3, "height": 0.34, "rotation": 6, "interpolation": "ease"},
                     {"at_ticks": 4 * second, "center_x": 0.48, "center_y": 0.5,
                      "width": 0.3, "height": 0.34, "rotation": 0, "interpolation": "hold"},
                 ]},
                {"shape": "ellipse", "center_x": 0.38, "center_y": 0.5, "width": 0.22,
                 "height": 0.28, "rotation": 18, "feather": 0.02, "inverted": True},
            ],
        },
        {
            "op": "clip.grade",
            "clip_id": "k2",
            "grade": [
                {"kind": "levels", "channel": "rgb", "black": 0.02, "white": 0.98, "gamma": 1.12},
                {"kind": "matrix", "coefficients": [0.95, 0.03, 0.02, 0.04, 0.94, 0.02,
                                                     0.04, 0.03, 0.93]},
            ],
        },
        # 1.218 量到的那两处重叠就是这一条命令引出来的：转场牌子压在片段左端的针上。
        # 留着它，「22 屏 green」才包括「转场上场时也不许有一枚针点不到」。
        # 0.5 秒 = 15 格，是默认 30 fps 那一格的整数倍（引擎按格夹转场）。
        {
            "op": "transition.set",
            "clip_id": "k2",
            "from_clip_id": "k1",
            "kind": "dissolve",
            "duration_ticks": 35_280_000,
        },
    ]
    request(
        f"/v1/projects/{pid}/edits",
        token,
        {"request_id": "shape-dense", "expected_revision": made["project"]["revision"] + 1,
         "commands": dense},
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


def sweep(pid: str, folder: Path, panel: str, extras: tuple[str, ...] = (),
          drag: bool = False, text_clip: str = "", boxkey: str = "",
          gradecard: str = "", dup_extra: bool = False,
          drag_extra: bool = False, insert_extra: bool = False,
          alt_dup: bool = False, mask_bezier: bool = False) -> list[dict]:
    out = folder / f"ui_shape_sweep-{panel}.json"
    shots = os.environ.get("AGENTCUT_SHAPE_SHOTS", "")
    node = subprocess.run(
        [
            "node", str(SWEEP),
            "--renderer", str(RENDERER),
            "--engine", f"http://127.0.0.1:{PORT}",
            "--token", TOKEN,
            "--project", pid,
            "--clip", "k2",
            "--panel", panel,
            "--open-details", "1",
            "--sizes", ",".join(SIZES),
            "--out", str(out),
            *(sum([["--extra", label] for label in extras], [])),
            *(["--drag-splitter", "1"] if drag else []),
            *(["--text-clip", text_clip] if text_clip else []),
            *(["--boxkey", boxkey] if boxkey else []),
            *(["--gradecard", gradecard] if gradecard else []),
            *(["--dup-extra", "1"] if dup_extra else []),
            *(["--drag-extra", "1"] if drag_extra else []),
            *(["--insert-extra", "1"] if insert_extra else []),
            *(["--alt-dup", "1"] if alt_dup else []),
            *(["--mask-bezier", "1"] if mask_bezier else []),
            *(["--shots", shots] if shots else []),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        cwd=str(ROOT),
    )
    # 上一轮被超时打断时留下的 msedge 会占住 profile 与端口——那是量具的抖动，不是界面的缺陷。
    if node.returncode != 0 or not out.is_file():
        time.sleep(6)
        node = subprocess.run(node.args, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=900, cwd=str(ROOT))
        if node.returncode != 0 or not out.is_file():
            fail("扫描没跑完（重试一次还是）：" + (node.stderr or node.stdout)[-400:])
    return json.loads(out.read_text(encoding="utf-8"))


def main() -> None:
    global PORT
    if not (RENDERER / "index.html").is_file():
        fail(f"{RENDERER}/index.html 不在——先跑 `cd desktop && npm run build:renderer`")
    if not SWEEP.is_file() or not PROBE.is_file():
        fail("量具缺件：" + ", ".join(str(p) for p in (SWEEP, PROBE) if not p.is_file()))
    if not EDGE.is_file():
        fail(f"没有 Edge（{EDGE}）——量具需要它，设 AGENTCUT_EDGE 指到实际那支")
    if not FFMPEG.is_file():
        fail(f"没有随包 FFmpeg：{FFMPEG}")
    if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
        fail("没有 node 可执行")
    css_floor = minimum_font_step()
    PORT = free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-shape-") as raw:
        folder = Path(raw)
        engine = run_engine(folder)
        try:
            pid = seed_project(TOKEN)
            rows = [
                row
                for panel in PANELS
                for row in sweep(pid, folder, panel,
                                 OVERLAYS if panel == "inspect" else (),
                                 drag=panel == "inspect",
                                 text_clip="t1" if panel == "inspect" else "",
                                 boxkey="#stack-0-center_x" if panel == "inspect" else "",
                                 gradecard="2" if panel == "inspect" else "",
                                 dup_extra=panel == "inspect",
                                 drag_extra=panel == "inspect",
                                 insert_extra=panel == "inspect",
                                 alt_dup=panel == "inspect",
                                 mask_bezier=panel == "inspect")
            ]
        finally:
            engine.terminate()
            try:
                engine.wait(timeout=30)
            except subprocess.TimeoutExpired:
                engine.kill()

    screens = [row for row in rows if row.get("data")]
    # 「至少该有 N 屏」那一判数的是**总数**，多出来的余量会把「某一屏根本没量到」吃掉：
    # 1.223 补进「画面中编辑」时，那一屏两档都没量到，总数仍然够，门禁照样绿。
    # 现在改成**每一行都必须量到**——量不到就点名，不许被别的屏抵掉。
    missed = [
        {"screen": row.get("screen"), "panel": row.get("panel"),
         "size": row.get("size"), "error": row.get("error")}
        for row in rows
        if not row.get("data")
    ]
    if missed:
        fail(f"{len(missed)} 行没量到（每一屏都得量到，不许用别的屏抵数）："
             + json.dumps(missed, ensure_ascii=False)[:600])
    # 每一档窗口 26 屏：启动 + 展开 + 其余页签 + 浮层那几颗 + 文字层 + 拖高 + 框点 + 调色节点
    # + 复制 / 画面拖 / 打新框点 / Alt 拖副本 / 框点带贝塞尔。这个数只是地板——真正的判据是上面那条
    # 「每一行都必须量到」；加一屏时一起加（按量到的数加，不按猜的加）。
    needed = 26 * len(SIZES)
    if len(screens) < needed:
        fail(f"只量到 {len(screens)} 屏（至少该有 {needed} 屏）")

    # 「点了才画」那一档要证明**真的画了**：1.224 补「画面中编辑」时那一屏量到 92 个字节点，
    # 与「剪辑」那一屏的 93 只差一个——只看几何，说不清遮罩参考线到底画没画。
    blank = [row for row in screens
             if row.get("screen") in PAINTED
             and not (row.get("markers") or {}).get(PAINTED[row["screen"]], 0)]
    if blank:
        fail("这些浮层屏没画出该画的东西：" + json.dumps(
            [{"screen": row["screen"], "size": row["size"], "markers": row.get("markers"),
              "state": row.get("state")} for row in blank],
            ensure_ascii=False)[:900] + "（那颗按钮点开了别的东西，或者根本没生效）")

    noisy = sorted({f"{row['screen']}@{row['size']}="
                    f"{(row.get('markers') or {}).get(QUIET[row['screen']])}"
                    for row in screens
                    if row.get("screen") in QUIET
                    and (row.get("markers") or {}).get(QUIET[row["screen"]], 0)})
    if noisy:
        fail("这些屏上挂着不该挂的那一行：" + json.dumps(noisy, ensure_ascii=False)
             + "（「窗口太矮」说的是这一屏要了一个装不下的数——重置之后还挂着，"
               "就是应用自己要的那一个数，不是用户拖出来的）")

    problems: list[str] = []
    named = 0
    cuts = 0
    piles = 0
    print(f"{'那一屏':<26}{'视口':>12}{'字节点':>8}{'最小字':>8}{'圆角档':>18}"
          f"{'尖角':>6}{'被切':>6}{'点不到':>8}{'叠行':>6}{'字压字':>8}")
    for row in screens:
        data = row["data"]
        label = f"{row['panel'][:3]}/{row['screen']}@{row['size'].split('x')[1]}"
        steps = "/".join(str(step) for step in data["radius_steps"])[:16]
        print(
            f"{label:<22}{data['viewport']['width']}x{data['viewport']['height']:>7}"
            f"{data['text_nodes']:>8}{str(data['min_font']):>8}{steps:>18}"
            f"{len(data['sharp_corners']):>6}{data['clipped_count']:>6}"
            f"{data['unreachable_count']:>8}{data['hint_stack_count']:>6}"
            f"{data['text_overlap_count']:>8}"
        )
        if not data["painted_tags"] or data["min_font"] is None:
            problems.append(f"{label}: 一个字都没画")
            continue
        if data["min_font"] < FONT_FLOOR:
            problems.append(
                f"{label}: 最小 {data['min_font']}px 低于地板 {FONT_FLOOR}px"
                f"（样式表那一档最小是 {css_floor}px）：{data['smallest_sample']}"
            )
        if data["sharp_corners"]:
            problems.append(f"{label}: 出现 1~5px 的尖角 {data['sharp_corners']}")
        if data["clipped_count"]:
            problems.append(f"{label}: 有 {data['clipped_count']} 处文字被切 "
                            + json.dumps(data["clipped"][:6], ensure_ascii=False)[:300])
        piles += int(data["text_overlap_count"])
        if data["text_overlaps"]:
            problems.append(f"{label}: 有 {data['text_overlap_count']} 处字压字 "
                            + json.dumps(data["text_overlaps"][:6], ensure_ascii=False)[:900])
        if data["unreachable_count"]:
            problems.append(f"{label}: 有 {data['unreachable_count']} 个控件点不到 "
                            + json.dumps(data["unreachable"][:8], ensure_ascii=False)[:900])
            problems.append(f"{label}: 版面 "
                            + json.dumps(data.get("layout_boxes", {}), ensure_ascii=False)[:600])
            problems.append(f"{label}: 第一处点到的祖先链 "
                            + json.dumps(data["unreachable"][0], ensure_ascii=False)[:1200])
        # 下拉那一行被切：`<select>` 不会自己报被切（它的 overflow 算出来是 visible），
        # 1.220 是靠眼睛看发布包才发现「Rec.709（电视与浏览器…」被竖切在括号前。
        # 现在这一判常驻：切了就必须把整句挂在同一颗控件的悬停上，否则算缺陷。
        for cut_row in data.get("truncated_selects", []):
            cuts += 1
            if not cut_row.get("has_title"):
                problems.append(
                    f"{label}: 下拉那一行被切又没有悬停可看整句 "
                    + json.dumps(cut_row, ensure_ascii=False)[:220]
                )
        if row["screen"] == "剪辑":
            # 夹具里那条带转场的片段，头一枚针让给了牌子那一格。少画的那一枚**必须有名字**：
            # 「静悄悄少画一枚针」和「留一枚点不到的针」是同一类缺陷，所以这一判也进门禁。
            marks = [str(chip.get("text")) for chip in data.get("chips", [])]
            if data.get("chip_count", 0) < 1 or not any(mark.startswith("+") for mark in marks):
                problems.append(
                    f"{label}: 画不下的针没有名字（+N 牌子看见的：{marks or '一枚都没有'}）"
                )
            else:
                named += 1
    if css_floor < FONT_FLOOR:
        problems.append(f"styles.css 里最小那一档字号 {css_floor}px 低于地板 {FONT_FLOOR}px")
    if problems:
        print("SUMMARY red")
        for line in problems:
            print(" - " + line)
        raise SystemExit(1)
    print(
        f"SUMMARY green screens={len(screens)} 地板={css_floor}px "
        f"叠行合计={sum(row['data']['hint_stack_count'] for row in screens)} "
        f"遮罩后={sum(row['data'].get('behind_scrim_count', 0) for row in screens)} "
        f"缺口有名={named} 下拉被切={cuts} 字压字合计={piles}"
    )


PORT = 0

if __name__ == "__main__":
    main()
