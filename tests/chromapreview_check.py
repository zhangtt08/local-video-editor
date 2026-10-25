"""1.277：溢色抑制在预览里画出来的那一格，与成片那一帧是同一幅画（逐点比数值）。

为什么要有这一档：`chroma_check.py` 量的是成片那一路（真导 DPX/EXR 逐点读回），壳检只能钉住
「算式在那儿」，两头都钉不出**预览屏幕上**是不是同一个数。溢色抑制尤其如此——它只动一条平面
的颜色，两端一致地「都不压」也能通过一条「两端相等」的判据。所以这里跑三趟，缺一不可：

① 对照（不挂键）：两端本就相等——量具自己先过一遍，没有系统性偏差；
② 挂键、不压（`spill=0`，就是 1.276 那一格）：两端仍然相等，而且洞那几格读回来是**蓝底**——
   证明这一只手真的在画，不是两端一起什么都没做；
③ 挂键、压一半（`spill=0.5`）：两端相等，且绿那一通道比 ② 明显掉下来（两端都掉）——
   这才说得上「抑制在两端都生效」。

比的是数值：同一批位置在两端各取一小片均值，逐通道算最大差；容差 `TOLERANCE` 取自第一趟实测。

跑法：空闲机器单跑 `uv run python tests/chromapreview_check.py`（要渲染层构建产物、node、Edge、
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

from agentcut.compositing import chroma_row  # noqa: E402
from agentcut.contracts import ChromaKey  # noqa: E402

RENDERER = ROOT / "desktop/dist/renderer"
SHOT = ROOT / "scripts/two_end_shot.cjs"
EDGE = Path(
    os.environ.get(
        "AGENTCUT_EDGE",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    )
)
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TOKEN = "chromapreviewcheck" + "b" * 30
SECOND = 70_560_000
WIDTH, HEIGHT = 320, 180
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
RED = (255, 0, 0)
# 三条靠近键色的带：距离 15 / 23 / 31，默认档（相似度 0.12、柔和 0.05）下是全透 / 斜坡 / 全不透。
NEAR = [(0, 240, 0), (0, 232, 0), (0, 224, 0)]
SPILL = 0.5
BOXES = [
    (24, 24, 64, 64, RED),
    (120, 60, 16, 16, NEAR[0]),
    (150, 60, 16, 16, NEAR[1]),
    (180, 60, 16, 16, NEAR[2]),
]
# 取样点：块中心（归一化，两端尺寸不同也能比）。
# 绿点原来落在画面左上角 (10,10)：1.289 把监视器做成圆角卡片之后，那只角被
# `border-radius` 剪掉，实测弧线从截图 (13,0) 走到 (1,10)（半径约 12 px），而 ±0.02 的取样片
# 正好整个压在切角里——读回来的是卡片底色 (16,16,29) 混进画面，对照那一趟因此报 5.6 级。
# 那是 CSS 装饰，不是色彩管线，所以把点挪进画面内部（离四边都 ≥ 半径 + 取样片半径），
# 容差不动：判据仍然能红，只是不再拿圆角当色偏。
SPOTS = {
    "green": (250.0 / WIDTH, 30.0 / HEIGHT),
    "red": (56.0 / WIDTH, 56.0 / HEIGHT),
    "near15": (128.0 / WIDTH, 68.0 / HEIGHT),
    "near23": (158.0 / WIDTH, 68.0 / HEIGHT),
    "near31": (188.0 / WIDTH, 68.0 / HEIGHT),
}
# 夹具该读回什么：不挂键那一趟就是板上那一格（先让夹具自证，再谈两端的差）。
PLATE = {"green": GREEN, "red": RED, "near15": NEAR[0], "near23": NEAR[1], "near31": NEAR[2]}
TOLERANCE = 4  # 实测：对照那一趟 0.0 级，挂键与压抑制各 1.0 级（都在 near23 那一格）
# 压一半那两格的读数由这里**手算**给出（不从 `chroma_row` 反推）：224×0.5=112；
# near23 权重 (23-17.85)/12.75=0.40392，压后 g=0.40392×116=46.9。
SPILL_HAND = {"near23": 47.0, "near31": 112.0}

PORT = 0


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def require_prerequisites() -> None:
    if not (RENDERER / "index.html").exists():
        fail(f"渲染层没构建：{RENDERER}（cd desktop && npm run build:renderer）")
    if not SHOT.exists():
        fail(f"照片腿不在：{SHOT}")
    if not EDGE.exists():
        fail(f"没有可用的浏览器：{EDGE}（设 AGENTCUT_EDGE）")
    if not FFMPEG.exists() or not FFPROBE.exists():
        fail(f"没有随包 ffmpeg/ffprobe：{FFMPEG} / {FFPROBE}")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def request(path: str, payload=None, method="GET"):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:600]
        raise AssertionError(f"{method} {path} -> {error.code}: {detail}") from None


def run(argv: list) -> bytes:
    proc = subprocess.run(argv, capture_output=True, creationflags=0x08000000)
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", errors="replace")[-500:]
        raise AssertionError(f"{argv[0]} … 退出 {proc.returncode}: {tail}")
    return proc.stdout


def write_plate(path: Path, default: tuple[int, int, int], boxes=()) -> None:
    """P6 的 PPM 直接写出来再让 ffmpeg 转 PNG——颜色一阶都不漂。"""
    full = bytearray(WIDTH * HEIGHT * 3)
    for step in range(WIDTH * HEIGHT):
        full[step * 3:step * 3 + 3] = bytes(default)
    for box in boxes:
        x, y, w, h, colour = box
        for row in range(y, y + h):
            start = (row * WIDTH + x) * 3
            full[start:start + w * 3] = bytes(colour) * w
    raw = path.with_suffix(".ppm")
    raw.write_bytes(f"P6\n{WIDTH} {HEIGHT}\n255\n".encode() + bytes(full))
    run([str(FFMPEG), "-v", "error", "-y", "-i", str(raw), "-frames:v", "1", str(path)])


def stream_size(path: Path) -> tuple[int, int]:
    answer = json.loads(
        run([str(FFPROBE), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)])
        .decode("utf-8", errors="replace")
    )
    stream = answer["streams"][0]
    return int(stream["width"]), int(stream["height"])


def first_frame(path: Path) -> tuple[int, int, bytes]:
    width, height = stream_size(path)
    argv = [str(FFMPEG), "-v", "error", "-i", str(path)]
    argv += ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    raw = run(argv)
    want = width * height * 3
    assert len(raw) >= want, f"{path.name} 只解出 {len(raw)} 字节，要 {want}"
    return width, height, raw[:want]


def spot_mean(
    rgb: bytes, width: int, height: int, cx: float, cy: float
) -> tuple[float, float, float]:
    """取样点中心 ±2% 那一片的均值（归一化坐标，两端尺寸不同也能比）。"""
    total = [0.0, 0.0, 0.0]
    count = 0
    for dy in (-0.02, -0.01, 0.0, 0.01, 0.02):
        for dx in (-0.02, -0.01, 0.0, 0.01, 0.02):
            px = min(width - 1, max(0, int((cx + dx) * width)))
            py = min(height - 1, max(0, int((cy + dy) * height)))
            offset = (py * width + px) * 3
            for channel in range(3):
                total[channel] += rgb[offset + channel]
            count += 1
    return tuple(channel / count for channel in total)  # type: ignore[return-value]


def read_spots(frame) -> dict:
    width, height, rgb = frame
    return {name: spot_mean(rgb, width, height, cx, cy) for name, (cx, cy) in SPOTS.items()}


def worst_delta(left: dict, right: dict) -> tuple[float, str]:
    worst, where = 0.0, ""
    for name in SPOTS:
        for one, other in zip(left[name], right[name]):
            if abs(one - other) > worst:
                worst, where = abs(one - other), name
    return worst, where


def engine(data_dir: Path) -> subprocess.Popen:
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
            return process
    fail("引擎 120 秒内没有报 ready")
    raise SystemExit(1)


def preview_shot(pid: str, folder: Path, key: str, webgl: bool):
    png = folder / f"preview-{key}.png"
    argv = [
        "node", str(SHOT),
        "--renderer", str(RENDERER),
        "--engine", f"http://127.0.0.1:{PORT}",
        "--token", TOKEN,
        "--project", pid,
        "--clip", "top",
        "--out", str(png),
        "--layers", "0",
        "--edge", str(EDGE),
    ]
    if webgl:
        argv.append("--webgl")
    retries = 0
    while True:
        answer = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(ROOT), creationflags=0x08000000, timeout=300,
        )
        if answer.returncode == 0:
            break
        if retries >= 1:
            raise AssertionError(
                f"照片腿退出 {answer.returncode}（重试过一次还是这样）: {answer.stderr[-700:]}"
            )
        retries += 1
        time.sleep(2.0)
    info = json.loads(answer.stdout.strip().splitlines()[-1])
    assert Path(info["out"]).exists(), "照片腿说写完了但文件不在"
    return png, info


def export_frame(pid: str, revision: int, key: str) -> Path:
    presets = {item["id"]: item for item in request("/v1/render-presets")["presets"]}
    preset = presets["dpx-sequence"]
    answer = request(
        f"/v1/projects/{pid}/renders",
        {"request_id": f"cp-{key}", "expected_revision": revision,
         "preset_id": "dpx-sequence", "filename": f"{key}.{preset['container']}"},
        "POST",
    )
    job_id = answer["job"]["id"]
    deadline = time.time() + 600
    job = {}
    while time.time() < deadline:
        job = request(f"/v1/jobs/{job_id}")["job"]
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.4)
    assert job.get("status") == "succeeded", json.dumps(job, ensure_ascii=False)[:500]
    out = Path(job["output_path"])
    if out.exists() and not out.is_dir():
        return out
    folder = out if out.is_dir() else out.parent
    frames = sorted(folder.glob(f"*.{preset['container']}"))
    assert frames, f"任务说成功了但帧不在：{out}（{folder} 里没有 .{preset['container']}）"
    return frames[0]


def set_key(pid: str, revision: int, key: ChromaKey | None, request_id: str) -> int:
    chroma = key.model_dump() if key else None
    answer = request(
        f"/v1/projects/{pid}/edits",
        {
            "request_id": request_id,
            "expected_revision": revision,
            "commands": [{"op": "clip.chroma", "clip_id": "top", "chroma": chroma}],
        },
        "POST",
    )
    return answer["project"]["revision"]


def both_ends(pid: str, folder: Path, revision: int, key: str, webgl: bool):
    """同一版工程：成片那一帧 + 预览那一格，各自读回那五个点。"""
    png, info = preview_shot(pid, folder, key, webgl)
    delivered = read_spots(first_frame(export_frame(pid, revision, key)))
    painted = read_spots(first_frame(png))
    return delivered, painted, info


def report(label: str, delivered: dict, painted: dict) -> float:
    worst, where = worst_delta(delivered, painted)
    for name in SPOTS:
        left = tuple(round(v, 1) for v in delivered[name])
        right = tuple(round(v, 1) for v in painted[name])
        print(f"   {label} {name:7s} 成片 {left} 预览 {right}")
    print(f"   {label} 两端最差 {worst:.1f} 级（{where}）")
    return worst


def main() -> None:
    require_prerequisites()
    global PORT
    PORT = free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-chromapreview-") as raw:
        folder = Path(raw)
        top = folder / "top.png"
        base = folder / "base.png"
        write_plate(top, GREEN, BOXES)
        write_plate(base, BLUE)
        process = engine(folder)
        try:
            made = request(
                "/v1/projects",
                {"request_id": "cp-new", "name": "溢色抑制两端",
                 "settings": {"width": WIDTH, "height": HEIGHT,
                              "frame_rate": {"numerator": 30, "denominator": 1}}},
                "POST",
            )
            pid = made["project"]["id"]
            probed_top = request("/v1/media/import", {"path": str(top)}, "POST")
            probed_base = request("/v1/media/import", {"path": str(base)}, "POST")
            revision = request(
                f"/v1/projects/{pid}/edits",
                {
                    "request_id": "cp-seed",
                    "expected_revision": made["project"]["revision"],
                    "commands": [
                        {"op": "track.add", "track": {"id": "v0", "kind": "video", "name": "底"}},
                        {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "幕"}},
                        {"op": "asset.import", "asset_id": "a0", "label": "蓝底",
                         "probe_id": probed_base["id"], "verified": probed_base["verified"]},
                        {"op": "asset.import", "asset_id": "a1", "label": "绿幕",
                         "probe_id": probed_top["id"], "verified": probed_top["verified"]},
                        {"op": "clip.add", "clip": {
                            "id": "base", "asset_id": "a0", "track_id": "v0",
                            "position_ticks": 0, "duration_ticks": SECOND}},
                        {"op": "clip.add", "clip": {
                            "id": "top", "asset_id": "a1", "track_id": "v1",
                            "position_ticks": 0, "duration_ticks": SECOND}},
                    ],
                },
                "POST",
            )["project"]["revision"]

            # ① 对照：谁都没挂键，两端本该相等——量具自己先过一遍。
            control = both_ends(pid, folder, revision, "control", webgl=False)
            control_worst = report("对照", control[0], control[1])
            assert control[2].get("webgl") is None, f"没挂键也长出了画布：{control[2].get('webgl')}"
            assert control_worst <= TOLERANCE, (
                f"对照那一趟两端就差了 {control_worst:.1f} 级——量具有系统性偏差，先查量具"
            )
            # 夹具自证：不挂键那一趟，两端读回来的就是板上那一格。
            for name, frame in (("成片", control[0]), ("预览", control[1])):
                for label, want in PLATE.items():
                    got = frame[label]
                    delta = max(abs(a - b) for a, b in zip(got, want))
                    assert delta <= TOLERANCE, (name, label, got, want)

            # ② 挂键、不压：这一趟就是 1.276 那一格，两端相等之外还必须真的抠出洞。
            keyed = set_key(pid, revision, ChromaKey(spill=0.0), "cp-key")
            plain = both_ends(pid, folder, keyed, "keyed", webgl=True)
            plain_worst = report("挂键不压", plain[0], plain[1])
            assert plain_worst <= TOLERANCE, f"挂键那一趟两端差 {plain_worst:.1f} 级"
            webgl = plain[2].get("webgl") or {}
            assert webgl.get("width", 0) > 2 and webgl.get("visible"), plain[2].get("webgl")
            assert webgl.get("hidden_source"), "色度键那趟没把源藏起来——屏幕上那块绿是源，不是画布"
            for label in ("green", "near15"):
                for name, frame in (("成片", plain[0]), ("预览", plain[1])):
                    got = frame[label]
                    # 洞那两格两端都必须读出蓝底：不绿、也不黑。
                    assert got[2] > 200 and got[1] < 40, (label, name, got)
            # 主体不能被这一只手带走：红块在对照与挂键两趟里必须是同一格（两端各比一次）。
            for name, frame in (("成片", plain[0]), ("预览", plain[1])):
                subject = control[0 if name == "成片" else 1]["red"]
                assert max(abs(a - b) for a, b in zip(frame["red"], subject)) <= TOLERANCE, (
                    name, frame["red"], subject
                )

            # ③ 压一半：绿那一条通道在两端都必须比 ② 低下去。
            spilled = set_key(pid, keyed, ChromaKey(spill=SPILL), "cp-spill")
            pressed = both_ends(pid, folder, spilled, "spilled", webgl=True)
            pressed_worst = report("挂键压一半", pressed[0], pressed[1])
            assert pressed_worst <= TOLERANCE, f"压了抑制之后两端差 {pressed_worst:.1f} 级"
            row = chroma_row(ChromaKey(spill=SPILL))
            assert row["spill_at"] == 1, row
            for label in ("near23", "near31"):
                for name, before, after in (
                    ("成片", plain[0][label][1], pressed[0][label][1]),
                    ("预览", plain[1][label][1], pressed[1][label][1]),
                ):
                    print(f"   {label} {name}：压前 g={before:.1f} 压后 g={after:.1f}")
                    assert before - after >= 30, (label, name, before, after)
            # 绝对读数也钉住：只比「两端相等」的话，两端一起压错同一个数也能过关。
            for label, hand in SPILL_HAND.items():
                for name, frame in (("成片", pressed[0]), ("预览", pressed[1])):
                    got = frame[label][1]
                    assert abs(got - hand) <= TOLERANCE, (label, name, got, hand)
            # 没压的那两条平面与那一个洞都不该被挪动：压绿不能顺手改红，也不能改 alpha。
            for label, keep in (("red", plain[0]["red"]), ("green", plain[0]["green"])):
                assert max(abs(a - b) for a, b in zip(pressed[0][label], keep)) <= TOLERANCE, label

            print(
                f"PASS: 溢色抑制两端同一幅画——对照 {control_worst:.1f} 级、挂键不压 "
                f"{plain_worst:.1f} 级、压一半 {pressed_worst:.1f} 级（容差 {TOLERANCE}），"
                f"画布 {webgl.get('width')}×{webgl.get('height')} 且源已藏起，"
                f"绿那一通道两端各降 "
                f"{plain[0]['near31'][1] - pressed[0]['near31'][1]:.0f}（成片）与 "
                f"{plain[1]['near31'][1] - pressed[1]['near31'][1]:.0f} 级（预览）"
            )
        finally:
            process.kill()


if __name__ == "__main__":
    main()
