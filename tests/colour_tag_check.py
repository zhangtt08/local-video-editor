"""1.151: a master may declare its colour, but only if the graph really folded it that way.

The trap this gate exists for is specific and measured: `-colorspace bt709` writes the container tag
and changes nothing else. Bundled FFmpeg does the RGB->YUV fold in the *encoder's* swscale context,
which uses BT.601 — the fixture's solid colour lands in the PNG as RGB (126,63,30), and an untagged
h264 delivery of it comes back as YUV (83,104,158), exactly the BT.601 prediction, while BT.709
predicts (80,107,157). So a tag written beside the old graph would be a claim about a picture the
file does not hold, and the container is the only thing a downstream colour pipeline can read.

The switch therefore does two things at once, and this file checks both against the same frame:
* the last stage of the graph becomes planar RGB at the preset's own depth, then
  `zscale=matrix=709:range=tv,format=<preset's pixel format>` — `zscale` has to be *handed* RGB, or
  it answers `code 3074: no path between colorspaces` and the render dies (that is why the video
  suite exists: an image-only fixture stayed green while real footage could not be exported);
* the container gets `-color_primaries/-color_trc/-colorspace`.

The reference numbers are re-derived here from the published coefficients, not imported from the
engine, so a wrong matrix in the code cannot agree with itself. Untagged deliveries must keep the
byte-for-byte argv they had before this field existed, and presets that carry no YUV fold at all
(an EXR/DPX sequence, an audio-only file) are refused by name rather than tagged loosely.
"""

import hashlib
import json
import subprocess
import tempfile
import time
from array import array
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut import gamut
from agentcut.colortags import detect_space
from agentcut.contracts import (
    COLOR_SPACES,
    COLOR_TRANSFER_TAGS,
    COLOUR_TAG_CODES,
    OUTPUT_COLOUR_TAGS,
    TIMEBASE,
    CreateProject,
    EditBatch,
    EditorError,
    RenderRequest,
    VerifiedMedia,
    capabilities,
    colour_tag_presets,
)
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime, request_fingerprint
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan, output_args, render_presets
from agentcut.timeline import apply_commands

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
T = TIMEBASE
WIDTH, HEIGHT = 64, 36
SOURCE_RGB = (128, 64, 32)


def reference_yuv(rgb, kr, kg, kb):
    """BT.601 / BT.709 luma-chroma fold, limited range, from the published coefficients.

    The source RGB is passed in because lavfi's own `color=` lands on YUV before the PNG is
    written: the check measures what the fixture really holds instead of assuming the nominal
    value survived a conversion it does not control.
    """
    r, g, b = (channel / 255.0 for channel in rgb)
    y = kr * r + kg * g + kb * b
    u = 0.5 * (b - y) / (1 - kb)
    v = 0.5 * (r - y) / (1 - kr)
    return tuple(round(value) for value in (16 + 219 * y, 128 + 224 * u, 128 + 224 * v))


BT601 = reference_yuv(SOURCE_RGB, 0.299, 0.587, 0.114)
BT709 = reference_yuv(SOURCE_RGB, 0.2126, 0.7152, 0.0722)


