"""Auto levels: measure one clip's own picture, then write an ordinary `levels` node.

The rule is the percentile stretch every grading surface uses for a one-click correction: the black
point is the level below which only `percentile` of the sampled pixels sit, and the white point the
level above which only that share sits. Discarding a few thousandths of the picture is what keeps a
single specular highlight — or a single dead pixel — from deciding where white is.

Nothing here invents editorial state. The answer is a plain `clip.grade` command carrying the chain
the user already had with the measured node in front, so `apply_edits` stays the only writer of
project state, a dry run writes nothing, and one apply is one revision.
"""

from collections import Counter
from pathlib import Path
from subprocess import Popen

from .contracts import (
    GRADE_NODE_LIMIT,
    TIMEBASE,
    EditorError,
    FrameRate,
    GradeLevels,
)

ANALYSIS_WIDTH = 256
FRAME_BYTES = 1 << 20
# A measured black and white closer than this leaves nothing to stretch: the node would multiply a
# handful of levels by 255/span and call the result a correction.
MIN_SPAN_LEVELS = 16
# BT.601 luma weights, summing to 255 so the divide is exact. Luma is the honest thing for a
# one-click stretch to read: per-channel bounds would pull a cast in from a picture that has none.
LUMA_WEIGHTS = (77, 150, 28)
CHANNEL_LABELS = ("red", "green", "blue")


def _plan_width(source_width: int) -> int:
    return max(32, min(ANALYSIS_WIDTH, source_width))


def decode_rgb(
    ffmpeg: Path,
    source: Path,
    start_seconds: float,
    duration_seconds: float,
    rate: FrameRate,
    source_width: int,
    source_height: int,
    limit: int,
    spread: bool = True,
) -> tuple[int, int, list[bytes]]:
    """Decode at most `limit` frames, never wider than the analysis width.

    With `spread` the frame rate asked of the decoder is `limit / duration`, so the samples are
    spread over the whole clip instead of crowding into its first second — the mistake a fixed `fps`
    would make. A single-frame source (a still image) has nothing to spread: measured here, `fps` on
    a one-frame input outputs *zero* frames, so the caller retries with the stage dropped.
    """
    width = _plan_width(source_width)
    height = max(2, round(source_height * width / source_width / 2) * 2)
    rate_per_second = min(float(limit), float(limit) / max(duration_seconds, 1.0 / 240))
    stages = [
        f"fps={rate_per_second:.6f}" if spread else None,
        f"scale={width}:{height}:flags=area",
        "format=rgb24",
    ]
    argv = [
        str(ffmpeg),
        "-v",
        "error",
        "-nostdin",
        "-ss",
        f"{max(0.0, start_seconds):.6f}",
        "-i",
        str(source),
        "-t",
        f"{duration_seconds:.6f}",
        "-vf",
        ",".join(stage for stage in stages if stage),
        "-frames:v",
        str(limit),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]
    process = Popen(argv, stdout=-1, stderr=-1)
    assert process.stdout is not None and process.stderr is not None
    frames: list[bytes] = []
    stride = width * height * 3
    buffer = bytearray()
    try:
        while chunk := process.stdout.read(FRAME_BYTES):
            buffer += chunk
            while len(buffer) >= stride:
                frames.append(bytes(buffer[:stride]))
                del buffer[:stride]
            if len(frames) >= limit:
                break
        error = process.stderr.read()[-600:]
        code = process.wait(timeout=120)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    if code != 0 and not frames:
        raise EditorError(
            "AUTO_GRADE_FAILED", f"the media engine could not decode this clip: {error!r}", 502
        )
    return width, height, frames


