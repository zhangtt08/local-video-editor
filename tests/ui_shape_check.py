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
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def seed_project(token: str) -> str:
    """一条视频轨 + 三段带针的片段 + 一条有中文名的合成——界面得有真东西才量得出形状。"""
    made = request("/v1/projects", token, {"request_id": "shape-new", "name": "形状扫描"}, "POST")
    pid = made["project"]["id"]
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
                "position_ticks": index * 4 * 2_352_000, "duration_ticks": 4 * 2_352_000,
                "keyframes": [
                    {"property": "x", "at_ticks": 0, "value": 0.05 + index / 20},
                    {"property": "opacity", "at_ticks": 2_352_000, "value": 0.8},
                ],
                "effects": {"blur": 0.04, "sharpen": 0.3},
            },
        })
    request(
        f"/v1/projects/{pid}/edits",
        token,
        {"request_id": "shape-seed", "expected_revision": made["project"]["revision"],
         "commands": commands},
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


def sweep(pid: str, folder: Path, panel: str) -> list[dict]:
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
            "--sizes", ",".join(SIZES),
            "--out", str(out),
            *(["--shots", shots] if shots else []),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        cwd=str(ROOT),
    )
    if node.returncode != 0 or not out.is_file():
        fail("扫描没跑完：" + (node.stderr or node.stdout)[-400:])
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
            rows = [row for panel in PANELS for row in sweep(pid, folder, panel)]
        finally:
            engine.terminate()
            try:
                engine.wait(timeout=30)
            except subprocess.TimeoutExpired:
                engine.kill()

    screens = [row for row in rows if row.get("data")]
    if len(screens) < len(PANELS) * len(SIZES):
        fail(f"只量到 {len(screens)} 屏（至少该有 {len(PANELS) * len(SIZES)} 屏）：" + json.dumps(
            [
                {"screen": row.get("screen"), "panel": row.get("panel"),
                 "size": row.get("size"), "error": row.get("error")}
                for row in rows
                if not row.get("data")
            ],
            ensure_ascii=False,
        )[:400])

    problems: list[str] = []
    print(f"{'那一屏':<26}{'视口':>12}{'字节点':>8}{'最小字':>8}{'圆角档':>18}"
          f"{'尖角':>6}{'被切':>6}{'点不到':>8}{'叠行':>6}")
    for row in screens:
        data = row["data"]
        label = f"{row['panel'][:3]}/{row['screen']}@{row['size'].split('x')[1]}"
        steps = "/".join(str(step) for step in data["radius_steps"])[:16]
        print(
            f"{label:<22}{data['viewport']['width']}x{data['viewport']['height']:>7}"
            f"{data['text_nodes']:>8}{str(data['min_font']):>8}{steps:>18}"
            f"{len(data['sharp_corners']):>6}{data['clipped_count']:>6}"
            f"{data['unreachable_count']:>8}{data['hint_stack_count']:>6}"
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
        if data["unreachable_count"]:
            problems.append(f"{label}: 有 {data['unreachable_count']} 个控件点不到 "
                            + json.dumps(data["unreachable"][:8], ensure_ascii=False)[:900])
            problems.append(f"{label}: 版面 "
                            + json.dumps(data.get("layout_boxes", {}), ensure_ascii=False)[:600])
            problems.append(f"{label}: 第一处点到的祖先链 "
                            + json.dumps(data["unreachable"][0], ensure_ascii=False)[:1200])
    if css_floor < FONT_FLOOR:
        problems.append(f"styles.css 里最小那一档字号 {css_floor}px 低于地板 {FONT_FLOOR}px")
    if problems:
        print("SUMMARY red")
        for line in problems:
            print(" - " + line)
        raise SystemExit(1)
    print(
        f"SUMMARY green screens={len(screens)} 地板={css_floor}px "
        f"叠行合计={sum(row['data']['hint_stack_count'] for row in screens)}"
    )


PORT = 0

if __name__ == "__main__":
    main()