def run(argv, timeout=240, cwd=None):
    proc = subprocess.run(
        [str(x) for x in argv],
        capture_output=True,
        timeout=timeout,
        creationflags=0x08000000,
        cwd=str(cwd) if cwd is not None else None,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")[-500:]
    return proc.stdout


def _await(runtime, job_id: str, seconds: int = 240) -> None:
    """Drain the queue: the receipt assertions are only worth anything once the jobs ran."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        job = runtime._load(job_id)
        if job.status not in ("queued", "running"):
            assert job.status == "succeeded", (job.status, job.error_code, job.message)
            return
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} never left the queue")


def build_project(folder: Path):
    """One solid-RGB image on one video track: the exact pixels the fold has to describe."""
    png = folder / "solid.png"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{SOURCE_RGB[0]:02x}{SOURCE_RGB[1]:02x}{SOURCE_RGB[2]:02x}"
            f":s={WIDTH}x{HEIGHT}",
            "-frames:v",
            "1",
            str(png),
        ]
    )
    media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
    store = ProjectStore(media.db_path, media)
    probe = media.import_file(str(png))
    project = store.create(
        CreateProject(request_id="new", name="tag", settings={"width": WIDTH, "height": HEIGHT})
    ).project
    batch = EditBatch.model_validate(
        {"request_id": "seed", "expected_revision": project.revision, "commands": _commands(probe)}
    )
    return apply_commands(project, batch.commands)


def _commands(probe):
    return [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
        {
            "op": "asset.import",
            "asset_id": "s",
            "label": "s",
            "probe_id": probe.id,
            "verified": probe.verified.model_dump(),
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "c",
                "asset_id": "s",
                "track_id": "v",
                "position_ticks": 0,
                "duration_ticks": T,
            },
        },
    ]


def plan_for(project, tag):
    return compile_render_plan(project, "h264-720p-web", colour_tag=tag, range_ticks=(0, T))


def compile_suite(folder: Path) -> None:
    project = build_project(folder)
    plain = plan_for(project, None)
    tagged = plan_for(project, "bt709")
    plain_argv = " ".join(plain.ffmpeg_argv(str(FFMPEG), "out.mp4"))
    tagged_argv = " ".join(tagged.ffmpeg_argv(str(FFMPEG), "out.mp4"))

    assert "-colorspace" not in plain_argv, plain_argv[-300:]
    assert "-color_primaries" not in plain_argv and "-color_trc" not in plain_argv
    assert "zscale" not in json.dumps(plain.filters), plain.filters
    for flag, value in (
        ("-color_primaries", "bt709"),
        ("-color_trc", "bt709"),
        ("-colorspace", "bt709"),
    ):
        assert f"{flag} {value}" in tagged_argv, (flag, tagged_argv[-400:])
    assert any("zscale=matrix=709:range=tv,format=yuv420p" in line for line in tagged.filters), (
        tagged.filters
    )
    # The dry-run document itself has to carry the claim, the way the matte and the timecode do: a
    # reader must be able to tell "this file will declare BT.709" from the plan, not only from the
    # field they sent in.
    assert plain.summary["colour_tag"] is None, plain.summary
    assert tagged.summary["colour_tag"] == "bt709", tagged.summary
    # The switch only ever adds: everything else about the two plans has to agree.
    assert plain.mode == tagged.mode and plain.duration_ticks == tagged.duration_ticks
    print("PASS compile: untagged argv carries no colour claim; tagged adds the trio + the fold")


def export(folder: Path, project, tag, name) -> Path:
    plan = plan_for(project, tag)
    for file_name, body in plan.text_files.items():
        (folder / file_name).write_text(body, encoding="utf-8")
    out = folder / name
    # 与 jobs.py 同一条约定：旁路文件写在作业目录、FFmpeg 也在作业目录里跑（cwd=work），
    # 所以这里不许换成仓库根——换了就等于测一条应用里不存在的路。
    run(plan.ffmpeg_argv(str(FFMPEG), str(out)), cwd=folder)
    return out


def pixels_suite(folder: Path) -> None:
    project = build_project(folder)
    untagged = export(folder, project, None, "untagged.mp4")
    tagged = export(folder, project, "bt709", "tagged.mp4")

    def planes(path: Path) -> tuple[int, int, int]:
        raw = run(
            [
                FFMPEG,
                "-v",
                "error",
                "-i",
                path,
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "yuv444p",
                "pipe:1",
            ]
        )
        # Plane offsets come from the frame the file really holds: a preset may deliver a
        # different raster than the timeline, and indexing by the project's size would read
        # three luma pixels and call them Y/U/V (which is exactly what it did first).
        stream = frames(path)
        size = int(stream["width"]) * int(stream["height"])
        assert len(raw) >= size * 3, (len(raw), size)
        return raw[0], raw[size], raw[2 * size]

    def frames(path: Path) -> dict:
        info = json.loads(
            run(
                [
                    FFPROBE,
                    "-v",
                    "error",
                    "-select_streams",
                    "v",
                    "-show_streams",
                    "-print_format",
                    "json",
                    path,
                ]
            ).decode()
        )
        return info["streams"][0]

    def tags(path: Path) -> dict:
        info = json.loads(
            run(
                [
                    FFPROBE,
                    "-v",
                    "error",
                    "-select_streams",
                    "v",
                    "-show_streams",
                    "-print_format",
                    "json",
                    path,
                ]
            ).decode()
        )
        return {k: v for k, v in info["streams"][0].items() if k.startswith("color")}

    # What the fixture actually holds, measured rather than assumed.
    solid = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            folder / "solid.png",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    rgb = tuple(solid[:3])
    want601 = reference_yuv(rgb, 0.299, 0.587, 0.114)
    want709 = reference_yuv(rgb, 0.2126, 0.7152, 0.0722)
    assert BT601 != BT709, (BT601, BT709)
    before, after = planes(untagged), planes(tagged)

    def close(got, want):
        return all(abs(g - w) <= 1 for g, w in zip(got, want))

    assert close(before, want601), (before, want601)
    assert close(after, want709), (after, want709)
    assert not close(after, want601), (after, want601)
    untagged_tags, tagged_tags = tags(untagged), tags(tagged)
    assert "color_space" not in untagged_tags, untagged_tags
    assert tagged_tags["color_space"] == "bt709", tagged_tags
    assert tagged_tags["color_transfer"] == "bt709" and tagged_tags["color_primaries"] == "bt709"
    # Range is the third thing a master claims. Measured the hard way first: leaving `zscale`'s
    # range at "input" carried the RGB source's full range through and the file came back
    # `yuvj420p` + `color_range=pc` around limited-range numbers, which is the same kind of lie
    # as a wrong matrix.
    assert tagged_tags.get("color_range") in (None, "tv"), tagged_tags
    assert str(frames(untagged)["pix_fmt"]) == "yuv420p", frames(untagged)
    assert str(frames(tagged)["pix_fmt"]) == "yuv420p", frames(tagged)
    print(
        f"PASS pixels: source {rgb}: untagged folds {before} (601 predicts {want601}), "
        f"tagged folds {after} (709 predicts {want709}), tags {tagged_tags}"
    )
    return tagged


def roundtrip_suite(folder: Path, master: Path) -> None:
    """The engine must recognise its own master, which is the point of writing the tags at all."""
    media = MediaService(folder / "rt.sqlite3", [folder], folder / "rt-cache", FFMPEG, FFPROBE)
    verified = media.import_file(str(master)).verified
    space, report = detect_space(verified)
    assert space == "rec709", (space, report)
    plain = media.import_file(str(folder / "untagged.mp4")).verified
    assert detect_space(plain)[0] is None, detect_space(plain)[1]
    print("PASS round trip: the tagged master reads back as rec709, the untagged one says nothing")


def probe_stream(path: Path) -> dict:
    raw = run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,pix_fmt,color_space,color_primaries,color_transfer,color_range",
            "-of",
            "json",
            path,
        ]
    )
    streams = json.loads(raw).get("streams", [])
    assert streams, (path, raw)
    return streams[0]


def first_rgb(path: Path) -> tuple[int, int, int]:
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            path,
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    assert len(raw) >= 3, (path, len(raw))
    return tuple(raw[:3])


def video_suite(folder: Path) -> None:
    """A video master, from a source that decodes as YUV — the case every other suite here missed.

    `zscale` can only be told which matrix to fold with when it is handed RGB; fed YUV it answers
    `code 3074: no path between colorspaces` and the whole filter graph dies. The first 1.151 plan
    did exactly that, and stayed green because every fixture in this file was a PNG. What caught it
    was clicking 开始导出 in the packaged app with an mp4 on the timeline.
    """
    clip = folder / "clip.mp4"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{SOURCE_RGB[0]:02x}{SOURCE_RGB[1]:02x}{SOURCE_RGB[2]:02x}"
            f":s={WIDTH}x{HEIGHT}",
            "-t",
            "1",
            "-r",
            "30",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ]
    )
    media = MediaService(folder / "vid.sqlite3", [folder], folder / "vid-cache", FFMPEG, FFPROBE)
    store = ProjectStore(media.db_path, media)
    probe = media.import_file(str(clip))
    project = store.create(
        CreateProject(request_id="vid", name="vid", settings={"width": WIDTH, "height": HEIGHT})
    ).project
    batch = EditBatch.model_validate(
        {"request_id": "seed", "expected_revision": project.revision, "commands": _commands(probe)}
    )
    project = apply_commands(project, batch.commands)

    tagged = export(folder, project, "bt709", "video-tagged.mp4")
    plain = export(folder, project, None, "video-plain.mp4")
    assert tagged.is_file() and tagged.stat().st_size > 1024, tagged
    assert plain.is_file() and plain.stat().st_size > 1024, plain

    stream = probe_stream(tagged)
    claims = {
        key: str(stream[key])
        for key in ("color_space", "color_primaries", "color_transfer", "color_range")
        if key in stream
    }
    assert claims.get("color_space") == "bt709", claims
    assert claims.get("color_primaries") == "bt709", claims
    assert claims.get("color_transfer") == "bt709", claims
    assert claims.get("color_range") == "tv", claims
    assert probe_stream(plain).get("color_space") in (None, "unknown"), probe_stream(plain)

    # The RGB a colour pipeline derives from the master has to be the RGB the source held: the trip
    # through planar RGB and back is coefficients-only, not a re-grade.
    want = first_rgb(clip)
    got = first_rgb(tagged)
    drift = tuple(abs(g - w) for g, w in zip(got, want))
    assert all(step <= 2 for step in drift), (want, got, drift)
    print(
        f"PASS video: an mp4-sourced tagged master really encodes, declares bt709 on all three "
        f"tags, and returns RGB {got} from source {want} (drift {drift})"
    )


# 每一档的折叠系数在这里有**独立出处**，不向引擎要：新加一档却没登记它该折成什么样，本检查当场红。
FOLD_COEFFICIENTS = {
    "bt709": (0.2126, 0.7152, 0.0722),  # ITU-R BT.709-6
    "smpte170m": (0.299, 0.587, 0.114),  # ITU-R BT.601-6（525 行）/ SMPTE 170M
    "bt2020nc": (0.2627, 0.6780, 0.0593),  # ITU-R BT.2020 那份非恒亮度 (NQ)
}

# 基色转换的两端矩阵都抄 ITU-R BT.2020 附件 4 表 5 的公布值（行=输出通道，列=输入通道）。
# 抄在这里而不是问引擎要，是因为 1.153 被自己咬过一次：方向写反的矩阵配一个反着算的往返，
# 检查照样全绿——只有外部出处能把它抓住。公布表只给四位小数，所以比的时候留 5e-4。
PUBLISHED_709_TO_2020 = (
    (0.6274, 0.3293, 0.0433),
    (0.0691, 0.9195, 0.0114),
    (0.0164, 0.0880, 0.8956),
)
IDENTITY_3X3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def invert3(m):
    """3×3 求逆（高斯消元）。反向那张表**由本文件从前向表算出来**，不抄第二份记忆。"""
    a = [list(row) for row in m]
    inv = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        inv[col], inv[pivot] = inv[pivot], inv[col]
        peak = a[col][col]
        for j in range(3):
            a[col][j] /= peak
            inv[col][j] /= peak
        for row in range(3):
            if row == col:
                continue
            factor = a[row][col]
            for j in range(3):
                a[row][j] -= factor * a[col][j]
                inv[row][j] -= factor * inv[col][j]
    return [tuple(row) for row in inv]


PUBLISHED_2020_TO_709 = invert3(PUBLISHED_709_TO_2020)
SHIFT_MATRICES = {
    ("rec709", "rec2020"): PUBLISHED_709_TO_2020,
    ("rec2020", "rec709"): PUBLISHED_2020_TO_709,
    ("rec709", "rec709"): IDENTITY_3X3,
}

BT709_ALPHA, BT709_BETA, BT709_SLOPE = 1.099, 0.099, 4.5
BT709_LIGHT_TURN, BT709_SIGNAL_TURN = 0.018, 0.081  # 拐点两侧各一个数，别互相套


def plane_triple(path: Path) -> tuple[int, int, int]:
    """Y/U/V of the corner pixel, indexed by the raster the file really holds (yuv444p dump)."""
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            path,
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv444p",
            "pipe:1",
        ]
    )
    stream = probe_stream(path)
    size = int(stream["width"]) * int(stream["height"])
    assert len(raw) >= size * 3, (len(raw), size)
    return raw[0], raw[size], raw[2 * size]


def unfold_rgb(
    triple: tuple[int, int, int], coefficients: tuple[float, float, float], scale: int = 1
):
    """按标记把画面解回 RGB：限制性量程、这组矩阵、不做色域映射。

    这就是一台老实的色彩管理观看者会做的事，所以「标签是真话」在这里是可量的一件事。
    `scale` 是那把尺的刻度：10 位的码字就是 8 位的四倍（亮度 64..940、色度以 512 为中心）。
    """
    kr, kg, kb = coefficients
    y = (triple[0] - 16 * scale) / (219 * scale)
    cb = (triple[1] - 128 * scale) / (224 * scale)
    cr = (triple[2] - 128 * scale) / (224 * scale)
    b = y + 2 * (1 - kb) * cb
    r = y + 2 * (1 - kr) * cr
    g = (y - kr * r - kb * b) / kg
    return tuple(round(max(0.0, min(1.0, value)) * 255) for value in (r, g, b))


def bt709_eotf(signal: float) -> float:
    """声明成 bt709 的那格信号换回线性光（ITU-R BT.709 那组 α/β/4.5）。"""
    if signal <= BT709_SIGNAL_TURN:
        return signal / BT709_SLOPE
    return ((signal + BT709_BETA) / BT709_ALPHA) ** (1 / 0.45)


def bt709_oetf(light: float) -> float:
    """`bt709_eotf` 的逆。"""
    if light < BT709_LIGHT_TURN:
        return BT709_SLOPE * light
    return BT709_ALPHA * light**0.45 - BT709_BETA


def shift_signal(rgb, matrix):
    """存储值 → 线性 → 乘公布矩阵 → 落回存储值（换基色那一步的完整算式）。"""
    linear = [bt709_eotf(value / 255.0) for value in rgb]
    moved = [sum(matrix[row][col] * linear[col] for col in range(3)) for row in range(3)]
    return tuple(round(max(0.0, min(1.0, bt709_oetf(value))) * 255) for value in moved)


def shift_pair(row):
    """这一档要换的那对基色；不换的档就是同一档（恒等矩阵）。"""
    target = str(row.get("shift_to") or "")
    if not target:
        return "rec709", "rec709"
    return str(row["shift_from"]), target


def tiers_suite(folder: Path) -> None:
    """表里每一档都真跑一次：编译串、真编码、探针读标记、按标记解回源色。

    1.151 那一版只有一档，各处断言写的都是那一档的数。这一条把「加一档」变成会被量的事，
    而每一档的期望值都从**公布数**算出来：
      (a) 容器 trio 与折叠那一句等于表里那几个值；
      (b) 要换基色的档，图里必须多一站 `lut3d`，且作业目录里真的落了一张立方体；
      (c) 折出来的 YUV 等于「公布矩阵换过的编码值 + 这一档公布的系数」独立算出的那一组；
      (d) 一台老实的色彩管理观看者按四样标记解回来，必须落在源色的量具地板之内
          （地板由恒等立方体的控制组量：1.153 是 (1,1,0)）。
      (e) 顺手交一份 MXF：1.151 那句「只在 mp4 上量过回读」现在逐档量。
    """
    project = build_project(folder)
    solid = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            folder / "solid.png",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    rgb = tuple(solid[:3])
    seen = []
    for row in OUTPUT_COLOUR_TAGS:
        code = str(row["id"])
        matrix_name = str(row["matrix"])
        if matrix_name not in FOLD_COEFFICIENTS:
            raise AssertionError(
                f"档位 {code} 声明的矩阵 {matrix_name!r} 没有独立系数出处，这条检查拦不住它"
            )
        coefficients = FOLD_COEFFICIENTS[matrix_name]
        source, target = shift_pair(row)
        if (source, target) not in SHIFT_MATRICES:
            raise AssertionError(f"档位 {code} 的基色对 {source}->{target} 没有公布矩阵可抄")
        shift = SHIFT_MATRICES[(source, target)]
        plan = plan_for(project, code)
        argv = " ".join(plan.ffmpeg_argv(str(FFMPEG), f"tier-{code}.mp4"))
        for flag, value in (
            ("-color_primaries", row["primaries"]),
            ("-color_trc", row["transfer"]),
            ("-colorspace", matrix_name),
        ):
            assert f"{flag} {value}" in argv, (code, flag, argv[-400:])
        fold = f"zscale=matrix={row['zscale_matrix']}:range={row['zscale_range']}"
        assert any(fold in line for line in plan.filters), (code, fold)
        cube_files = [name for name in plan.text_files if name.startswith("primaries-")]
        if source == target:
            assert not cube_files, (code, cube_files)
            assert "lut3d" not in json.dumps(plan.filters), (code, plan.filters)
        else:
            assert len(cube_files) == 1, (code, cube_files)
            assert any("lut3d=file=" in line for line in plan.filters), (code, plan.filters)

        # 期望的编码值：换基色的那一站先按公布矩阵把画面搬过去，再谈折叠。
        want_signal = shift_signal(rgb, shift) if source != target else rgb
        want_fold = reference_yuv(want_signal, *coefficients)

        master = export(folder, project, code, f"tier-{code}.mp4")
        stream = probe_stream(master)
        for key, want in (
            ("color_primaries", row["primaries"]),
            ("color_transfer", row["transfer"]),
            ("color_space", matrix_name),
        ):
            assert stream.get(key) == want, (code, key, stream)
        assert stream.get("color_range") in (None, "tv"), (code, stream)
        got = plane_triple(master)
        assert all(abs(g - w) <= 1 for g, w in zip(got, want_fold)), (
            f"档位 {code} 折出 {got}，独立系数算出的是 {want_fold}"
        )
        # 观看者要乘的是**反方向**那张表；这里用错方向就是我自己刚犯过的错，红过一次才钉下来。
        back = viewer_recovers(got, coefficients, SHIFT_MATRICES[(target, source)])
        assert all(abs(b - s) <= 2 for b, s in zip(back, rgb)), (
            f"档位 {code} 按自己的标记解回 {back}，不是源色 {rgb}"
        )

        mxf_plan = compile_render_plan(project, "mxf-mpeg2", colour_tag=code, range_ticks=(0, T))
        for file_name, body in mxf_plan.text_files.items():
            (folder / file_name).write_text(body, encoding="utf-8")
        mxf_out = folder / f"tier-{code}.mxf"
        run(mxf_plan.ffmpeg_argv(str(FFMPEG), str(mxf_out)), cwd=folder)
        mxf_stream = probe_stream(mxf_out)
        for key, want in (
            ("color_primaries", row["primaries"]),
            ("color_transfer", row["transfer"]),
            ("color_space", matrix_name),
        ):
            assert mxf_stream.get(key) == want, (code, "mxf", key, mxf_stream)
        seen.append((code, got, back, want_fold))

    triples = {item[1] for item in seen}
    assert len(triples) == len(seen), seen
    assert COLOUR_TAG_CODES == tuple(str(row["id"]) for row in OUTPUT_COLOUR_TAGS)
    print(
        "PASS tiers: "
        + "；".join(
            f"{code} 期望 {want} 折成 {got}、按标记解回 {back}（源 {rgb}），mp4 与 MXF 都读回标记"
            for code, got, back, want in seen
        )
    )


def viewer_recovers(triple, coefficients, shift, scale=1):
    """一台老实的色彩管理观看者：按这一档的系数解出编码值，按 bt709 进线性，乘公布的反方向
    矩阵换回 709，再落回 bt709。矩阵与曲线都用本文件抄的那份，不问引擎要。"""
    encoded = unfold_rgb(triple, coefficients, scale)
    if shift is IDENTITY_3X3:
        return encoded
    linear = [bt709_eotf(value / 255.0) for value in encoded]
    moved = [sum(shift[row][col] * linear[col] for col in range(3)) for row in range(3)]
    return tuple(round(max(0.0, min(1.0, bt709_oetf(value))) * 255) for value in moved)


RAMP_BLOCK = 2  # 图案的最小颗粒，与最狠的那一档抽样（4:2:0）对齐
RAMP_WIDTH, RAMP_HEIGHT = 256 * RAMP_BLOCK, 8  # 每两块一值，扫出来的仍是完整那 256 级
FILTER_COMMA = ","  # 表达式在单引号里，逗号不用转义：转义了反而把反斜杠留给解析器
# 四条渐变：三条各扫两根色度轴，第四条是纯亮度斜坡。每一格是 2x2 的块，因为交付画面最粗的抽样
# 是 4:2:0（两列两行共用一个色度）。颗粒比它细的图案量到的是抽样本身而不是标签：旧的逐列渐变
# 在 8 位 4:2:0 上连**不带任何转换**那一档都解到 102 阶，1.153 的一条拒绝就是被那个数撑错的。
RAMP_LANES = (("X", "255-X", "128"), ("X", "128", "255-X"), ("128", "X", "255-X"), ("X", "X", "X"))


def lane_number(token: str, x: int) -> int:
    """具体那一块在该条渐变里的值——期望值走这里。"""
    if token == "X":
        return x
    if token == "255-X":
        return 255 - x
    return int(token)


def lane_token(token: str, sweep: str) -> str:
    """同一个 token 在 `geq` 里的写法——生成走这里。两份各写一次是故意的，`build_ramp_project`
    把 PNG 逐块读回来与 `ramp_expected` 比一遍，谁漂了当场对不上。"""
    if token == "X":
        return sweep
    if token == "255-X":
        return f"255-{sweep}"
    return token


def block_value(x: int) -> int:
    """那一列所属那一块的序号：块宽 2、总宽 512，序号正好走满 0..255。"""
    return x // RAMP_BLOCK


def ramp_geq() -> str:
    """列取 `floor(X/2)`、行按块的下边界分派，写出来的 PNG 就是 2×2 的块。"""
    sweep = f"floor(X/{RAMP_BLOCK})"
    planes = []
    for index in range(3):
        expr = lane_token(RAMP_LANES[-1][index], sweep)  # 最浅的那一条也是渐变，不是定值
        for row in range(len(RAMP_LANES) - 2, -1, -1):
            expr = (
                f"if(lt(Y{FILTER_COMMA}{(row + 1) * RAMP_BLOCK})"
                f"{FILTER_COMMA}{lane_token(RAMP_LANES[row][index], sweep)}"
                f"{FILTER_COMMA}{expr})"
            )
        planes.append(f"{('r', 'g', 'b')[index]}='{expr}'")
    return "geq=" + ":".join(planes)


def ramp_expected(row: int, x: int) -> tuple[int, int, int]:
    sweep = block_value(x)
    lane = RAMP_LANES[row // RAMP_BLOCK]
    return tuple(lane_number(token, sweep) for token in lane)  # type: ignore[return-value]


def build_ramp_project(folder: Path):
    """一条 256×8 的渐变 PNG：PNG 解出来就是精确的 RGB，不必先过一趟 YUV。"""
    png = folder / "ramp.png"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"nullsrc=s={RAMP_WIDTH}x{RAMP_HEIGHT},format=gbrp,{ramp_geq()}",
            "-frames:v",
            "1",
            str(png),
        ]
    )
    assert png.is_file(), png
    # 先探 fixture：PNG 是无损的，那一格就应当正是 `ramp_expected` 说的数。这一步不做，
    # 后面量到的任何偏差都可能是素材而不是引擎——1.152 那一轮就是这么被骗过一次的。
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            png,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    assert len(raw) == RAMP_WIDTH * RAMP_HEIGHT * 3, (len(raw), RAMP_WIDTH * RAMP_HEIGHT * 3)
    for row in range(0, RAMP_HEIGHT, RAMP_BLOCK):
        for x in range(0, RAMP_WIDTH, 7 * RAMP_BLOCK):
            want = ramp_expected(row, x)
            for dy in range(RAMP_BLOCK):
                for dx in range(RAMP_BLOCK):
                    cell = (row + dy) * RAMP_WIDTH + x + dx
                    got = tuple(raw[cell * 3 + i] for i in range(3))
                    assert got == want, f"第 {row + dy} 行第 {x + dx} 列是 {got}，本该 {want}"
    media = MediaService(folder / "ramp.sqlite3", [folder], folder / "ramp-cache", FFMPEG, FFPROBE)
    store = ProjectStore(media.db_path, media)
    probe = media.import_file(str(png))
    project = store.create(
        CreateProject(
            request_id="ramp-new",
            name="ramp",
            settings={"width": RAMP_WIDTH, "height": RAMP_HEIGHT},
        )
    ).project
    batch = EditBatch.model_validate(
        {
            "request_id": "ramp-seed",
            "expected_revision": project.revision,
            "commands": _commands(probe),
        }
    )
    return apply_commands(project, batch.commands)


def ramp_rows(path: Path) -> tuple[list[list[tuple[int, int, int]]], int]:
    """成片的每一行、每一列的 YUV 三元组（4:4:4 直读，一个像素都不抽样）。

    宽一点的位深是**每个采样两个字节**（yuv444p10le），按字节取会把高低位错开——第一版就是这么
    读出满屏假偏差的。这里按探针说的位深取宽度，再折回 8 位那把尺（10 位÷4、12 位÷16）。
    """
    stream = probe_stream(path)
    width, height = int(stream["width"]), int(stream["height"])
    pix_fmt = str(stream["pix_fmt"])
    step = 4 if "10" in pix_fmt else (16 if "12" in pix_fmt else 1)
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            path,
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv444p10le" if step == 4 else ("yuv444p12le" if step == 16 else "yuv444p"),
            "pipe:1",
        ]
    )
    size = width * height
    if step > 1:
        samples = list(array("H", raw))
        assert len(samples) >= size * 3, (len(samples), size)
        rows = [
            [
                (
                    samples[y * width + x],
                    samples[size + y * width + x],
                    samples[2 * size + y * width + x],
                )
                for x in range(width)
            ]
            for y in range(height)
        ]
    else:
        assert len(raw) >= size * 3, (len(raw), size)
        rows = [
            [
                (raw[y * width + x], raw[size + y * width + x], raw[2 * size + y * width + x])
                for x in range(width)
            ]
            for y in range(height)
        ]
    # 码字原样交出，刻度跟着位深走。先截成 8 位再比，等于把 10 位交付白送的精度丢掉——
    # 1.153 那个「暗部饱和色解不回源色、差 85 阶」的幽灵就是这么造出来的。
    return rows, step


FLAT_WIDTH, FLAT_HEIGHT = 64, 36
FLAT_COLUMN, FLAT_ROW = 32, 18
# 一句基色声明所指的是**一个颜色**，不是一幅画：所以判它兑不兑得了现，要拿纯色去量。
# `FLAT_LIMIT` 是判据（1.153 拿五种画面格式各取一条、三片 709 之外的边缘色量到的最差是 2 阶）。
FLAT_COLOURS = ((20, 5, 5), (0, 128, 0), (5, 5, 20))
FLAT_LIMIT = 4
# 那条每两像素换一次色度的渐变只量得出**带得动它**的画面（10 位 4:4:4）。其余画面上连不带立方体
# 那一档都解到 126 阶，那个数说的是抽样，不是标签——所以这条检查对它们只断言「量具确实不成立」，
# 真正判那份像素的是上面那把纯色尺。
RAMP_LIMIT = 8  # 量具自己的地板：控制档（不带任何转换）在这份画面上也得过得了这一条
TIER_LIMIT = 9  # 三种 10 位画面上量到的最大是 8 阶（prores-4444-alpha），留一阶
TIER_SPREAD = 7  # 比同一条的控制档多出来的那几阶：量到的是 5~6，留一阶
WIDE_CODE = "bt2020"


def picture_presets() -> list[dict]:
    return [item for item in render_presets() if not item["sequence"] and item["codec"] is not None]


def representative_presets() -> list[dict]:
    """每一种画面格式取一条代表：判据说的是那份像素，不是那条预设的名字。"""
    seen: dict[str, dict] = {}
    for item in picture_presets():
        seen.setdefault(str(item["pixel_format"]), item)
    return list(seen.values())


def build_flat_project(folder: Path, media, store, index: int, colour: tuple[int, int, int]):
    """一帧纯色：PNG 是无损的，先探它一眼，确认那一格正是画出来的数。"""
    png = folder / f"flat{index}.png"
    run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "nullsrc=s={}x{},format=gbrp,geq=r={}:g={}:b={}".format(
                FLAT_WIDTH, FLAT_HEIGHT, colour[0], colour[1], colour[2]
            ),
            "-frames:v",
            "1",
            str(png),
        ]
    )
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-i",
            str(png),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    got = tuple(raw[(FLAT_ROW * FLAT_WIDTH + FLAT_COLUMN) * 3 + i] for i in range(3))
    assert got == colour, f"纯色素材第 {index} 片是 {got}，本该是 {colour}"
    probe = media.import_file(str(png))
    project = store.create(
        CreateProject(
            request_id=f"flat-new-{index}",
            name=f"flat{index}",
            settings={"width": FLAT_WIDTH, "height": FLAT_HEIGHT},
        )
    ).project
    batch = EditBatch.model_validate(
        {
            "request_id": f"flat-seed-{index}",
            "expected_revision": project.revision,
            "commands": _commands(probe),
        }
    )
    return apply_commands(project, batch.commands)


def flat_recovery(folder: Path, projects: dict, preset_id: str, code: str):
    """这一条预设挂着这一档交出来的纯色，按容器那四样标记解回来之后与源色最大差几阶。"""
    spec = next(row for row in OUTPUT_COLOUR_TAGS if str(row["id"]) == code)
    coefficients = FOLD_COEFFICIENTS[str(spec["matrix"])]
    source, target = shift_pair(spec)
    shift = SHIFT_MATRICES[(target, source)]
    container = str(
        next(item for item in render_presets() if str(item["id"]) == preset_id)["container"]
    )
    worst = 0
    detail = []
    for index, colour in enumerate(FLAT_COLOURS):
        plan = compile_render_plan(projects[index], preset_id, colour_tag=code, range_ticks=(0, T))
        for file_name, body in plan.text_files.items():
            (folder / file_name).write_text(body, encoding="utf-8")
        out = folder / f"flat-{preset_id}-{code}-{index}.{container}"
        run(plan.ffmpeg_argv(str(FFMPEG), str(out)), cwd=folder)
        rows, scale = ramp_rows(out)
        got = viewer_recovers(rows[FLAT_ROW][FLAT_COLUMN], coefficients, shift, scale)
        delta = max(abs(g - w) for g, w in zip(got, colour))
        worst = max(worst, delta)
        detail.append(f"{colour}->{got}")
    return worst, detail


def flat_suite(folder: Path) -> None:
    """每一种画面格式都把「基色声明兑不兑得了现」量一遍——宽色域那一档不再被任何画面拒掉。

    这一条是 1.153 把那条拒绝撤掉的根据。曾经撑住那句拒绝的是渐变档在 8 位 4:2:0 上量到的 134 阶，
    可在同一份像素上连**不带任何转换**那一档都解到 126 阶：那是色度抽样，与标签无关。纯色没有抽样
    可躲，量的正是「按这四样标记解回来还是不是那个颜色」。
    """
    media = MediaService(folder / "flat.sqlite3", [folder], folder / "flat-cache", FFMPEG, FFPROBE)
    store = ProjectStore(media.db_path, media)
    projects = {
        index: build_flat_project(folder, media, store, index, colour)
        for index, colour in enumerate(FLAT_COLOURS)
    }
    control = COLOUR_TAG_CODES[0]
    seen: dict[tuple[str, str], int] = {}
    lines = []
    for item in representative_presets():
        preset_id = str(item["id"])
        for code in (control, WIDE_CODE):
            worst, detail = flat_recovery(folder, projects, preset_id, code)
            seen[(preset_id, code)] = worst
            assert worst <= FLAT_LIMIT, (
                f"{preset_id} 挂 {code} 把纯色解偏 {worst} 阶，过不了 {FLAT_LIMIT} 阶那条线"
            )
            if code == WIDE_CODE:
                lines.append(
                    f"{preset_id} {item['pixel_format']} 控制 "
                    f"{seen[(preset_id, control)]} 阶 / 宽色 {worst} 阶（{'  '.join(detail)}）"
                )
        wide, base = seen[(preset_id, WIDE_CODE)], seen[(preset_id, control)]
        assert wide <= base + 2, (
            f"{preset_id} 换基色那一档比不带转换多出 {wide - base} 阶：立方体把颜色搬出了画面"
        )
    print("PASS flat: 基色声明按纯色逐格式量过——" + "；".join(lines) + f"（判据 {FLAT_LIMIT} 阶）")


def ramp_worst(folder: Path, project, preset_id: str, code: str) -> tuple[int, int, int]:
    """这一条预设挂着这一档交出来的渐变，逐列解回源色之后三根轴各自的最大偏差。"""
    spec = next(row for row in OUTPUT_COLOUR_TAGS if str(row["id"]) == code)
    coefficients = FOLD_COEFFICIENTS[str(spec["matrix"])]
    source, target = shift_pair(spec)
    plan = compile_render_plan(
        project,
        preset_id,
        colour_tag=code,
        preview_size=(RAMP_WIDTH, RAMP_HEIGHT),
        range_ticks=(0, T),
    )
    for file_name, body in plan.text_files.items():
        (folder / file_name).write_text(body, encoding="utf-8")
    container = str(
        next(item for item in render_presets() if str(item["id"]) == preset_id)["container"]
    )
    out = folder / f"ramp-{preset_id}-{code}.{container}"
    run(plan.ffmpeg_argv(str(FFMPEG), str(out)), cwd=folder)
    rows, scale = ramp_rows(out)  # 码字原样交出，刻度跟着位深走
    worst = (0, 0, 0)
    per_row = {}
    for row in range(len(RAMP_LANES)):
        for x in range(8, RAMP_WIDTH - 8):
            got = viewer_recovers(
                rows[row][x], coefficients, SHIFT_MATRICES[(target, source)], scale
            )
            want = ramp_expected(row, x)
            delta = tuple(abs(g - w) for g, w in zip(got, want))
            worst = tuple(max(a, b) for a, b in zip(worst, delta))
            per_row[row] = max(per_row.get(row, 0), max(delta))
    print(f"    {preset_id} 挂 {code} 逐行最大偏差：{per_row}")
    return worst


def cube_reference(shift, encoded):
    """立方体那一格**应当**是多少：本文件的公布矩阵 + 本文件的曲线，独立算一遍。"""
    linear = [bt709_eotf(value) for value in encoded]
    moved = [sum(shift[row][col] * linear[col] for col in range(3)) for row in range(3)]
    return [bt709_oetf(max(0.0, min(1.0, value))) for value in moved]


def parse_delivery_cube(body: str) -> tuple[int, list[list[float]]]:
    """读回引擎写的那张 `.cube`：既定次序是红变化最快、蓝最慢，那一行的下标是
    `(蓝×大小+绿)×大小+红`——与 `grade.parse_3d_cube` 的读法同一句。"""
    lines = body.splitlines()
    header = [line for line in lines[:8] if line.startswith("LUT_3D_SIZE")]
    assert header, lines[:8]
    size = int(header[0].split()[1])
    start = next(
        position
        for position, line in enumerate(lines)
        if len(line.split()) == 3 and line[0] in "-0123456789"
    )
    cells = [[float(token) for token in line.split()] for line in lines[start : start + size**3]]
    assert len(cells) == size**3, (len(cells), size**3)
    return size, cells


def cube_lattice_error(cells: list[list[float]], size: int, shift) -> float:
    """格点上的值与独立算的那一个最大差几阶（8 位那把尺）——三根轴都走一遍。"""
    top = size - 1
    probes = []
    for a, b in ((0, 0), (top, top), (0, top), (top, top // 2), (top // 2, 0)):
        for index in range(size):
            probes.append((index, a, b))
            probes.append((a, index, b))
            probes.append((a, b, index))
    worst = 0.0
    for red, green, blue in probes:
        encoded = (red / top, green / top, blue / top)
        want = cube_reference(shift, encoded)
        got = cells[(blue * size + green) * size + red]
        worst = max(worst, max(abs(x - y) for x, y in zip(want, got)) * 255)
    return worst


def cube_interpolation_bound(size: int, shift) -> float:
    """格子疏到什么程度：相邻两格的中点与「两端平均」最大差几阶——那就是插值的地板。"""
    top = size - 1
    worst = 0.0
    for others in ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.0, 1.0)):
        for step in range(top):
            low = step / top
            high = (step + 1) / top
            ends = [
                cube_reference(shift, (value, others[0], others[1]))[0] for value in (low, high)
            ]
            mid = cube_reference(shift, ((low + high) / 2, others[0], others[1]))[0]
            worst = max(worst, abs(mid - (ends[0] + ends[1]) / 2) * 255)
    return worst


def cube_suite(folder: Path) -> None:
    """立方体用数学判，不必等一趟编码：格点的值对不对、格子够不够疏，都有解析解。

    1.153 为什么加这一条：渐变那把尺**量不出格数**——同一份渐变在 65³、33³、17³、9³ 上量到的最大
    偏差都是 7 阶（量的，见 `ramp_suite` 那一段的说明）。把格数从 65 砍到 33 少写 6 MB 文本，在交付
    上看不出区别，因此这件事不能交给 FFmpeg 去判，要判的是它自己那条数学地板：相邻两格中点与两端
    平均之差。这一条判的就是那个数，以及格点上的值与独立参考是否同一份。
    """
    project = build_project(folder)
    wide = next(row for row in OUTPUT_COLOUR_TAGS if row.get("shift_to"))
    source, target = shift_pair(wide)
    shift = SHIFT_MATRICES[(source, target)]
    plan = compile_render_plan(project, "prores-422hq", colour_tag=str(wide["id"]))
    names = sorted(name for name in plan.text_files if name.startswith("primaries-"))
    assert len(names) == 1, names
    size, cells = parse_delivery_cube(plan.text_files[names[0]])
    point = cube_lattice_error(cells, size, shift)
    bound = cube_interpolation_bound(size, shift)
    # 格点的值：与独立算的那一份对。文本只写到小数点后六位（合 0.0003 阶），0.5 阶是宽裕的。
    assert point <= 0.5, f"立方体格点与独立算的参考最大差 {point:.2f} 阶"
    # 插值的地板：这一档的格子必须细到中间误差 0.5 阶以内。
    assert bound <= 0.5, f"{size}³ 的格子插值误差地板 {bound:.2f} 阶，过不了 0.5 阶"
    print(
        f"PASS cube: 引擎写的 {size}³ 立方体（{len(plan.text_files[names[0]]) // 1024} KB 文本）"
        f"格点值与独立参考最大差 {point:.2f} 阶，插值地板 {bound:.2f} 阶——都在 0.5 阶以内"
    )


def ramp_suite(folder: Path) -> None:
    """立方体是插值的，所以格与格之间也要量；比较挪到「观看者看到的 RGB」那一站。

    走的是同一条编译出来的图（`preview_size` 把画幅收成渐变自己的尺寸，缩放就成了恒等），四条
    渐变逐列比：按容器声明的曲线与矩阵解回来，应当还是画出来的那一格。判据是**差值**：编码、位深、
    量具那半阶同时作用在同一预设的控制档上，做差就都对消了，只剩立方体的插值与曲线——把 BT.709
    的两个指数对调（一对仍然互逆的错曲线，纯色往返与控制组都查不出来）在这里量到的是 85 阶。

    图案的颗粒是 2x2，与交付画面最粗的那一档抽样对齐。哪一份像素量得动这条渐变，是量出来的
    而不是照格式名猜的：每种格式的代表先跑控制档（不带任何转换那一档），控制档自己过不去
    `RAMP_LIMIT` 的画面，这条就只对那句「量具在这里说不了话」负责，判那份像素的是纯色那把
    `flat_suite`。哪天某份像数量得动了，它自动落进被判的那一组。

    这条判不了立方体的**格数**：同一份渐变在 65³、33³、17³、9³ 上最大偏差都是 7 阶（1.153 量的），
    因为那 7 阶是有损编码器在奈奎斯特图案上的账，不是插值的账。格数由 `cube_suite` 用数学判。
    """
    project = build_ramp_project(folder)
    control = COLOUR_TAG_CODES[0]
    judged: dict[str, dict[str, tuple[int, int, int]]] = {}
    invalid: dict[str, int] = {}
    for item in representative_presets():
        preset_id = str(item["id"])
        base = ramp_worst(folder, project, preset_id, control)
        if max(base) > RAMP_LIMIT:
            # 量具自己先过不去的画面，这一条对它说不了话：每两像素一变的亮度斜坡正落在有损
            # 编码器奈奎斯特上，8 位 4:2:0 的控制档在这里量到 46~62 阶。那份像素由纯色尺判。
            # 这个分类是每轮**量**出来的，不是照格式名猜的——哪一天某份像数量得动了，自动进来。
            invalid[preset_id] = max(base)
            continue
        codes = {control: base}
        for row_spec in OUTPUT_COLOUR_TAGS:
            code = str(row_spec["id"])
            if code == control:
                continue
            worst = ramp_worst(folder, project, preset_id, code)
            codes[code] = worst
            assert max(worst) <= TIER_LIMIT, (
                f"{preset_id} 挂 {code} 渐变最大 {max(worst)} 阶，过不了 {TIER_LIMIT} 阶那条线"
            )
            assert max(worst) <= max(base) + TIER_SPREAD, (
                f"{preset_id} 挂 {code} 是 {max(worst)} 阶，比同一条不带转换的 {max(base)} 阶"
                f"多出 {TIER_SPREAD} 阶以上——立方体的插值或曲线出了问题"
            )
        judged[preset_id] = codes
    assert judged, "没有一种画面量得动这条渐变，这条检查已经在空转"
    covered = set(judged) | set(invalid)
    assert covered == {str(item["id"]) for item in representative_presets()}, covered
    print(
        "PASS ramp: 渐变档逐列判了 "
        + "；".join(
            f"{preset_id} " + "/".join(f"{code} {max(worst)} 阶" for code, worst in codes.items())
            for preset_id, codes in sorted(judged.items())
        )
        + "，量不动的 "
        + "；".join(f"{pid} 控制档 {base} 阶" for pid, base in sorted(invalid.items()))
        + f"（判据 {TIER_LIMIT} 阶 / 比控制档多 {TIER_SPREAD} 阶，纯色那把尺见 flat）"
    )


def refusal_suite(folder: Path) -> None:
    project = build_project(folder)
    presets = {str(item["id"]): item for item in render_presets()}
    for preset_id in ("exr-sequence", "dpx-sequence"):
        try:
            compile_render_plan(project, preset_id, colour_tag="bt709")
            raise AssertionError(f"{preset_id} accepted a colour tag it cannot carry")
        except Exception as error:  # noqa: BLE001
            assert getattr(error, "code", None) == "COLOUR_TAG_NEEDS_CONTAINER", (preset_id, error)
            assert getattr(error, "details", {}).get("preset_id") == preset_id
    # Asked of the argument builder, not of a whole project: a picture-less timeline is refused for
    # its own good reason long before the preset's shape is consulted, and mixing the two up would
    # leave this branch asserted by an error that has nothing to do with colour.
    for preset_id in ("audio-mp3", "audio-wav", "audio-flac"):
        try:
            output_args(presets[preset_id], 48_000, 30.0, colour_tag="bt709")
            raise AssertionError(f"{preset_id} accepted a colour tag")
        except EditorError as error:
            assert error.code == "COLOUR_TAG_NEEDS_PICTURE", (preset_id, error.code)
            assert error.details["preset_id"] == preset_id

    # 宽色域那一档现在与另两档同进同退：挂得上标记的画面都挂得上它，挂不上的还是原来那两条理由。
    # 这一条是「撤掉一条拒绝」的反向保险——把守卫写反（只放行宽色域、把另两档挡在门外）照样红。
    table = colour_tag_presets()
    assert table[COLOUR_TAG_CODES[0]] == table[COLOUR_TAG_CODES[1]] == table[WIDE_CODE], table
    assert table[WIDE_CODE] == [str(item["id"]) for item in picture_presets()], table
    for preset_id in ("prores-422hq", "mxf-prores-422hq", "h264-720p-web", "vp9-1080p-web-alpha"):
        wide = compile_render_plan(project, preset_id, colour_tag=WIDE_CODE)
        assert any("lut3d=file=primaries-" in line for line in wide.filters), preset_id
        assert "-color_primaries bt2020" in " ".join(
            wide.ffmpeg_argv(str(FFMPEG), f"wide-{preset_id}.bin")
        ), preset_id
    for preset_id in ("exr-sequence", "dpx-sequence"):
        try:
            compile_render_plan(project, preset_id, colour_tag=WIDE_CODE)
            raise AssertionError(f"{preset_id} 挂上了容器里没有的标记")
        except EditorError as error:
            assert error.code == "COLOUR_TAG_NEEDS_CONTAINER", (preset_id, error)
    try:
        output_args(presets["audio-mp3"], 48_000, 30.0, colour_tag=WIDE_CODE)
        raise AssertionError("纯声带交出的那份东西没有画面可以写基色")
    except EditorError as error:
        assert error.code == "COLOUR_TAG_NEEDS_PICTURE", error.code
    try:
        compile_render_plan(project, "h264-720p-web", colour_tag="p3-dci")
        raise AssertionError("an unknown tag was accepted")
    except EditorError as error:
        assert error.code == "UNKNOWN_COLOUR_TAG", error.code
        # 钉成字面量：加一档却不改这里，这条就红——那句拒绝必须点齐表里所有的出路。
        assert error.details["known"] == ["bt709", "bt601", "bt2020"], (
            "那句拒绝点名的出路与表不符：" + str(error.details["known"])
        )
        assert error.details["known"] == list(COLOUR_TAG_CODES), error.details
    # A transparent master carries its rgba all the way to the encoder, so which matrix folded the
    # picture is not this graph's business: the claim is refused rather than guessed at...
    try:
        compile_render_plan(project, "vp9-1080p-web-alpha", colour_tag="bt709", transparent=True)
        raise AssertionError("an alpha master accepted a colour claim it cannot back")
    except EditorError as error:
        assert error.code == "COLOUR_TAG_NOT_WITH_ALPHA", error.code
        assert error.details["colour_tag"] == "bt709", error.details
    # ...and the same preset asked honestly (no tag) still compiles the alpha chain it always did.
    plain_alpha = compile_render_plan(project, "vp9-1080p-web-alpha", transparent=True)
    assert any("format=rgba[vout]" in line for line in plain_alpha.filters), plain_alpha.filters
    print(
        "PASS refusals: sequences, audio, unknown ids and alpha masters each name the reason, "
        "and the untagged alpha chain is untouched"
    )


def http_suite(folder: Path) -> None:
    """The query surface has to reach the same plan the exporter builds, and refuse bad ids."""
    media = MediaService(folder / "http.sqlite3", [folder], folder / "http-cache", FFMPEG, FFPROBE)
    store = ProjectStore(media.db_path, media)
    # One database for the store and the render queue, the way the app runs it: the worker reads the
    # project snapshot out of the file the store wrote it to.
    runtime = JobRuntime(media.db_path, FFMPEG, folder / "exports", [folder / "exports", folder])
    png = folder / "solid.png"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{SOURCE_RGB[0]:02x}{SOURCE_RGB[1]:02x}{SOURCE_RGB[2]:02x}"
            f":s={WIDTH}x{HEIGHT}",
            "-frames:v",
            "1",
            str(png),
        ]
    )
    probe = media.import_file(str(png))
    token = "colourtag-" + "0" * 40
    with TestClient(
        create_app(store.path, token, media, jobs=runtime),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "new",
                "name": "tag",
                "settings": {"width": WIDTH, "height": HEIGHT},
            },
        ).json()
        project = created.get("project", created)
        pid, revision = project["id"], project["revision"]
        commands = [
            {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
            {
                "op": "asset.import",
                "asset_id": "s",
                "label": "s",
                "probe_id": probe.id,
                "verified": probe.verified.model_dump(),
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "c",
                    "asset_id": "s",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": T,
                },
            },
        ]
        seeded = client.post(
            f"/v1/projects/{pid}/edits",
            json={"request_id": "seed", "expected_revision": revision, "commands": commands},
        )
        assert seeded.status_code == 200, seeded.text[:300]

        def plan(params):
            answer = client.get(f"/v1/projects/{pid}/render-plan", params=params)
            assert answer.status_code == 200, answer.text[:300]
            return " ".join(answer.json()["argv_preview"])

        base = {"preset_id": "h264-720p-web"}
        assert "-colorspace" not in plan(base), plan(base)[-200:]
        tagged = plan(dict(base, colour_tag="bt709"))
        assert "-colorspace bt709" in tagged and "zscale=matrix=709:range=tv" in tagged, tagged[
            -300:
        ]
        bad = client.get(f"/v1/projects/{pid}/render-plan", params=dict(base, colour_tag="nope"))
        assert bad.status_code == 422, bad.text[:200]
        error = bad.json()["error"]
        assert error["code"] == "UNKNOWN_COLOUR_TAG", error
        assert error["details"]["colour_tag"] == "nope", error["details"]

        # The receipt keys the delivery, not the plan: retrying the same request_id has to hand back
        # the same job, and asking that id for a tagged master is a different delivery — refused,
        # never silently answered with the untagged file that was already queued.
        revision = seeded.json()["project"]["revision"]
        plain_body = {
            "request_id": "one",
            "expected_revision": revision,
            "preset_id": "h264-720p-web",
            "filename": "plain.mp4",
        }

        def queue(body):
            answer = client.post(f"/v1/projects/{pid}/renders", json=body)
            return answer.status_code, answer.json()

        status, first = queue(plain_body)
        assert status == 200, first
        plain_job = first["job"]
        assert plain_job["colour_tag"] is None, plain_job
        status, again = queue(plain_body)
        assert status == 200, again
        assert again["job"]["id"] == plain_job["id"], "the same request_id queued it a second time"
        status, moved = queue(dict(plain_body, colour_tag="bt709"))
        assert status == 409, moved
        assert moved["error"]["code"] == "IDEMPOTENCY_CONFLICT", moved
        status, second = queue(
            dict(plain_body, request_id="two", filename="tagged.mp4", colour_tag="bt709")
        )
        assert status == 200, second
        tagged_job = second["job"]
        assert tagged_job["colour_tag"] == "bt709", tagged_job
        assert tagged_job["id"] != plain_job["id"], (tagged_job["id"], plain_job["id"])
        # The plan shown beside a queued job is that job's own plan, and it has to say the tagged
        # master is tagged. Deterministic by construction: the runtime has a single worker thread,
        # so this second delivery is still queued while the first one is being encoded.
        shown = client.get(f"/v1/jobs/{tagged_job['id']}").json()
        assert shown["job"]["status"] in ("queued", "running"), shown["job"]
        assert shown["plan"]["colour_tag"] == "bt709", shown["plan"]
        # Both deliveries really ran, and the tag survived the round trip through the stored job.
        for job_id in (plain_job["id"], tagged_job["id"]):
            _await(runtime, job_id)
        kept = runtime._load(tagged_job["id"])
        dropped = runtime._load(plain_job["id"])
        assert kept.colour_tag == "bt709", kept
        assert dropped.colour_tag is None, dropped
    print(
        "PASS http: the query surface reaches the same plan, an unknown id is refused by name, and "
        "the queued receipts replay or conflict the way the delivery they describe says"
    )


def capability_suite() -> None:
    # Every preset that can carry a claim folds through YUV. Asserted here rather than branched on
    # in the exporter: an RGB video preset added later must make this red, not quietly ride a
    # `zscale` stage that changes nothing about it.
    foldable = [
        str(item["id"])
        for item in render_presets()
        if not item["sequence"] and item["codec"] is not None
    ]
    formats = {str(item["id"]): str(item["pixel_format"]) for item in render_presets()}
    rgb_video = [pid for pid in foldable if not formats[pid].startswith("yuv")]
    assert not rgb_video, f"these presets carry no YUV fold to tag: {rgb_video}"
    caps = capabilities()
    row = OUTPUT_COLOUR_TAGS[0]
    assert caps["output_colour_tags"] == [dict(item) for item in OUTPUT_COLOUR_TAGS]
    assert [str(item["id"]) for item in caps["output_colour_tags"]] == list(COLOUR_TAG_CODES)
    assert caps["features"]["colour_tag_delivery"] is True
    assert row["matrix"] == row["primaries"] == row["transfer"] == "bt709", row
    assert row["zscale_matrix"] == "709", row
    # 每一档的两条 zscale 拼法都要在随包 FFmpeg 自己的帮助里出现：这就是「先量 zscale 认什么」
    # 那句话落成的门禁——写一个它不认的名字，图当场崩，而这条检查不必等崩。
    help_text = run([FFMPEG, "-hide_banner", "-h", "filter=zscale"]).decode(errors="replace")
    enums = {line.strip().split()[0] for line in help_text.splitlines() if line.startswith("     ")}
    assert enums, "zscale 的帮助没读到任何枚举名，这条门禁就成了空话"
    for item in OUTPUT_COLOUR_TAGS:
        # 折叠与基色不是一回事：只换折叠的那一档，标签必须说它只换了折叠。
        assert str(item["zscale_matrix"]) in enums, (item["id"], str(item["zscale_matrix"]))
        assert str(item["zscale_range"]) in enums, (item["id"], str(item["zscale_range"]))
        if str(item["matrix"]) != str(item["primaries"]) and not item.get("shift_to"):
            # 不换基色、矩阵却与基色不一致——那只能是「只换折叠」，标签必须说清。
            assert "折叠" in str(item["label"]), f"档位 {item['id']} 只换了折叠却没在标签里说清"
        # 声明的基色要么就是图里那份 709，要么这一档必须自带换基色那一站，而且两端都在这张表里；
        # 引擎算的九个数还要对得上 ITU-R BT.2020 公布的表（抄在上面的字面量），差 5e-4 以内。
        assert str(item["transfer"]) == "bt709", item
        source, target = shift_pair(item)
        if source == target:
            assert str(item["primaries"]) == "bt709", (
                f"档位 {item['id']} 不换基色却声明了 {item['primaries']} 基色"
            )
            continue
        assert str(item["primaries"]) == {"rec2020": "bt2020"}.get(target), (
            f"档位 {item['id']} 的基色声明 {item['primaries']} 与要换去的 {target} 对不上"
        )
        assert "基色" in str(item["label"]), f"档位 {item['id']} 的标签没说它换了基色"
        engine = gamut.primaries_matrix(source, target)
        published = SHIFT_MATRICES[(source, target)]
        worst = max(abs(engine[r][c] - published[r][c]) for r in range(3) for c in range(3))
        assert worst <= 5e-4, f"引擎算的 {source}->{target} 与公布表最大差 {worst:.5f}"
        # 反方向不抄第二份记忆，而是钉成「公布前向阵的逆」——1.153 就是抄过一份第二表，
        # 暗部饱和色被放大成 85 阶的偏差才逼出这条断言的。
        back_engine = gamut.primaries_matrix(target, source)
        back_test = SHIFT_MATRICES[(target, source)]
        worst_back = max(
            abs(back_engine[r][c] - back_test[r][c]) for r in range(3) for c in range(3)
        )
        assert worst_back <= 5e-4, f"引擎算的反方向与公布前向阵的逆最大差 {worst_back:.5f}"
        curve = [
            abs(gamut.bt709_oetf(gamut.bt709_eotf(value / 255.0)) * 255 - value)
            for value in range(0, 256, 17)
        ]
        assert max(curve) < 1.0, f"引擎那份 bt709 曲线往返最大偏差 {max(curve):.2f} 阶"

    # A tag may only name a curve this engine can actually convert to: the delivery table and the
    # probe table have to stay joined, or a tagged master would promise a transfer nothing can read.
    assert dict(COLOR_TRANSFER_TAGS)[row["transfer"]] in COLOR_SPACES, row
    print(f"PASS capabilities: {len(COLOUR_TAG_CODES)} tag(s) published from one table")


# The digest the previous release stored for the request built below. Captured by parsing that
# commit's own `jobs.py`, lifting the `canonical = json.dumps(...)` statement out of
# `_submit_locked`, and evaluating it against that commit's own `RenderRequest` — so it is a fact
# from outside this release, not a number 1.151 can recompute and agree with. If a defaulted field
# leaked into the hash, every receipt written before 1.151 would stop replaying and the store would
# queue the same delivery a second time under a new file name.
PRE_1151_CANONICAL = '["proj_pin_1","h264-720p-web","show.mp4",null,"contain"]'
PRE_1151_FINGERPRINT = "39931bfe33e7b53745dd5d50caa79cb82065636e61bd8a6fdddc4de611a5c4cb"


def receipt_suite(folder: Path) -> None:
    """The tagged master is a different delivery; the untagged one is byte-for-byte the old."""
    base = RenderRequest(
        request_id="req_pin",
        expected_revision=7,
        preset_id="h264-720p-web",
        filename="show.mp4",
        folder=None,
        fit="contain",
    )
    assert request_fingerprint("proj_pin_1", base) == PRE_1151_FINGERPRINT, (
        "an untagged request no longer replays as the receipt 1.150 wrote"
    )
    assert hashlib.sha256(PRE_1151_CANONICAL.encode()).hexdigest() == PRE_1151_FINGERPRINT, (
        "the two pins disagree about what joined the hash"
    )
    # A 1.151 client that names the new field and leaves it null must not split the receipt either:
    # that is the same delivery, spelled with one more key.
    assert (
        request_fingerprint("proj_pin_1", base.model_copy(update={"colour_tag": None}))
        == PRE_1151_FINGERPRINT
    ), "an explicit null colour_tag split a pre-1.151 receipt"
    assert (
        request_fingerprint("proj_pin_1", base.model_copy(update={"colour_tag": "bt709"}))
        != PRE_1151_FINGERPRINT
    ), "a tagged master hashed as the untagged one, so a retry would return the wrong file"

    # A tagged delivery on a fresh id really does carry the tag through to the job record — that
    # half is checked where the project is actually persisted (`http_suite`).

    old = VerifiedMedia.model_validate(
        {
            "probe_id": "p",
            "path": "x.mp4",
            "kind": "video",
            "label": "x",
            "size_bytes": 1,
            "content_sha256": "0" * 64,
            "duration_ticks": T,
        }
    )
    assert old.color_transfer is None and old.color_space is None, old
    assert detect_space(old)[1]["reason"] == "no_color_tags", detect_space(old)[1]
    print(
        "PASS receipts: an untagged request still hashes to 1.150's receipt, a tag makes it a "
        "different delivery, and an older probe record says nothing"
    )


def main() -> None:
    assert FFMPEG.is_file(), f"needs the bundled FFmpeg at {FFMPEG}"
    capability_suite()
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        compile_suite(folder)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        master = pixels_suite(folder)
        roundtrip_suite(folder, master)
    for suite in (
        refusal_suite,
        cube_suite,
        video_suite,
        http_suite,
        receipt_suite,
        tiers_suite,
        flat_suite,
        ramp_suite,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            suite(Path(tmp))


if __name__ == "__main__":
    main()
