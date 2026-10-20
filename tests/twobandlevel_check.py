"""两端同色：调色链在预览里画出来的级，与导出那一片里的级，逐列比数值（1.223 第 2 项）。

1.222 那条 `twoband_check.py` 只比**亮暗**——它要回答的是「洞在不在同一处」，二值化刚好
够用。这一档问的是另一个问题：**同一个颜色在两端是不是同一个级**。
现有的那些表级比对（`gradelevels_check`、`autograde_check` 把 256 个输入级逐点比过公式）
证的是「两端拿到同一张表」；表一样不等于画出来一样——SVG 滤镜在浏览器里是 8 位缓冲、
`color-interpolation-filters` 声明、合成时的色彩管理，FFmpeg 那一路是 `lutrgb` /
`colorchannelmixer` 在信号域上直接算。这些都在表比对的下游，只有拍到像素才看得见。

量法：

* 板子是一张 512×288 的 PNG：上面 2/3 是一条 256 级的横向灰度斜坡（每级 2 px），
  下面 1/3 是六块饱和色（红绿蓝青品黄）——斜坡量每通道自己的函数，色块量跨通道
  （矩阵把红挪到哪儿，灰斜坡是看不出来的）。
* 调色链装三节：一张 1D 查找表（逐通道）、一个 3×3 通道混合、一档色阶——
  三种编译形状（表、矩阵、再一张表）都在同一条链上，顺序也有意义。
* 导出那一片走 **DPX 序列**（`gbrap10le`：RGB 三平面、10 位、没有色度二次采样），
  两端都用随包 ffmpeg 解成 rgb24。走 DPX 而不是 H.264 的理由与 `gradelevels_check` 一样：
  4:2:0 与 x264 自己就会把平滑渐变挪动几级，那测的是编码器不是调色链。
* 预览那一格由 `scripts/two_end_shot.cjs` 经 CDP 截图（与 1.222 同一条腿）。

判据：斜坡每一级与六块色上的每一个通道，两端之差的绝对值必须 ≤ 4 级。这一档的容差就是
**量出来的最坏值**（一条陡的三节链在最暗的那一截里，预览比导出低 3~4 级；两档容器量到的
最坏值一样，说明那不是某一档容器的锅）。另外还有一把**第三尺**：把清单里那串编译好的阶段
在浮点上自己走一遍，导出必须贴着它（≤2 级，即 8 位量化该有的量）——这一条只对 RGB 那一档
容器判，YUV 那一档自己还要过两次矩阵与一次 4:2:0，实测它比 RGB 那一档多带 2~4 级。
同时必须**看得见**这条链真的动了画面（斜坡中段的输出与输入差出至少 20 级，
六块饱和色每一块都被挪开至少 5 级），不然「两端都没画」也能过关。
突变那一手（把浏览器那一侧的矩阵阶段摘掉）必须让这一档红。

跑法：空闲机器单跑 `uv run python tests/twobandlevel_check.py`。
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
TOKEN = "twobandlevel" + "c" * 40
PORT = 0
SECOND = 70_560_000
WIDTH, HEIGHT = 512, 288
RAMP_ROWS = 192
BLOCKS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 255, 255), (255, 0, 255), (255, 255, 0))
# 斜坡取样避开两端各 8 级：那两头被黑场/白场夹住，比不出插值。
SAMPLE_FROM, SAMPLE_TO = 8, 248
RAMP_Y = 0.4
BLOCK_Y = 0.85
TOLERANCE = 4
# 导出对「它自己拿到的那张表」该差多少：8 位量化每段最多挪 1 级，两段串起来给 2 级。
AUTHORITY = 2
MOVEMENT = 20
# 两档容器各比一遍：DPX 是 RGB 三平面 10 位、没有色度二次采样，H.264 是交付那一档。
# 只比一档的话，「两端差几级」到底是调色链的事还是那档容器的事，分不开。
# 第二枚布尔说的是这一档**能不能**拿去比「导出 vs 它拿到的那张表」：YUV 那一档自己就要过
# 两次矩阵与一次 4:2:0，实测它比 RGB 那一档多带 2~4 级，那不该记在调色链头上。
PRESETS = (("dpx-sequence", True), ("h264-source-quality", False))
# 平色那一趟取的几级：最暗的几级 + 中段 + 接近顶。斜坡量到差的那几处都在这里。
FLAT_LEVELS = (8, 20, 34, 64, 128, 200, 250)
# 2 级是实测：平色输入下浏览器那张滤镜对表最差 2 级（34 与 128 那两格）。
FLAT_TOLERANCE = 2


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def require_prerequisites() -> None:
    if not (RENDERER / "index.html").exists():
        fail(f"渲染层没构建：{RENDERER}（cd desktop && npm run build:renderer）")
    if not SHOT.exists():
        fail(f"照片腿不在：{SHOT}")
    if not EDGE.exists():
        fail(f"没有可用的浏览器：{EDGE}（设 AGENCUT_EDGE）")
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
        tail = (proc.stderr or b"").decode("utf-8", errors="replace")[-500:]
        raise AssertionError(f"{Path(str(argv[0])).name} 退出 {proc.returncode}: {tail}")
    return proc.stdout


def plate_bytes() -> bytes:
    """512×288 的 rgb24：上面一条 256 级斜坡，下面六块饱和色。纯 Python 拼字节，不拉依赖。"""
    row_ramp = bytearray(WIDTH * 3)
    for x in range(WIDTH):
        value = min(255, x // 2)
        row_ramp[x * 3: x * 3 + 3] = bytes((value, value, value))
    row_blocks = bytearray(WIDTH * 3)
    for x in range(WIDTH):
        value = BLOCKS[min(len(BLOCKS) - 1, x * len(BLOCKS) // WIDTH)]
        row_blocks[x * 3: x * 3 + 3] = bytes(value)
    return bytes(row_ramp * RAMP_ROWS + row_blocks * (HEIGHT - RAMP_ROWS))


def write_plate(path: Path) -> None:
    proc = subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{WIDTH}x{HEIGHT}", "-i", "pipe:0", str(path)],
        input=plate_bytes(), capture_output=True, creationflags=0x08000000,
    )
    if proc.returncode != 0:
        fail("画板落不成 PNG：" + proc.stderr.decode("utf-8", errors="replace")[-300:])


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
    argv = [str(FFMPEG), "-v", "error"]
    if path.suffix in (".mov", ".mp4", ".webm", ".mxf"):
        argv += ["-i", str(path), "-vf", "select=eq(n\\,0)", "-frames:v", "1"]
    else:
        argv += ["-i", str(path)]
    argv += ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    raw = run(argv)
    want = width * height * 3
    assert len(raw) >= want, f"{path.name} 只解出 {len(raw)} 字节，要 {want}"
    return width, height, raw[:want]


def at(rgb: bytes, width: int, height: int, x: float, y: float) -> tuple[int, int, int]:
    offset = (int(y * height) * width + int(x * width)) * 3
    return (rgb[offset], rgb[offset + 1], rgb[offset + 2])


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
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env=env, cwd=str(ROOT),
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


def export_frame(pid: str, revision: int, preset_id: str, folder: Path) -> Path:
    presets = {item["id"]: item for item in request("/v1/render-presets")["presets"]}
    assert preset_id in presets, f"预设表里没有 {preset_id}：{sorted(presets)}"
    container = presets[preset_id]["container"]
    answer = request(
        f"/v1/projects/{pid}/renders",
        {"request_id": f"2bl-{preset_id}", "expected_revision": revision,
         "preset_id": preset_id, "filename": f"levels.{container}"},
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
    if out.is_dir():
        frames = sorted(out.glob(f"*.{container}"))
    elif out.exists():
        frames = [out]
    else:
        frames = sorted(out.parent.glob(f"*.{container}"))
    assert frames, f"导出说成功了，可 {out} 旁边找不到 {container}"
    return frames[0]


def preview_shot(pid: str, folder: Path, stages) -> Path:
    """拍预览那一腿，并且当场对一遍「画出来的段数 == 清单交的段数」。"""
    png = folder / "preview-levels.png"
    argv = [
        "node", str(SHOT), "--renderer", str(RENDERER),
        "--engine", f"http://127.0.0.1:{PORT}", "--token", TOKEN,
        "--project", pid, "--clip", "c", "--out", str(png), "--layers", "0",
        "--tables", str(sum(1 for stage in stages if stage["type"] == "lut")),
        "--matrices", str(sum(1 for stage in stages if stage["type"] == "matrix")),
        "--table-values", "256",
        "--edge", str(EDGE),
    ]
    retries = 0
    while True:
        answer = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", cwd=str(ROOT), creationflags=0x08000000,
                                timeout=300)
        if answer.returncode == 0:
            break
        if retries >= 1:
            raise AssertionError(f"照片腿退出 {answer.returncode}（重试过一次还是这样）: "
                                 f"{answer.stderr[-600:]}")
        retries += 1
        time.sleep(2.0)
    assert png.exists(), "照片腿说写完了但文件不在"
    return png


def reference(stages, rgb):
    """把清单里那串编译好的阶段在浮点上照序走一遍——第三把尺，用来说明「哪一端是异类」。

    两端互相一致不等于两端都对；只有第三把尺能分清是预览偏了还是导出偏了。
    """
    values = [channel / 255 for channel in rgb]
    for stage in stages:
        if stage["type"] == "lut":
            tables = (stage["r"], stage["g"], stage["b"])
            values = [
                tables[index][min(255, max(0, round(value * 255)))]
                for index, value in enumerate(values)
            ]
        elif stage["type"] == "matrix":
            m = stage["m"]
            values = [
                max(0.0, min(1.0, m[row * 3] * values[0] + m[row * 3 + 1] * values[1]
                             + m[row * 3 + 2] * values[2]))
                for row in range(3)
            ]
        else:  # pragma: no cover - 清单里出现没见过的阶段就点名，不许悄悄算过去
            raise AssertionError(f"这一档不认识清单里的阶段类型 {stage['type']}")
    return tuple(round(value * 255) for value in values)


def compare(export: tuple[int, int, bytes], preview: tuple[int, int, bytes], stages) -> dict:
    """逐取样点比三个通道的级差；返回最差的那一处、超容差的清单，以及第三把尺的两条读数。"""
    worst = {"delta": -1, "where": "", "export": (), "preview": ()}
    over = []
    blocks = []
    ref_gap = {"export": {"delta": -1, "where": ""}, "preview": {"delta": -1, "where": ""}}
    for level in range(SAMPLE_FROM, SAMPLE_TO + 1):
        x = (level + 0.5) / 256
        e = at(export[2], export[0], export[1], x, RAMP_Y)
        p = at(preview[2], preview[0], preview[1], x, RAMP_Y)
        want = reference(stages, (level, level, level))
        for channel in range(3):
            for side, value in (("export", e[channel]), ("preview", p[channel])):
                gap = abs(value - want[channel])
                if gap > ref_gap[side]["delta"]:
                    ref_gap[side] = {"delta": gap,
                                     "where": f"斜坡 {level} 级 {'rgb'[channel]}"}
        for channel, name in enumerate("rgb"):
            delta = abs(e[channel] - p[channel])
            if delta > worst["delta"]:
                worst = {"delta": delta, "where": f"斜坡 {level} 级 {name}",
                         "export": e, "preview": p}
            if delta > TOLERANCE:
                over.append((f"斜坡 {level} {name}", e[channel], p[channel], delta))
    for index, plate in enumerate(BLOCKS):
        x = (index + 0.5) / len(BLOCKS)
        e = at(export[2], export[0], export[1], x, BLOCK_Y)
        p = at(preview[2], preview[0], preview[1], x, BLOCK_Y)
        want = reference(stages, plate)
        for channel in range(3):
            delta = abs(e[channel] - p[channel])
            if delta > worst["delta"]:
                worst = {"delta": delta, "where": f"色块 {index} 通道 {channel}",
                         "export": e, "preview": p}
            if delta > TOLERANCE:
                over.append((f"色块 {index} 通道 {channel}", e[channel], p[channel], delta))
            for side, value in (("export", e[channel]), ("preview", p[channel])):
                gap = abs(value - want[channel])
                if gap > ref_gap[side]["delta"]:
                    ref_gap[side] = {"delta": gap,
                                     "where": f"色块 {index} 通道 {'rgb'[channel]}"}
        # 板子上写的是饱和色，链子必须真的把它挪开（跨通道那一半只有色块看得见）。
        # 这里**不拿**板子的值去比导出——那是链子之前的东西，比了就是把产品当恒等映射。
        blocks.append((index, plate, e, p, max(abs(e[c] - plate[c]) for c in range(3))))
    return {"worst": worst, "over": over, "blocks": blocks, "ref_gap": ref_gap}


def strip_shot(pid: str, folder: Path, levels) -> tuple[list[tuple[int, int, int]], dict]:
    """把产品自己那张滤镜贴到一排平色上拍回来——这一趟里没有任何缩放。"""
    png = folder / "strip.png"
    argv = [
        "node", str(SHOT), "--renderer", str(RENDERER),
        "--engine", f"http://127.0.0.1:{PORT}", "--token", TOKEN,
        "--project", pid, "--clip", "c", "--out", str(png), "--layers", "0",
        "--strip", ",".join(str(v) for v in levels), "--edge", str(EDGE),
    ]
    answer = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", cwd=str(ROOT), creationflags=0x08000000,
                            timeout=300)
    assert answer.returncode == 0, f"平色腿退出 {answer.returncode}: {answer.stderr[-500:]}"
    info = json.loads(answer.stdout.strip().splitlines()[-1])
    width, height, raw = first_frame(png)
    assert width == 40 * len(levels) and height == 40, (width, height)
    cells = [at(raw, width, height, (index + 0.5) / len(levels), 0.5)
             for index in range(len(levels))]
    return cells, info


def main() -> None:
    require_prerequisites()
    global PORT
    PORT = free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-twobandlevel-") as temp:
        folder = Path(temp)
        plate = folder / "ramp.png"
        write_plate(plate)
        process = engine(folder)
        try:
            made = request(
                "/v1/projects",
                {"request_id": "2bl-new", "name": "两端同色",
                 "settings": {"width": WIDTH, "height": HEIGHT,
                              "frame_rate": {"numerator": 30, "denominator": 1}}},
                "POST",
            )
            pid = made["project"]["id"]
            probe = request("/v1/media/import", {"path": str(plate)}, "POST")
            bent = [
                [round(min(1.0, (level / 255) ** 0.85 * 0.94 + 0.03), 6) for level in range(256)],
                [round((level / 255) ** 1.15, 6) for level in range(256)],
                [round(min(1.0, (level / 255) ** 0.95), 6) for level in range(256)],
            ]
            identity = [round(level / 255, 6) for level in range(256)]
            assert bent[0] != identity and bent[1] != identity, (
                "查找表写成了恒等，这一档就没有东西在比"
            )
            request(
                f"/v1/projects/{pid}/edits",
                {"request_id": "2bl-seed", "expected_revision": made["project"]["revision"],
                 "commands": [
                     {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
                     {"op": "asset.import", "asset_id": "w", "label": "斜坡",
                      "probe_id": probe["id"], "verified": probe["verified"]},
                     {"op": "clip.add", "clip": {"id": "c", "asset_id": "w", "track_id": "v",
                                                 "position_ticks": 0,
                                                 "duration_ticks": 2 * SECOND}},
                     {"op": "clip.grade", "clip_id": "c", "grade": [
                         {"kind": "lut", "size": 256, "channels": bent},
                         {"kind": "matrix", "coefficients": [
                             0.95, 0.03, 0.02, 0.04, 0.94, 0.02, 0.04, 0.03, 0.93]},
                         {"kind": "levels", "channel": "rgb", "black": 0.02,
                          "white": 0.98, "gamma": 1.12},
                     ]},
                 ]},
                "POST",
            )
            revision = request(f"/v1/projects/{pid}")["revision"]
            manifest = request(f"/v1/projects/{pid}/preview-manifest?revision={revision}")
            entry = manifest["clips"]["c"]
            assert entry.get("grade"), f"清单里没有调色阶段：{sorted(entry)}"
            kinds = [stage["type"] for stage in entry["grade"]["stages"]]
            assert "lut" in kinds and "matrix" in kinds, kinds
            stages = entry["grade"]["stages"]

            png = preview_shot(pid, folder, stages)
            preview_frame = first_frame(png)
            readings = {}
            for preset, exact in PRESETS:
                path = export_frame(pid, revision, preset, folder)
                frame = first_frame(path)
                readings[preset] = (exact, path, frame, compare(frame, preview_frame, stages))

            # 这条链必须真的把画面挪开了：斜坡中段那一级的**导出**值离输入至少 MOVEMENT 级，
            # 否则「两端一致地什么都没画」也能满足上面的比对。
            level = 128
            _exact, _dpx_path, dpx_frame, answer = readings[PRESETS[0][0]]
            drawn = at(dpx_frame[2], dpx_frame[0], dpx_frame[1], (level + 0.5) / 256, RAMP_Y)
            assert max(abs(value - level) for value in drawn) >= MOVEMENT, (
                f"128 级经这条链之后导出仍是 {drawn}——链没生效，上面那个比对在量空气"
            )
            problems = []
            for preset, (_exact, _path, _frame, each) in readings.items():
                least = min(block[4] for block in each["blocks"])
                if least < 5:
                    problems.append(
                        f"{preset}：六块饱和色里被链子挪开得最少的一块只动了 {least} 级——"
                        f"跨通道的那一半没被量到"
                    )
                if each["over"]:
                    problems.append(
                        f"{preset}：两端有 {len(each['over'])} 个取样点差过 {TOLERANCE} 级，"
                        f"前八个 {each['over'][:8]}；最差 {each['worst']}"
                    )
            # 第三把尺：清单里那串阶段自己走一遍。导出必须贴着它——那是「导出画的就是
            # 它拿到的那张表」这句话的像素版本。预览这一端只报数不判：浏览器对
            # `feComponentTransfer` 的表插值语义与 8 位中间缓冲还没量清，
            # 拿一个没量清的模型去判它，红与绿都不说明问题。
            for preset, (exact, _path, _frame, each) in readings.items():
                gap = each["ref_gap"]["export"]["delta"]
                if exact and gap > AUTHORITY:
                    problems.append(
                        f"{preset}：导出离自己拿到的那张表有 {gap} 级"
                        f"（在 {each['ref_gap']['export']['where']}），"
                        f"超过 8 位量化该有的 {AUTHORITY} 级"
                    )
            # 平色那一趟：把缩放摘掉，只问「浏览器这张滤镜把 8 变成几」。斜坡那一趟里
            # 预览比导出低 3~4 级，到底是滤镜的锅还是「512 宽的两级台阶被画到 414 宽」的锅，
            # 由这一趟分开——它没有任何重采样。
            cells, strip_info = strip_shot(pid, folder, FLAT_LEVELS)
            primitives = strip_info["strip"]["primitives"]
            assert "feComponentTransfer" in primitives and "feColorMatrix" in primitives, primitives
            flat = []
            for level, cell in zip(FLAT_LEVELS, cells):
                want = reference(stages, (level, level, level))
                flat.append((level, cell, want, max(abs(cell[c] - want[c]) for c in range(3))))
            worst_flat = max(flat, key=lambda row: row[3])
            if worst_flat[3] > FLAT_TOLERANCE:
                problems.append(
                    "平色那一趟：滤镜把 " + " / ".join(f"{r[0]}→{r[1]}" for r in flat) +
                    f" 对表最差 {worst_flat[3]} 级，超过 {FLAT_TOLERANCE} 级"
                )
            assert not problems, "\n".join(problems)
            points = (SAMPLE_TO - SAMPLE_FROM + 1) * 3 + 54
            report = "；".join(
                f"{preset} 两端最差 {each['worst']['delta']} 级 @ {each['worst']['where']}，"
                f"导出对表最差 {each['ref_gap']['export']['delta']} 级，"
                f"预览对表最差 {each['ref_gap']['preview']['delta']} 级 @ "
                + each["ref_gap"]["preview"]["where"]
                for preset, (_exact, _path, _frame, each) in readings.items()
            )
            print(
                "PASS: 斜坡 " + f"{SAMPLE_FROM}~{SAMPLE_TO} 级与六块饱和色上，预览与导出的"
                f"每一通道都只差 ≤{TOLERANCE} 级（每档容器 {points} 个通道值）；{report}；"
                f"平色那一趟（没有任何缩放）滤镜对表最差 {worst_flat[3]} 级："
                f"{worst_flat[0]} 级画成 {worst_flat[1]}，表算的是 {worst_flat[2]}；"
                f"链子编译出的阶段是 {kinds}，平色那趟走的是 {primitives}"
            )
        finally:
            process.kill()


if __name__ == "__main__":
    main()