def histograms(frames: list[bytes]) -> tuple[list[int], list[int], list[int], list[int], int]:
    """Per-channel and luma 256-bin counts over every sampled pixel."""
    red, green, blue, luma = [0] * 256, [0] * 256, [0] * 256, [0] * 256
    total = 0
    for frame in frames:
        plane_r, plane_g, plane_b = frame[0::3], frame[1::3], frame[2::3]
        for plane, counts in ((plane_r, red), (plane_g, green), (plane_b, blue)):
            for value, count in Counter(plane).items():
                counts[value] += count
        for r, g, b in zip(plane_r, plane_g, plane_b):
            luma[(r * LUMA_WEIGHTS[0] + g * LUMA_WEIGHTS[1] + b * LUMA_WEIGHTS[2]) // 255] += 1
        total += len(plane_r)
    return red, green, blue, luma, total


def _edges(counts: list[int], skip: int) -> list[int]:
    """The first and last level with more than `skip` sampled pixels on the far side of it."""
    low = 0
    seen = 0
    for level, count in enumerate(counts):
        seen += count
        if seen > skip:
            low = level
            break
    high = 255
    seen = 0
    for level in range(255, -1, -1):
        seen += counts[level]
        if seen > skip:
            high = level
            break
    return [low, high]


def measure(
    ffmpeg: Path,
    source: Path,
    source_width: int,
    source_height: int,
    rate: FrameRate,
    start_ticks: int,
    duration_ticks: int,
    samples: int,
    percentile: float,
) -> dict:
    """Sample the clip's own source window and report the bounds at 8-bit levels."""
    seconds = duration_ticks / TIMEBASE
    if seconds <= 0:
        raise EditorError(
            "AUTO_GRADE_FAILED",
            "the clip has no source length to look at",
            422,
            duration_ticks=duration_ticks,
        )
    frames_wanted = max(1, min(samples, round(seconds * rate.numerator / rate.denominator) or 1))
    args = (
        ffmpeg,
        source,
        start_ticks / TIMEBASE,
        seconds,
        rate,
        source_width,
        source_height,
        frames_wanted,
    )
    width, height, frames = decode_rgb(*args)
    if not frames:
        # A one-frame source (a still image) has no window to spread samples across, and the fps
        # stage drops its single frame outright. Read the frames the demuxer actually hands over.
        width, height, frames = decode_rgb(*args, spread=False)
    if not frames:
        raise EditorError(
            "AUTO_GRADE_FAILED",
            "no frame of this clip could be decoded; the source may be shorter than the timeline "
            "thinks, or the file was replaced",
            410,
            requested_frames=frames_wanted,
        )
    red, green, blue, luma, total = histograms(frames)
    skip = int(round(total * percentile))
    return {
        "frames": len(frames),
        "analysis_width": width,
        "analysis_height": height,
        "pixels": total,
        "percentile": percentile,
        "skipped_pixels": skip,
        "source_in_ticks": start_ticks,
        "source_ticks": duration_ticks,
        "luma": _edges(luma, skip),
        "red": _edges(red, skip),
        "green": _edges(green, skip),
        "blue": _edges(blue, skip),
    }


def _levels_nodes(measurement: dict, mode: str) -> list[GradeLevels]:
    """The nodes the measurement asks for, dropping any channel already spanning the full range."""
    bounds = (
        [("rgb", measurement["luma"])]
        if mode == "luma"
        else [(name, measurement[name]) for name in CHANNEL_LABELS]
    )
    nodes = []
    for channel, (low, high) in bounds:
        if (low, high) == (0, 255):
            continue
        if high - low < MIN_SPAN_LEVELS:
            raise EditorError(
                "AUTO_GRADE_NO_RANGE",
                f"the {channel} channel only spans levels {low}-{high} in the sampled frames: "
                "there is no range here to stretch. Check the clip's source window, or raise "
                "`percentile` if the picture is meant to be flat",
                422,
                channel=channel,
                low=low,
                high=high,
                min_span=MIN_SPAN_LEVELS,
            )
        nodes.append(
            GradeLevels(
                channel=channel,  # type: ignore[arg-type]
                black=round(low / 255, 6),
                white=round(high / 255, 6),
                gamma=1.0,
            )
        )
    return nodes


def _held_levels(nodes: list) -> list[int]:
    """Positions of the levels nodes already in this chain, including inside parallel branches."""
    held = []
    for index, node in enumerate(nodes):
        if node.kind == "levels":
            held.append(index)
        elif node.kind == "parallel" and any(branch.kind == "levels" for branch in node.branches):
            held.append(index)
    return held


def plan(project, clip_id: str, measurement: dict, *, mode: str, replace: bool):
    """Hand back the one `clip.grade` command the measurement implies, plus what it says it did."""
    clip = project.clips[clip_id]
    current = list(clip.color.grade)
    held = _held_levels(current)
    if held and not replace:
        raise EditorError(
            "AUTO_GRADE_CONFLICT",
            f"this clip already has levels node(s) at position {held}: a second stretch would "
            "compound the first one, so nothing was written. Remove that node, or send "
            "`replace=true` to recompute it in place",
            422,
            clip_id=clip_id,
            positions=held,
        )
    nodes = _levels_nodes(measurement, mode)
    if not nodes:
        # The picture already spans the whole range this mode measures. Report the measurement and
        # write nothing, rather than burning a revision on a node that cannot change a pixel.
        return [], {
            "mode": mode,
            "measured": _reported(measurement, mode),
            "nodes": [],
            "removed": held,
            "reason": "already spans the full range this measurement looks at",
        }
    kept = [node for index, node in enumerate(current) if index not in held]
    grade = nodes + kept
    if len(grade) > GRADE_NODE_LIMIT:
        raise EditorError(
            "AUTO_GRADE_LIMIT",
            f"the chain already holds {len(kept)} node(s) and this correction needs "
            f"{len(nodes)}: the limit is {GRADE_NODE_LIMIT}. Remove a node, or measure luma "
            "(one node) instead of per-channel rgb",
            422,
            clip_id=clip_id,
            existing=len(kept),
            needed=len(nodes),
            limit=GRADE_NODE_LIMIT,
        )
    commands = [
        {"op": "clip.grade", "clip_id": clip_id, "grade": [node.model_dump() for node in grade]}
    ]
    notes = {
        "mode": mode,
        "measured": _reported(measurement, mode),
        "nodes": [node.model_dump() for node in nodes],
        "removed": held,
        "chain_length": len(grade),
    }
    return commands, notes


def _reported(measurement: dict, mode: str) -> dict:
    """The part of the measurement the reply carries: bounds, samples, and how much was clipped."""
    keys = ("luma", "red", "green", "blue") if mode == "rgb" else ("luma",)
    return {
        "frames": measurement["frames"],
        "pixels": measurement["pixels"],
        "percentile": measurement["percentile"],
        "skipped_pixels": measurement["skipped_pixels"],
        # Say which slice of the source was read: a sped-up clip plays less of it, and whoever
        # checks these numbers has to be able to see the window they came from.
        "window": {
            "source_in_ticks": measurement["source_in_ticks"],
            "source_ticks": measurement["source_ticks"],
        },
        "analysis": f"{measurement['analysis_width']}x{measurement['analysis_height']}",
        "bounds": {name: measurement[name] for name in keys},
    }
