"""1.259：主遮罩的软边也能打点——不转的那一只盒也按窗换图，两端读同一张阶梯。

以前只有转起来的盒才需要那张窗表（`mask-image` 不吃图层旋转，1.164 量的）。软边看着像另一个
极端——它是一条 `clip((1-x)/feather,0,1)`，导出能逐帧现算。但它烘在引擎那张板里：预览画的是
SVG 的渐变停靠点，浏览器没有「把这个数逐帧改掉」的那只手。于是一端连续、一端静止就是这个项目
拒绝的那条缝。做法与角度同族：`mask_feather` 进那条窗表的第四个位置，一窗一步、两端同表。

判据：
① 那一只盒**没有转**，窗表却非空，且每一窗的软边等于曲线在**该窗起点**那一格的采样（1.182 的
   规矩）；清单里相邻两窗烘出来的图不一样——「换了窗」是看得见的，不是只多了一个字段。
② 编译串里那条软边走的是 `if(lt(T,` 的阶梯，且带着 `max(…,1e-4)` 那个下限；一条软边都不许
   落到 `ld(20)` 那一对格子上（那是再叠块跟随主遮罩中心时用的，撞上了就是一起读同一个缓存）。
③ 没有软边曲线的那一段：编译串与静止那一路逐字节相同，窗表为空。
④ 路径遮罩带软边曲线按名字拒（那句同时点名角度与软边），值越界在契约层就拒，两者都不涨 revision。
⑤ 两端像素：同一段 0.05→0.35 的斜坡，早一格与晚一格在三个探针上预览与导出逐点同判，
   而 0.85 那一格由亮转暗——「软边在动」是量出来的；对照那一趟（不带曲线）两个时刻都亮。

跑法：空闲机器单跑 `uv run python tests/maskfeather_check.py`（照片腿要随包那支 Edge）。
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import typing
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.animation import (  # noqa: E402
    MASK_EXTRA_FIELDS,
    mask_box_schedule,
    preview_manifest,
    rotated_box,
)
from agentcut.contracts import (  # noqa: E402
    MASK_BOX_VALUES,
    MASK_FIELDS,
    MASK_ROTATION_SCHEDULE_MAX,
    PROPERTY_LIMITS,
    SCHEMA_VERSION,
    Keyframe,
    Project,
    ShapeMask,
    VerifiedMedia,
    capabilities,
)
from agentcut.contracts import (  # noqa: E402
    TIMEBASE as T,
)
from agentcut.masks import alpha_expression  # noqa: E402
from agentcut.render import compile_render_plan  # noqa: E402

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
TOKEN = "maskfeathercheck" + "b" * 34
FRAME = T // 30
WIDTH, HEIGHT = 320, 180
PORT = 0

# 一只 0.8×0.8 的正盒（0.1..0.9），从不转；软边从 0.05 走到 0.35。
MAIN = {"shape": "rectangle", "center_x": 0.5, "center_y": 0.5, "width": 0.8,
        "height": 0.8, "feather": 0.0}
FIRST, LAST = 0.05, 0.35
# 斜坡从边往里量，所以这三格各有各的身份：0.85 在两条窗之间由亮转暗，0.80 一直在斜坡内侧，
# 0.95 一直在盒外（它替「什么都没画」那一类把关）。
PROBES = (0.85, 0.80, 0.95)


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
        detail = error.read().decode("utf-8", errors="replace")[:700]
        raise AssertionError(f"{method} {path} -> {error.code}: {detail}") from None


def refused(path: str, payload, method="POST") -> dict:
    """要的就是那一个 4xx：把状态码与正文一起交回来，别让它伪装成一次成功。"""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return {"status": response.status, "body": response.read().decode("utf-8")}
    except urllib.error.HTTPError as error:
        return {"status": error.code,
                "body": error.read().decode("utf-8", errors="replace")}


def run(argv: list) -> bytes:
    proc = subprocess.run(argv, capture_output=True, creationflags=0x08000000)
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", errors="replace")[-400:]
        raise AssertionError(f"{argv[0]} … 退出 {proc.returncode}: {tail}")
    return proc.stdout


def stream_size(path: Path) -> tuple[int, int]:
    answer = json.loads(
        run([str(FFPROBE), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)])
        .decode("utf-8", errors="replace")
    )
    stream = answer["streams"][0]
    return int(stream["width"]), int(stream["height"])


def frame_at(path: Path) -> tuple[int, int, bytes]:
    width, height = stream_size(path)
    raw = run([str(FFMPEG), "-v", "error", "-i", str(path), "-frames:v", "1",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    want = width * height * 3
    assert len(raw) >= want, f"{path.name} 只解出 {len(raw)} 字节，要 {want}"
    return width, height, raw[:want]


def grey_at(image, x: float, y: float) -> int:
    width, height, rgb = image
    offset = (int(y * height) * width + int(x * width)) * 3
    return round((rgb[offset] + rgb[offset + 1] + rgb[offset + 2]) / 3)


def bright(image, x: float, y: float) -> bool:
    return grey_at(image, x, y) > 128


def engine(data_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["AGENTCUT_TOKEN"] = TOKEN
    process = subprocess.Popen(
        [sys.executable, "-m", "agentcut", "api", "--port", str(PORT), "--json",
         "--data-dir", str(data_dir), "--cache-dir", str(data_dir / "cache"),
         "--output-dir", str(data_dir / "out"), "--media-root", str(data_dir),
         "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE)],
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


def feather_at(seconds: float) -> float:
    """量具自己那条直线斜坡：0 秒 FIRST，2 秒 LAST。"""
    return FIRST + (LAST - FIRST) * (seconds / 2.0)


def ramp_alpha(u: float, v: float, feather: float) -> bool:
    """按定义算这一格亮不亮——不 import 产品那条式子。"""
    x = abs((u - 0.5) * 2 / MAIN["width"])
    y = abs((v - 0.5) * 2 / MAIN["height"])
    if feather <= 0:
        return x <= 1 and y <= 1
    value = min(1.0, max(0.0, (1 - x) / feather)) * min(1.0, max(0.0, (1 - y) / feather))
    return value > 0.502


def clip_payload(**changes) -> dict:
    clip = {
        "id": "c", "asset_id": "a", "track_id": "v",
        "position_ticks": 0, "duration_ticks": 2 * T,
        "mask": dict(MAIN),
    }
    clip.update(changes)
    return clip


def feather_keys() -> list[dict]:
    return [
        {"property": "mask_feather", "at_ticks": 0, "value": FIRST, "interpolation": "linear"},
        {"property": "mask_feather", "at_ticks": 2 * T, "value": LAST, "interpolation": "linear"},
    ]


def picture(clip: dict) -> Project:
    return Project.model_validate(
        {
            "id": "p", "name": "maskfeather",
            "settings": {"width": WIDTH, "height": HEIGHT},
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {"a": {"id": "a", "kind": "video", "label": "a", "reference": "r",
                             "duration_ticks": 2 * T}},
            "clips": {"c": clip},
        }
    )


def with_media(project: Project, path: Path) -> Project:
    project.assets["a"].verified = VerifiedMedia.model_validate(
        {
            "probe_id": "a", "path": str(path), "kind": "video", "label": "white",
            "size_bytes": path.stat().st_size,
            "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "duration_ticks": 2 * T, "width": WIDTH, "height": HEIGHT, "has_audio": False,
        }
    )
    return project


def contract_suite() -> None:
    caps = capabilities()
    assert SCHEMA_VERSION == 30, SCHEMA_VERSION
    assert caps["project_schema_version"] == 30
    assert MASK_FIELDS["mask_feather"] == "feather", MASK_FIELDS
    # 再叠那一块的窗表按位置说话：这一列属性名与那一列字段名必须一格对一格。
    assert list(MASK_BOX_VALUES) == list(MASK_FIELDS), (MASK_BOX_VALUES, MASK_FIELDS)
    assert len(MASK_BOX_VALUES) == len(MASK_EXTRA_FIELDS)
    assert MASK_BOX_VALUES[-1] == "mask_feather" and MASK_EXTRA_FIELDS[-1] == "feather", (
        MASK_BOX_VALUES, MASK_EXTRA_FIELDS)
    assert PROPERTY_LIMITS["mask_feather"] == (0.0, 1.0), PROPERTY_LIMITS["mask_feather"]
    union = typing.get_args(Keyframe.model_fields["property"].annotation)
    mask_literal = [row for row in union if "mask_x" in typing.get_args(row)]
    assert len(mask_literal) == 1, union
    assert typing.get_args(mask_literal[0]) == tuple(MASK_FIELDS), (
        "能打点的遮罩属性与那张名字表不是同一串", typing.get_args(mask_literal[0]))
    assert caps["features"]["mask_feather_curves"] is True
    assert caps["features"]["mask_rotation_curves"] is True
    # 静止那一路一个字不许改：0.2 还是一个 0.2，不是 `max(0.2,1e-4)`，也不是窗表那条式子。
    still = ShapeMask(**{**MAIN, "feather": 0.2})
    literal = alpha_expression(still)
    assert "/0.2," in literal and "max(" not in literal, literal
    assert literal == alpha_expression(still, {"mask_feather": "0.200000000"}), (
        "窗表里那个数没有化成同一个字面量")
    print("   契约：属性名、那条带、开关与 schema 都在；静止那一路仍是 /0.2,")


def schedule_suite() -> None:
    clip = picture(clip_payload(keyframes=feather_keys())).clips["c"]
    assert not rotated_box(clip), "这一只盒从头到尾没转——窗表非空才是这一档要说的事"
    windows = mask_box_schedule(clip, FRAME, MASK_ROTATION_SCHEDULE_MAX)
    assert len(windows) >= 2, windows
    assert len(windows) <= MASK_ROTATION_SCHEDULE_MAX, len(windows)
    for window in windows:
        start = window["from_ticks"] / T
        assert len(window["value"]) == 4, window
        assert abs(window["value"][3] - feather_at(start)) < 1e-6, (
            "这一窗的软边不是它自己起点那一格", window["from_ticks"], window["value"][3],
            feather_at(start))
        assert window["value"][0] == 0.0, "角度不该跟着动"
    # 曲线之外：一格都不许多出来。两端都只认这张表，所以这里数得清。
    assert windows[-1]["to_ticks"] == 2 * T, windows[-1]
    plain = picture(clip_payload()).clips["c"]
    assert mask_box_schedule(plain, FRAME, MASK_ROTATION_SCHEDULE_MAX) == [], (
        "没有软边曲线的片段也被拖进了换图那一路")
    # 中心在动而软边不动：仍不走窗表（与 1.258 之前逐字节相同那一句是同一件事）。
    moved = picture(clip_payload(keyframes=[
        {"property": "mask_x", "at_ticks": 0, "value": 0.4, "interpolation": "linear"},
        {"property": "mask_x", "at_ticks": 2 * T, "value": 0.6, "interpolation": "linear"},
    ])).clips["c"]
    assert mask_box_schedule(moved, FRAME, MASK_ROTATION_SCHEDULE_MAX) == []
    print(f"   阶梯：不转的盒也切出 {len(windows)} 窗，"
          f"每窗的软边等于它自己起点那一格；没有曲线的两趟仍是空的")


def manifest_suite(folder: Path) -> None:
    keyed = with_media(picture(clip_payload(keyframes=feather_keys())), folder / "white.png")
    row = preview_manifest(keyed)["clips"]["c"]
    windows = row["mask_rotation_windows"]
    schedule = mask_box_schedule(keyed.clips["c"], FRAME, MASK_ROTATION_SCHEDULE_MAX)
    assert windows and len(windows) == len(schedule)
    assert [w["from_ticks"] for w in windows] == [w["from_ticks"] for w in schedule]
    for window in windows:
        assert set(window) >= {"from_ticks", "to_ticks", "angle", "width", "height",
                               "feather", "image"}, sorted(window)
    assert windows[0]["image"] != windows[-1]["image"], (
        "相邻两窗烘出来是同一张图——换窗这件事看不见")
    assert row["mask_unit"] == windows[0]["image"], "单位图不是第一窗那一张"
    curve = row["mask_curves"]["mask_feather"]
    assert len(curve) == len(windows), (len(curve), len(windows))
    for point, window in zip(curve, windows):
        assert abs(point["value"] - window["feather"]) < 1e-9, (point, window)
        assert abs(point["offset"] - window["from_ticks"] / (2 * T)) < 1e-9
        assert point["easing"] == "steps(1, end)", point
    graph = "\n".join(compile_render_plan(keyed, "h264-source-quality").filters)
    assert "max(if(lt(T," in graph, "那条软边没有走阶梯，或者没有那个非零下限"
    assert "ld(20)" not in graph and "st(20," not in graph, (
        "软边落进了再叠块跟随那一路用的格子——两端会一起读同一份缓存")
    assert "ld(21)" not in graph and "st(21," not in graph
    still = with_media(picture(clip_payload()), folder / "white.png")
    still_graph = "\n".join(compile_render_plan(still, "h264-source-quality").filters)
    assert "max(" not in still_graph and "lte(" in still_graph, still_graph[:300]
    assert preview_manifest(still)["clips"]["c"]["mask_rotation_windows"] is None
    print(f"   清单与图：{len(windows)} 窗、每窗一张自己的图；"
          "编译串走阶梯且不碰那一对跟随用的格子；没有曲线的串仍是 lte 那条边")


def follow_suite(folder: Path) -> None:
    """「跟着一个转了的主遮罩走」那一路吃的是**同一张**窗表，所以它必须受得住四个数。

    1.259 这一轮这里坏过一次：那一路整串解包三个数，窗表多一格就 ValueError → 清单 500 →
    监视器整块黑。逐点的账由 maskfollow_check 量；这一节只管清单还建不建得出来、
    建出来的那些行是不是每一窗各有一张自己的图。
    """
    turned = dict(MAIN)
    turned["rotation"] = 20.0
    clip = clip_payload(
        mask=turned,
        keyframes=[
            {"property": "mask_rotation", "at_ticks": 0, "value": 0.0, "interpolation": "linear"},
            {"property": "mask_rotation", "at_ticks": 2 * T,
             "value": 60.0, "interpolation": "linear"},
        ],
        extra_masks=[{"shape": "ellipse", "center_x": 0.62, "center_y": 0.5,
                      "width": 0.2, "height": 0.4, "feather": 0.0}],
        extra_masks_follow=True,
    )
    keyed = with_media(picture(clip), folder / "white.png")
    row = preview_manifest(keyed)["clips"]["c"]
    windows = row["extra_mask_windows"]
    assert windows and len(windows) == 1, json.dumps(windows, ensure_ascii=False)[:200]
    rows = windows[0]
    assert rows and all(item["follow"] for item in rows), "跟随的那些行没带 follow"
    assert len(rows) >= 2, f"只切出一窗，转起来这件事看不见：{len(rows)}"
    assert rows[0]["image"] != rows[-1]["image"], "相邻两窗烘出来是同一张图"
    for item in rows:
        assert "box" not in item, "跟随那一路不该带自己的盒——那一格是这一块静止的数"
    print(f"   跟随那一路：{len(rows)} 窗、每窗一张自己的图，四个数的窗表解得出来")


def export_frames(pid: str, revision: int, key: str, folder: Path) -> tuple[Path, Path]:
    presets = {item["id"]: item for item in request("/v1/render-presets")["presets"]}
    preset = presets["dpx-sequence"]
    answer = request(
        f"/v1/projects/{pid}/renders",
        {"request_id": f"mf-{key}", "expected_revision": revision,
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
    folder_out = out.parent if not out.is_dir() else out
    frames = sorted(folder_out.glob(f"*.{preset['container']}"))
    assert len(frames) >= 55, f"导出的帧不足：{len(frames)}"
    return frames[6], frames[54]


def preview_shot(pid: str, tick: int, folder: Path, key: str) -> dict:
    png = folder / f"preview-{key}.png"
    argv = ["node", str(SHOT), "--renderer", str(RENDERER),
            "--engine", f"http://127.0.0.1:{PORT}", "--token", TOKEN,
            "--project", pid, "--clip", "c", "--tick", str(tick),
            "--out", str(png), "--layers", "1", "--edge", str(EDGE)]
    retries = 0
    while True:
        answer = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", cwd=str(ROOT), creationflags=0x08000000,
                                timeout=300)
        if answer.returncode == 0:
            break
        if retries >= 1:
            raise AssertionError(
                f"照片腿退出 {answer.returncode}（重试过一次还是这样）: {answer.stderr[-600:]}")
        retries += 1
        time.sleep(2.0)
    info = json.loads(answer.stdout.strip().splitlines()[-1])
    assert Path(info["out"]).exists(), "照片腿说写完了但文件不在"
    return info


def seed(folder: Path, tag: str, keyed: bool) -> str:
    made = request(
        "/v1/projects",
        {"request_id": f"kf-new-{tag}", "name": "主遮罩的软边" + ("（动）" if keyed else "（静）"),
         "settings": {"width": WIDTH, "height": HEIGHT,
                      "frame_rate": {"numerator": 30, "denominator": 1}}},
        "POST",
    )
    pid = made["project"]["id"]
    probe = request("/v1/media/import", {"path": str(folder / "white.png")}, "POST")
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {"op": "asset.import", "asset_id": "w", "label": "白板",
         "probe_id": probe["id"], "verified": probe["verified"]},
        {"op": "clip.add", "clip": {"id": "c", "asset_id": "w", "track_id": "v",
                                    "position_ticks": 0, "duration_ticks": 2 * T}},
        {"op": "clip.mask", "clip_id": "c", "mask": MAIN},
    ]
    if keyed:
        commands += [{"op": "keyframe.set", "clip_id": "c", "keyframe": row}
                     for row in feather_keys()]
    request(f"/v1/projects/{pid}/edits",
            {"request_id": f"kf-seed-{tag}", "expected_revision": made["project"]["revision"],
             "commands": commands},
            "POST")
    return pid


def pixel_suite(folder: Path) -> None:
    keyed = seed(folder, "keyed", True)
    still = seed(folder, "still", False)
    answers = {}
    for pid, tag in ((keyed, "keyed"), (still, "still")):
        revision = request(f"/v1/projects/{pid}")["revision"]
        early_frame, late_frame = export_frames(pid, revision, tag, folder)
        export = {"t0": frame_at(early_frame), "t18": frame_at(late_frame)}
        early_png = preview_shot(pid, 6 * FRAME, folder, f"{tag}-early")
        late_png = preview_shot(pid, 54 * FRAME, folder, f"{tag}-late")
        preview = {"t0": frame_at(Path(early_png["out"])), "t18": frame_at(Path(late_png["out"]))}
        answers[tag] = {"export": export, "preview": preview}
    windows = mask_box_schedule(picture(
        clip_payload(keyframes=feather_keys())).clips["c"], FRAME, MASK_ROTATION_SCHEDULE_MAX)
    executed = {}
    for label, frame in (("t0", 6), ("t18", 54)):
        window = next(w for w in windows if w["from_ticks"] <= frame * FRAME < w["to_ticks"])
        executed[label] = window["value"][3]
    rows = []
    for tag in ("keyed", "still"):
        for label in ("t0", "t18"):
            for probe in PROBES:
                got_export = bright(answers[tag]["export"][label], probe, 0.5)
                got_preview = bright(answers[tag]["preview"][label], probe, 0.5)
                assert got_export == got_preview, (
                    f"{tag} / {label} / x={probe}：预览与导出不是同一个洞",
                    got_preview, got_export)
                if tag == "keyed":
                    want = ramp_alpha(probe, 0.5, executed[label])
                    assert got_export == want, (
                        f"{label} / x={probe}：按定义该{'亮' if want else '暗'}",
                        got_export, executed[label])
                rows.append((tag, label, probe, got_export, got_preview))
    flip = [row for row in rows if row[0] == "keyed" and row[2] == 0.85]
    assert [row[3] for row in flip] == [True, False], (
        "那条斜坡没有真的在动：0.85 这一格两个时刻同判", flip)
    held = [row for row in rows if row[0] == "still" and row[2] == 0.85]
    assert [row[3] for row in held] == [True, True], ("对照那一趟不该动", held)
    print(f"   两端像素：执行的是 {executed['t0']:.3f} → {executed['t18']:.3f} 那两个数；"
          f"{len(rows)} 个点预览与导出逐点同判，0.85 那一格由亮转暗，对照两个时刻都亮")


def refusal_suite(folder: Path) -> None:
    path_mask = {"shape": "path", "center_x": 0.5, "center_y": 0.5, "width": 0.6,
                 "height": 0.6, "feather": 0.0,
                 "vertices": [{"x": x, "y": y, "handle_out": [0, 0], "handle_in": [0, 0]}
                              for x, y in ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8))]}
    pid = seed(folder, "refuse", False)
    revision = request(f"/v1/projects/{pid}")["revision"]
    cases = [
        ("路径遮罩带软边曲线", {"request_id": "kf-r-path", "expected_revision": revision,
                               "commands": [{"op": "clip.mask", "clip_id": "c",
                                             "mask": path_mask},
                                            {"op": "keyframe.set", "clip_id": "c",
                                             "keyframe": {"property": "mask_feather",
                                                          "at_ticks": 0, "value": 0.2,
                                                          "interpolation": "linear"}}]}),
        ("软边值越界", {"request_id": "kf-r-band", "expected_revision": revision,
                        "commands": [{"op": "keyframe.set", "clip_id": "c",
                                      "keyframe": {"property": "mask_feather",
                                                   "at_ticks": 0, "value": 2.0,
                                                   "interpolation": "linear"}}]}),
        ("软边值是负数", {"request_id": "kf-r-neg", "expected_revision": revision,
                          "commands": [{"op": "keyframe.set", "clip_id": "c",
                                        "keyframe": {"property": "mask_feather",
                                                     "at_ticks": 0, "value": -0.1,
                                                     "interpolation": "linear"}}]}),
    ]
    for label, payload in cases:
        answer = refused(f"/v1/projects/{pid}/edits", payload)
        assert answer["status"] == 422, (label, answer["status"], answer["body"][:300])
        assert request(f"/v1/projects/{pid}")["revision"] == revision, (
            f"{label}那一笔被拒了，revision 却涨了")
        if label == "路径遮罩带软边曲线":
            body = answer["body"]
            assert "INVALID_MASK" in body, body[:300]
            assert "遮罩角度" in body and ("软边" in body or "羽化" in body), body[:400]
        if label == "软边值越界":
            body = answer["body"]
            assert "mask_feather" in body and "[0.0, 1.0]" in body, body[:300]
        if label == "软边值是负数":
            assert "mask_feather" in answer["body"], answer["body"][:300]
    dry = refused(
        f"/v1/projects/{pid}/edits",
        {"request_id": "kf-dry", "expected_revision": revision, "dry_run": True,
         "commands": [{"op": "keyframe.set", "clip_id": "c",
                       "keyframe": {"property": "mask_feather", "at_ticks": T,
                                    "value": 0.3, "interpolation": "linear"}}]},
    )
    assert dry["status"] == 200, dry["body"][:300]
    assert request(f"/v1/projects/{pid}")["revision"] == revision, "dry_run 写了库"
    made = refused(
        f"/v1/projects/{pid}/edits",
        {"request_id": "kf-write", "expected_revision": revision,
         "commands": [{"op": "keyframe.set", "clip_id": "c",
                       "keyframe": {"property": "mask_feather", "at_ticks": T,
                                    "value": 0.3, "interpolation": "linear"}}]},
    )
    assert made["status"] == 200, made["body"][:300]
    after = request(f"/v1/projects/{pid}")
    assert after["revision"] == revision + 1, (revision, after["revision"])
    named = [k for k in after["clips"]["c"]["keyframes"] if k["property"] == "mask_feather"]
    assert len(named) == 1, named
    print("   拒绝：路径遮罩点名角度与软边、越界点名收到的数，三条都不写库；"
          "dry_run 不写，提交只涨一格")


def main() -> None:
    require_prerequisites()
    global PORT
    PORT = free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-maskfeather-") as temp:
        folder = Path(temp)
        run([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=white:s={WIDTH}x{HEIGHT}", "-frames:v", "1", str(folder / "white.png")])
        contract_suite()
        schedule_suite()
        manifest_suite(folder)
        follow_suite(folder)
        process = engine(folder)
        try:
            pixel_suite(folder)
            refusal_suite(folder)
        finally:
            process.terminate()
            process.wait(timeout=30)
    print("PASS: 主遮罩的软边成了那条窗表的第四个数——不转的盒也按窗换图，"
          "两端逐点同答；没有它的一段一字未改")


if __name__ == "__main__":
    main()
