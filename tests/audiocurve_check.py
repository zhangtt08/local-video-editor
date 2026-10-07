"""The gain curve, measured on the audio that actually came out of the render.

`gain` keyframes reach FFmpeg as `volume='…':eval=frame`, compiled by the same expression builder as
the picture. Existing audio checks measure a duck's total, a loudness target, or a pitch — mostly at
whole seconds. Nobody has swept the curve: whether the fade is on the timeline clock (like the
picture) rather than the source clock, whether it holds mid-segment under ease and bezier, and
whether it survives a speed change. Every one of those is a place a curve can be wrong while the
endpoints look perfect.

The measurement is differential, the way it has to be: RMS is compared with the RMS of the same
render with no curve on it, so the encoder, the resampler and the tone's own envelope cancel out.
"""

import array
import subprocess
import tempfile
from math import sqrt
from pathlib import Path

from agentcut.animation import expression, sample
from agentcut.contracts import (
    TIMEBASE as T,
)
from agentcut.contracts import (
    Clip,
    Keyframe,
    Project,
    SequenceSettings,
    Track,
    VerifiedMedia,
)
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
RATE = 48_000
SECONDS = 4
# The 200% case reads twice its timeline of source, so the tone has to be long enough for it.
SOURCE_SECONDS = 2 * SECONDS
FRAME = T // 30
WINDOW = 0.1
# The curve: linear down, an eased valley, a bezier climb, then a stepped hold at the end.
GAIN_KEYS = [
    Keyframe(property="gain", at_ticks=0, value=1.0, interpolation="linear"),
    Keyframe(property="gain", at_ticks=T, value=0.25, interpolation="ease"),
    Keyframe(property="gain", at_ticks=int(2.4 * T), value=1.0, interpolation="bezier"),
    Keyframe(property="gain", at_ticks=int(3.2 * T), value=0.6, interpolation="hold"),
    Keyframe(property="gain", at_ticks=SECONDS * T - FRAME, value=0.6, interpolation="linear"),
]
TRACK_VOLUME = 0.8
# Measured drift across 39 windows is <= 0.01; this leaves room for the AAC round trip.
TOLERANCE = 0.03


def run(args, timeout=420):
    done = subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )
    return done.stdout


def source(folder: Path) -> Path:
    """A steady 440 Hz tone at a fixed level, so amplitude changes only come from the curve."""
    target = folder / "tone.mp4"
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
            f"sine=frequency=440:sample_rate={RATE}:duration={SOURCE_SECONDS}",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x404040:s=160x90:r=30:d={SOURCE_SECONDS}",
            "-t",
            str(SOURCE_SECONDS),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(target),
        ]
    )
    measured = float(
        run(
            [
                str(FFPROBE),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(target),
            ]
        )
        .decode()
        .strip()
    )
    assert abs(measured - SOURCE_SECONDS) < 0.15, f"the tone is {measured}s, not {SOURCE_SECONDS}s"
    return target


def clip(speed: int, keys: list[Keyframe]) -> Clip:
    built = Clip.model_validate(
        {
            "id": "c",
            "asset_id": "a",
            "track_id": "a1",
            "position_ticks": 0,
            "duration_ticks": SECONDS * T,
            "speed_percent": speed,
        }
    )
    built.keyframes = keys
    return built


def project(clip: Clip, track_volume: float = 1.0) -> Project:
    """A picture to make the timeline renderable, plus the audio clip under test."""
    verified = VerifiedMedia.model_validate(
        {
            "probe_id": "a",
            "path": "C:/nowhere/tone.mp4",
            "kind": "audio",
            "label": "tone",
            "size_bytes": 4096,
            "content_sha256": "0" * 64,
            "duration_ticks": SOURCE_SECONDS * T,
            "width": 160,
            "height": 90,
            "has_audio": True,
        }
    )
    picture = verified.model_copy(update={"probe_id": "vid", "kind": "video"})
    video = Clip.model_validate(
        {
            "id": "cv",
            "asset_id": "vid",
            "track_id": "v",
            "position_ticks": 0,
            "duration_ticks": SECONDS * T,
        }
    )
    return Project(
        id="p",
        name="audio curve",
        settings=SequenceSettings(width=160, height=90),
        tracks=[
            # Muted: the picture exists only to make the timeline renderable. Left unmuted it would
            # mix its own un-attenuated copy of the tone in, and the measured floor would be the
            # mixer's, not the curve's.
            Track(id="v", kind="video", name="画面", muted=True),
            Track(id="a1", kind="audio", name="床", volume=track_volume),
        ],
        assets={
            "a": {
                "id": "a",
                "kind": "audio",
                "label": "tone",
                "reference": "r",
                "duration_ticks": SOURCE_SECONDS * T,
                "verified": verified.model_dump(),
            },
            "vid": {
                "id": "vid",
                "kind": "video",
                "label": "tone",
                "reference": "r",
                "duration_ticks": SOURCE_SECONDS * T,
                "verified": picture.model_dump(),
            },
        },
        clips={"c": clip, "cv": video},
    )


def on_disk(target: Project, path: Path) -> Project:
    """Point the server-verified records at the file this check actually made."""
    for asset_id in ("a", "vid"):
        asset = target.assets[asset_id]
        target.assets[asset_id] = asset.model_copy(
            update={
                "reference": str(path),
                "verified": asset.verified.model_copy(update={"path": str(path)}),
            }
        )
    return target


