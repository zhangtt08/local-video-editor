"""Every one of the 256 input levels, against the table the browser is handed.

The grade chain compiles to one authority: per-channel polylines, exported as a 256-entry browser
LUT (`grade_tables`) and as an FFmpeg `lutrgb` expression (`grade_filter`). Existing checks
compare a handful of levels, which is how a slip in the middle of a curve can ship unnoticed. A ramp
gives 256 input levels at once, so this compares the compiled expression with the table at
**every** level.

The dense comparison runs the compiled stage over raw RGB with no encoder in between: x264 moves a
smooth gradient by several levels on its own, and measuring that would test the codec, not the
grade. One real render is still made, to prove the stage is inside the exported picture and not
merely available.
"""

import subprocess
import tempfile
from pathlib import Path

from agentcut.contracts import Clip, ClipColor, Project, SequenceSettings, Track, VerifiedMedia
from agentcut.grade import grade_filter, grade_tables
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
T = 70_560_000
WIDTH, HEIGHT = 256, 32
RAMP_ROWS = 16
# block index -> colour, so the three channel tables each get pulled in a different direction.
BLOCKS = [
    (0, 0, 0),
    (255, 255, 255),
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (128, 0, 0),
    (128, 128, 128),
    (0, 200, 255),
]
LEVEL_TOLERANCE = 1.5
NAMES = ("r", "g", "b")


def run(args, timeout=300):
    done = subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )
    return done.stdout


def blocks_expression(values: list[int]) -> str:
    expression = str(values[len(BLOCKS) - 1])
    for index in range(len(BLOCKS) - 2, -1, -1):
        expression = f"if(lt(floor(X/32),{index + 1}),{values[index]},{expression})"
    return expression


def ramp_filter(index: int) -> str:
    """Upper half: a grey ramp across the columns. Lower half: the flat colour blocks."""
    values = [block[index] for block in BLOCKS]
    return f"if(lt(Y,{RAMP_ROWS}),X,{blocks_expression(values)})"


def graded_row(stage: str) -> dict:
    """The 256 input levels and the 8 blocks, pushed through `stage` with no encoder involved."""
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            (
                f"nullsrc=s={WIDTH}x{HEIGHT}:r=1,format=rgb24,"
                f"geq=r='{ramp_filter(0)}':g='{ramp_filter(1)}':b='{ramp_filter(2)}',{stage}"
            ),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    stride = WIDTH * 3
    rows = {}
    for row in (8, 24):
        line = raw[row * stride : (row + 1) * stride]
        rows[row] = [tuple(line[column * 3 : column * 3 + 3]) for column in range(WIDTH)]
    return rows


def chain() -> list[dict]:
    """A chain whose three channel tables are deliberately different from each other."""
    return [
        {
            "kind": "wheels",
            "lift": [-0.04, 0.0, 0.05],
            "gamma": [1.12, 0.93, 1.0],
            "gain": [1.06, 0.98, 1.14],
        },
        {
            "kind": "curve",
            "channel": "red",
            "points": [
                {"x": 0.0, "y": 0.02},
                {"x": 0.25, "y": 0.16},
                {"x": 0.5, "y": 0.58},
                {"x": 0.78, "y": 0.72},
                {"x": 1.0, "y": 0.97},
            ],
        },
        {
            "kind": "curve",
            "channel": "green",
            "points": [{"x": 0.0, "y": 0.0}, {"x": 0.4, "y": 0.52}, {"x": 1.0, "y": 0.9}],
        },
        {"kind": "white_balance", "temperature": 0.28, "tint": -0.12},
        {
            "kind": "curve",
            "channel": "rgb",
            "points": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.44}, {"x": 1.0, "y": 1.0}],
            "mix": 0.6,
            "blend": "screen",
        },
        {"kind": "transfer", "input_space": "srgb", "output_space": "rec709"},
    ]


def project(color: ClipColor, path: Path) -> Project:
    verified = VerifiedMedia.model_validate(
        {
            "probe_id": "a",
            "path": str(path),
            "kind": "video",
            "label": "ramp",
            "size_bytes": 1024,
            "content_sha256": "0" * 64,
            "duration_ticks": T // 3,
            "width": WIDTH,
            "height": HEIGHT,
            "has_audio": False,
        }
    )
    clip = Clip.model_validate(
        {
            "id": "c",
            "asset_id": "a",
            "track_id": "v",
            "position_ticks": 0,
            "duration_ticks": T // 3,
            "color": color.model_dump(),
        }
    )
    return Project(
        id="p",
        name="grade levels",
        settings=SequenceSettings(width=WIDTH, height=HEIGHT),
        tracks=[Track(id="v", kind="video", name="v")],
        assets={
            "a": {
                "id": "a",
                "kind": "video",
                "label": "ramp",
                "reference": str(path),
                "duration_ticks": T // 3,
                "verified": verified.model_dump(),
            }
        },
        clips={"c": clip},
    )


