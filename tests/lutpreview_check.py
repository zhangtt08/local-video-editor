"""1.234：立方表在预览里画出来的那一格，与成片那一帧是同一幅画（逐点比数值）。

为什么要有这一档：1.103 起 3D LUT 只在导出里生效，界面写的是「预览不生效、导出生效」；
1.234 把预览那一头接到一块 WebGL2 画布上（同一张表、同一档四面体插值）。壳检只能钉住
「算式在那儿」，钉不出「两端画出来的是不是一个数」——这一档把两端都落成像素：

* 导出那一帧：真跑一次 DPX 序列渲染任务（10 位、无二次采样），随包 ffmpeg 解成 rgb24；
* 预览那一格：`scripts/two_end_shot.cjs --webgl` 把渲染层伺服起来、深链进同一个工程，
  证明画布在、内部尺寸>0、源被藏起来，再截 `.masked-picture` 那一块；
* 比的是**数值**：12 块平色板各取中心一小片的均值，逐通道比两端差多少级。

三件事缺一不可：

① 对照那一趟（没有立方表）两端就对得上——量具本身没有系统性偏差；
② 挂上立方表之后两端仍然对得上——预览真的画了同一张表，不是「两边都不画」；
③ 成片里那些板子**真的换了颜色**（与对照那一趟的成片比），而且预览也跟着换——
   只有 ② 的话，两端一致地什么都没画也能过关。

跑法：空闲机器单跑 `uv run python tests/lutpreview_check.py`。缺渲染层、缺 node、缺 Edge、
缺随包 ffmpeg 一律点名，不许静悄悄跳过。
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
TOKEN = "lutpreviewcheck" + "b" * 36
SECOND = 70_560_000
FRAME = SECOND // 30
WIDTH, HEIGHT = 320, 180
CUBE_SIZE = 17
# 12 块板子：四列三行，每块 64×44，取中心那一小片。颜色挑在三通道都张开的位置上。
COLOURS = [
    (32, 48, 210), (210, 40, 36), (36, 190, 64), (128, 128, 128),
    (12, 12, 12), (246, 246, 246), (250, 130, 8), (10, 140, 250),
    (140, 20, 160), (200, 200, 40), (70, 160, 215), (165, 70, 120),
]
MASK = {"shape": "rectangle", "center_x": 0.5, "center_y": 0.5,
        "width": 1.0, "height": 1.0, "feather": 0.0}
TOLERANCE = 8  # 量出来的：对照那一趟与立方那一趟各报一次，见末尾的 print

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
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:600]
        raise AssertionError(f"{method} {path} -> {error.code}: {detail}") from None


def run(argv: list) -> bytes:
    proc = subprocess.run(argv, capture_output=True, creationflags=0x08000000)
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", errors="replace")[-400:]
        raise AssertionError(f"{argv[0]} … 退出 {proc.returncode}: {tail}")
    return proc.stdout


def patch_boxes() -> list[tuple[int, int, int, int]]:
    """四列三行：每格 80×60，板子居中 64×44，四周留 6/8 px 的黑。"""
    boxes = []
    for row in range(3):
        for column in range(4):
            x = column * 80 + 8
            y = row * 60 + 8
            boxes.append((x, y, 64, 44))
    return boxes


def write_plate(path: Path) -> None:
    """P6 的 PPM 直接写出来再让 ffmpeg 转 PNG——颜色一阶都不漂，避免「两块板自己先差几级」。"""
    pixels = bytearray(WIDTH * HEIGHT * 3)
    for (x, y, w, h), colour in zip(patch_boxes(), COLOURS):
        for row in range(y, y + h):
            start = (row * WIDTH + x) * 3
            pixels[start:start + w * 3] = bytes(colour) * w
    raw = path.with_suffix(".ppm")
    raw.write_bytes(f"P6\n{WIDTH} {HEIGHT}\n255\n".encode() + bytes(pixels))
    run([str(FFMPEG), "-v", "error", "-y", "-i", str(raw), "-frames:v", "1", str(path)])


def cube_text(size: int = CUBE_SIZE) -> str:
    """一张**跨通道、非线性**的表：红取蓝的幂、绿自己、蓝取红的幂。

    跨通道这一半让通道顺序写错时差出上百级；非线性这一半让「只取最近格点」与四面体
    插值在格子中间差出几个级——两端用的是同一张表，所以两端该一起落在插值那一侧。
    """
    lines = [f"TITLE \"preview-{size}\"", f"LUT_3D_SIZE {size}"]
    span = size - 1
    for b in range(size):
        for g in range(size):
            for r in range(size):
                out_r = (b / span) ** 1.1
                out_g = (g / span) ** 0.8
                out_b = (r / span) ** 1.3
                lines.append(f"{out_r:.6f} {out_g:.6f} {out_b:.6f}")
    return "\n".join(lines) + "\n"


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


def patch_centres() -> list[tuple[float, float]]:
    return [((x + w / 2) / WIDTH, (y + h / 2) / HEIGHT) for x, y, w, h in patch_boxes()]


def patch_mean(rgb: bytes, width: int, height: int, index: int) -> tuple[float, float, float]:
    """一块板子中心 ±5% 见方那一片的均值（归一化坐标，两端尺寸不同也能比）。"""
    cx, cy = patch_centres()[index]
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


def compare(left, right, label: str) -> tuple[list, float]:
    """left/right 是 (width, height, rgb) 三元组；逐板逐通道算出最大差。"""
    worst = 0.0
    rows = []
    for index in range(len(COLOURS)):
        a = patch_mean(left[2], left[0], left[1], index)
        b = patch_mean(right[2], right[0], right[1], index)
        diff = max(abs(one - other) for one, other in zip(a, b))
        worst = max(worst, diff)
        rows.append((index, tuple(round(v, 1) for v in a), tuple(round(v, 1) for v in b),
                     round(diff, 1)))
    return rows, worst


def change(left, right) -> tuple[float, int]:
    """两趟之间有多少块板子真的换了颜色：返回最大差与「差≥20 级」的块数。"""
    worst = 0.0
    changed = 0
    for index in range(len(COLOURS)):
        a = patch_mean(left[2], left[0], left[1], index)
        b = patch_mean(right[2], right[0], right[1], index)
        diff = max(abs(one - other) for one, other in zip(a, b))
        worst = max(worst, diff)
        changed += 1 if diff >= 20 else 0
    return worst, changed


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


def export_frame(pid: str, revision: int, key: str) -> Path:
    presets = {item["id"]: item for item in request("/v1/render-presets")["presets"]}
    preset = presets["dpx-sequence"]
    answer = request(
        f"/v1/projects/{pid}/renders",
        {"request_id": f"lp-{key}", "expected_revision": revision,
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
    # 序列那条 `output_path` 交的是带 `%06d` 的模板，文件在它旁边那个目录里。
    folder = out if out.is_dir() else out.parent
    frames = sorted(folder.glob(f"*.{preset['container']}"))
    assert frames, f"任务说成功了但帧不在：{out}（{folder} 里没有 .{preset['container']}）"
    return frames[0]


def preview_shot(pid: str, folder: Path, key: str, webgl: bool,
                 play_ms: int = 0) -> tuple[Path, dict]:
    png = folder / f"preview-{key}.png"
    argv = [
        "node", str(SHOT),
        "--renderer", str(RENDERER),
        "--engine", f"http://127.0.0.1:{PORT}",
        "--token", TOKEN,
        "--project", pid,
        "--clip", "c",
        "--out", str(png),
        "--layers", "1",
        "--edge", str(EDGE),
    ]
    if webgl:
        argv.append("--webgl")
    if play_ms:
        argv += ["--play", str(play_ms)]
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
                f"照片腿退出 {answer.returncode}（重试过一次还是这样）: {answer.stderr[-600:]}"
            )
        retries += 1
        time.sleep(2.0)
    info = json.loads(answer.stdout.strip().splitlines()[-1])
    assert Path(info["out"]).exists(), "照片腿说写完了但文件不在"
    if retries:
        print(f"   照片腿重试了 {retries} 次才拍到「{key}」那一格")
    return png, info


def video_suite(folder: Path) -> dict:
    """播放中的那一帧也要在画布上：静止图那一趟证明不了「每一帧都重画」。

    每趟都从 tick 0 起播，播 0.7 秒与 1.5 秒各读一次画布中心：两次都对得上（不是黑的），
    而且**不是同一格**——画布若停在第一帧，这两个数会一模一样。
    """
    source = folder / "moving.mp4"
    run([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=s={WIDTH}x{HEIGHT}:r=30:d=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)])
    made = request(
        "/v1/projects",
        {"request_id": "lp-video", "name": "立方表预览·视频",
         "settings": {"width": WIDTH, "height": HEIGHT,
                      "frame_rate": {"numerator": 30, "denominator": 1}}},
        "POST",
    )
    pid = made["project"]["id"]
    probe = request("/v1/media/import", {"path": str(source)}, "POST")
    parsed = request("/v1/lut/parse", {"content": cube_text()}, "POST")
    node = {key: value for key, value in parsed.items() if key != "kind"}
    request(
        f"/v1/projects/{pid}/edits",
        {"request_id": "lp-video-seed", "expected_revision": made["project"]["revision"],
         "commands": [
             {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
             {"op": "asset.import", "asset_id": "w", "label": "动图",
              "probe_id": probe["id"], "verified": probe["verified"]},
             {"op": "clip.add", "clip": {
                 "id": "c", "asset_id": "w", "track_id": "v",
                 "position_ticks": 0, "duration_ticks": 2 * SECOND}},
             {"op": "clip.mask", "clip_id": "c", "mask": MASK},
             {"op": "clip.color", "clip_id": "c", "color": {
                 "exposure": 0.3, "contrast": 1.05, "saturation": 1.1,
                 "grade": [{"kind": "lut3d", **node}]}},
         ]},
        "POST",
    )
    early = preview_shot(pid, folder, "video-early", webgl=True, play_ms=700)[1]
    late = preview_shot(pid, folder, "video-late", webgl=True, play_ms=1500)[1]
    first, second = early.get("play") or {}, late.get("play") or {}
    for label, answer in (("0.7 秒", first), ("1.5 秒", second)):
        assert answer.get("canvas") and answer.get("width", 0) > 2, (label, answer)
        assert max(answer["pixel"][:3]) > 20, (label, "播放中画布是黑的", answer)
    shift = max(abs(a - b) for a, b in zip(first["pixel"][:3], second["pixel"][:3]))
    same_frame = (
        first.get("checksum") is not None
        and first.get("checksum") == second.get("checksum")
    )
    assert not same_frame, ("画布停在第一帧没跟着播", first, second)
    return {"early": first, "late": second, "shift": shift}


def main() -> None:
    require_prerequisites()
    global PORT
    PORT = free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-lutpreview-") as temp:
        folder = Path(temp)
        plate = folder / "plate.png"
        write_plate(plate)
        process = engine(folder)
        try:
            made = request(
                "/v1/projects",
                {"request_id": "lp-new", "name": "立方表预览",
                 "settings": {"width": WIDTH, "height": HEIGHT,
                              "frame_rate": {"numerator": 30, "denominator": 1}}},
                "POST",
            )
            pid = made["project"]["id"]
            probe = request("/v1/media/import", {"path": str(plate)}, "POST")
            request(
                f"/v1/projects/{pid}/edits",
                {"request_id": "lp-seed", "expected_revision": made["project"]["revision"],
                 "commands": [
                     {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
                     {"op": "asset.import", "asset_id": "w", "label": "色板",
                      "probe_id": probe["id"], "verified": probe["verified"]},
                     {"op": "clip.add", "clip": {
                         "id": "c", "asset_id": "w", "track_id": "v",
                         "position_ticks": 0, "duration_ticks": FRAME}},
                     {"op": "clip.mask", "clip_id": "c", "mask": MASK},
                 ]},
                "POST",
            )
            revision = request(f"/v1/projects/{pid}")["revision"]

            # ① 对照那一趟：没有立方表，两端本该就对得上——量具自己先过一遍。
            control_png, control_info = preview_shot(pid, folder, "control", webgl=False)
            control_mp4 = export_frame(pid, revision, "control")
            control_rows, control_worst = compare(
                first_frame(control_mp4), first_frame(control_png), "对照"
            )
            assert control_info.get("webgl") is None, (
                f"没有立方表却出现了画布：{control_info.get('webgl')}"
            )

            # ② 挂上立方表（外加三个基础调色数，画布要从 `color_basics` 读同一组）。
            parsed = request("/v1/lut/parse", {"content": cube_text()}, "POST")
            node = {key: value for key, value in parsed.items() if key != "kind"}
            graded = request(
                f"/v1/projects/{pid}/edits",
                {"request_id": "lp-grade", "expected_revision": revision,
                 "commands": [{"op": "clip.color", "clip_id": "c", "color": {
                     "exposure": 0.3, "contrast": 1.05, "saturation": 1.1,
                     "grade": [{"kind": "lut3d", **node}]}}]},
                "POST",
            )["project"]["revision"]
            graded_png, graded_info = preview_shot(pid, folder, "graded", webgl=True)
            graded_mp4 = export_frame(pid, graded, "graded")
            print("   画布：" + json.dumps(graded_info.get("webgl"), ensure_ascii=False))
            if graded_info.get("logs"):
                print("   页面控制台：" + " / ".join(graded_info["logs"]))

            control_frame = first_frame(control_mp4)
            graded_frame = first_frame(graded_mp4)
            preview_control = first_frame(control_png)
            preview_graded = first_frame(graded_png)

            rows, worst = compare(graded_frame, preview_graded, "立方表")
            export_shift, export_changed = change(control_frame, graded_frame)
            preview_shift, preview_changed = change(preview_control, preview_graded)
            for row in rows:
                print(f"   板 {row[0]:2d}：成片 {row[1]} 预览 {row[2]} 差 {row[3]} 级")
            print(
                f"   对照两端最差 {control_worst:.1f} 级；立方这一趟两端最差 {worst:.1f} 级；"
                f"成片里 {export_changed}/12 块换了（最大 {export_shift:.1f}），"
                f"预览里 {preview_changed}/12 块换了（最大 {preview_shift:.1f}）"
            )

            assert control_worst <= TOLERANCE, (
                f"对照那一趟两端就差了 {control_worst:.1f} 级——量具有系统性偏差，先查量具"
            )
            assert worst <= TOLERANCE, (
                f"立方这一趟两端最差 {worst:.1f} 级，超过容差 {TOLERANCE}；"
                f"前几块 {rows[:4]}"
            )
            assert export_changed >= 10 and export_shift >= 40, (
                f"成片里只有 {export_changed}/12 块换了颜色（最大 {export_shift:.1f}）——"
                "这一趟没证明表被用上"
            )
            assert preview_changed >= 10 and preview_shift >= 40, (
                f"预览里只有 {preview_changed}/12 块换了颜色（最大 {preview_shift:.1f}）——"
                "预览根本没用那张表"
            )
            moving = video_suite(folder)
            info = graded_info.get("webgl") or {}
            print(
                "PASS: 立方表两端同一幅画——预览画布 "
                f"{info.get('width')}×{info.get('height')}（源已藏起），"
                f"12 块板两端最差 {worst:.1f} 级（容差 {TOLERANCE}），"
                f"成片与预览各换了 {export_changed}/12 与 {preview_changed}/12 块；"
                f"播放中画布 0.7s 与 1.5s 两整帧不同（校验 {moving['early'].get('checksum')} / "
                f"{moving['late'].get('checksum')}，中心像素差 {moving['shift']} 级）"
            )
        finally:
            process.kill()


if __name__ == "__main__":
    main()