def build(target: Project, folder: Path, name: str) -> Path:
    plan = compile_render_plan(target, "h264-source-quality")
    assert "volume=" in " ".join(plan.filters), "the audio chain must carry the gain"
    out = folder / name
    job = folder / f"job-{name}"
    job.mkdir(exist_ok=True)
    for file, body in plan.text_files.items():
        (job / file).write_text(body, encoding="utf-8")
    done = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=420,
        creationflags=0x08000000,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-900:]
    return out


def rms_windows(path: Path) -> list[float]:
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "pipe:1",
        ]
    )
    samples = array.array("f")
    samples.frombytes(raw[: len(raw) - len(raw) % 4])
    size = int(RATE * WINDOW)
    return [
        sqrt(sum(value * value for value in samples[start : start + size]) / size)
        for start in range(0, len(samples) - size, size)
    ]


def seconds() -> list[float]:
    return [round(index * WINDOW + WINDOW / 2, 3) for index in range(int(SECONDS / WINDOW) - 1)]


def sweep(label: str, curve: Path, flat: Path, subject: Clip, volume: float) -> list:
    measured = rms_windows(curve)
    base = rms_windows(flat)
    assert len(measured) == len(base) >= 30, (len(measured), len(base))
    misses: list[str] = []
    worst = (0.0, None)
    for index, at in enumerate(seconds()):
        if index >= len(measured) or base[index] <= 1e-6:
            continue
        got = measured[index] / base[index]
        # The track volume multiplies both renders, so it cancels out of the ratio: what is left is
        # exactly the curve. Passing `volume` in here would double-count it.
        at_ticks = round(at * T)
        want = sample(subject, "gain", at_ticks)
        # A window is 0.1 s long and the curve moves inside it, so the honest allowance is half a
        # window of the local slope, plus a little for the codec. A flat stretch still has to match
        # to 0.02; only a steep ramp gets to be a wider miss.
        slope = abs(
            sample(subject, "gain", at_ticks + round(WINDOW * T))
            - sample(subject, "gain", max(0, at_ticks - round(WINDOW * T)))
        ) / (2 * WINDOW)
        allowance = 0.02 + 0.5 * WINDOW * slope
        drift = abs(got - want)
        if drift / allowance > worst[0]:
            worst = (
                drift / allowance,
                f"{at}s: ratio {got:.3f}, authority {want:.3f} (drift {drift:.3f} /"
                f" allowance {allowance:.3f})",
            )
        if drift > allowance:
            misses.append(
                f"{at}s: ratio {got:.3f} vs authority {want:.3f} (allowance {allowance:.3f})"
            )
    print(
        f"   {label}: {len(seconds())} windows of {WINDOW}s, worst {worst[0]:.2f}× its allowance"
        f" ({worst[1]})"
    )
    return misses


def clock_suite() -> None:
    """The compiled expression has to be on the timeline clock, like the picture is."""
    subject = clip(100, GAIN_KEYS)
    stage = expression(subject, "gain")
    assert "t+" in stage or "(t" in stage, stage[:120]
    assert sample(subject, "gain", 0) == 1.0, "the curve starts at unity"
    held = sample(subject, "gain", int(3.5 * T))
    assert abs(held - 0.6) < 1e-6, f"a hold must stay put, got {held}"
    assert abs(sample(subject, "gain", int(2.9 * T)) - 0.6) > 0.05, "the bezier is still climbing"
    print("   the gain expression is written in frame time and a hold really holds")


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="agentcut-audio-"))
    clip_source = source(folder)
    clock_suite()
    misses: list[str] = []

    subject = clip(100, GAIN_KEYS)
    curve = build(on_disk(project(subject, TRACK_VOLUME), clip_source), folder, "curve.mp4")
    flat = build(on_disk(project(clip(100, []), TRACK_VOLUME), clip_source), folder, "flat.mp4")
    misses += sweep(
        "100% speed, track volume cancels in the ratio", curve, flat, subject, TRACK_VOLUME
    )

    # Same curve, twice the speed: the fade belongs to the timeline, so the ratio at a given output
    # second must still be the authority's value at that second.
    fast_subject = clip(200, GAIN_KEYS)
    fast_curve = build(on_disk(project(fast_subject, 1.0), clip_source), folder, "fast-curve.mp4")
    fast_flat = build(on_disk(project(clip(200, []), 1.0), clip_source), folder, "fast-flat.mp4")
    misses += sweep("200% speed, timeline clock", fast_curve, fast_flat, fast_subject, 1.0)

    measured, base = rms_windows(curve), rms_windows(flat)
    straight = [
        index
        for index in range(len(base))
        if index < len(measured) and abs(measured[index] / base[index] - 1.0) > TOLERANCE
    ]
    assert len(straight) > 10, f"only {len(straight)} windows disagree with a flat gain"
    print(f"   self-test: {len(straight)} windows disagree when compared against no curve at all")

    assert not misses, "the exported audio disagrees with the gain authority:\n" + "\n".join(
        misses[:20]
    )
    print("PASS: the gain curve lands where the authority says, at every tenth of a second")


if __name__ == "__main__":
    main()