def source(folder: Path) -> Path:
    target = folder / "ramp.mp4"
    run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            (
                f"nullsrc=s={WIDTH}x{HEIGHT}:r=30,format=rgb24,"
                f"geq=r='{ramp_filter(0)}':g='{ramp_filter(1)}':b='{ramp_filter(2)}'"
            ),
            "-t",
            "0.1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-qp",
            "0",
            str(target),
        ]
    )
    return target


def render(color: ClipColor, clip_source: Path, folder: Path, name: str) -> Path:
    plan = compile_render_plan(project(color, clip_source), "h264-source-quality")
    out = folder / name
    job = folder / f"job-{name}"
    job.mkdir(exist_ok=True)
    for file, body in plan.text_files.items():
        (job / file).write_text(body, encoding="utf-8")
    done = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-900:]
    return out


def picture_row(path: Path, row: int) -> list:
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    stride = WIDTH * 3
    line = raw[row * stride : (row + 1) * stride]
    return [tuple(line[column * 3 : column * 3 + 3]) for column in range(WIDTH)]


def sweep(rows: dict, tables: dict, label: str) -> list:
    misses: list[str] = []
    worst = (0.0, None)
    ramp, blocks = rows[8], rows[24]
    for column in range(WIDTH):
        for channel, name in enumerate(NAMES):
            want = tables[name][column] * 255
            drift = abs(ramp[column][channel] - want)
            if drift > worst[0]:
                worst = (drift, f"level {column} {name}: {ramp[column][channel]} vs {want:.2f}")
            if drift > LEVEL_TOLERANCE:
                misses.append(f"level {column} {name}: {ramp[column][channel]} vs {want:.2f}")
    for index, block in enumerate(BLOCKS):
        for channel, name in enumerate(NAMES):
            want = tables[name][block[channel]] * 255
            got = blocks[index * 32 + 16][channel]
            drift = abs(got - want)
            if drift > worst[0]:
                worst = (drift, f"block {index} {name}: {got} vs {want:.2f}")
            if drift > LEVEL_TOLERANCE:
                misses.append(f"block {index} {name}: {got} vs {want:.2f}")
    total = WIDTH * 3 + len(BLOCKS) * 3
    print(f"   {label}: {total} comparisons, worst drift {worst[0]:.2f} ({worst[1]})")
    return misses


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="agentcut-levels-"))
    clip_source = source(folder)
    color = ClipColor(grade=chain())
    tables = grade_tables(color)
    assert tables, "the chain has to be a real grade, not a no-op"
    stage = grade_filter(color)
    assert stage.startswith("lutrgb="), stage[:40]

    misses = sweep(graded_row(stage), tables, "compiled stage")
    straight = {name: [index / 255 for index in range(WIDTH)] for name in NAMES}
    silent = sweep(graded_row(stage), straight, "self-test against no grade")
    assert len(silent) > 300, f"only {len(silent)} comparisons disagree with an identity table"

    plan = compile_render_plan(project(color, clip_source), "h264-source-quality")
    assert "lutrgb" in " ".join(plan.filters), "the compiled plan must carry the grade"
    graded = picture_row(render(color, clip_source, folder, "graded.mp4"), 8)
    identity = picture_row(render(ClipColor(), clip_source, folder, "identity.mp4"), 8)
    moved = sum(graded[level][0] - identity[level][0] for level in range(64, 192)) / 128
    wanted = sum(tables["r"][level] * 255 - level for level in range(64, 192)) / 128
    assert abs(moved - wanted) < 6, (moved, wanted)
    print(
        f"   a real export carries the same grade: mean red shift {moved:.1f} vs table {wanted:.1f}"
    )
    assert not misses, "the exported grade disagrees with the browser table:\n" + "\n".join(
        misses[:20]
    )
    print(
        "PASS: all 256 input levels and 8 flat colours compile to what the shared table says, and"
        " the stage is inside the real export"
    )


if __name__ == "__main__":
    main()
