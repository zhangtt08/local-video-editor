"""Mask tracking by normalized cross-correlation on a downscaled luma plane: stdlib and FFmpeg only.

The tracker follows one box by translation and scale, matched against the template cut from frame 0,
so a target that hides and returns is re-found rather than mutated into the occluder. Correlation
replaces the pixel difference because a difference always prefers the window whose area equals the
template: it cannot tell a target that has grown from one that has left. Normalized correlation
measures shape, so the box can follow a target walking toward the camera, which a difference metric
cannot do. Frames where nothing scores high enough are predicted from recent motion, and an open gap
is truncated at the last sighting. What comes back are ordinary mask keyframes, so `apply_edits`
stays the only writer of project state.
"""

import math
from operator import mul
from pathlib import Path
from statistics import median
from subprocess import Popen

from .contracts import TIMEBASE, EditorError, FrameRate

ANALYSIS_WIDTH = 256
MAX_TEMPLATE = 96 * 54
MAX_FRAMES = 900
FRAME_BYTES = 1 << 20


def _plan_width(source_width: int) -> int:
    return max(32, min(ANALYSIS_WIDTH, source_width))


def decode_luma(
    ffmpeg: Path,
    source: Path,
    start_seconds: float,
    duration_seconds: float,
    rate: FrameRate,
    source_width: int,
    source_height: int,
    limit: int,
) -> tuple[int, int, list[bytes]]:
    """Decode at most `limit` frames as gray bitmaps, never wider than the analysis width."""
    width = _plan_width(source_width)
    height = max(2, round(source_height * width / source_width / 2) * 2)
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
        f"fps={rate.numerator}/{rate.denominator},scale={width}:{height}:flags=area,format=gray",
        "-frames:v",
        str(limit),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    process = Popen(argv, stdout=-1, stderr=-1)
    assert process.stdout is not None and process.stderr is not None
    frames: list[bytes] = []
    stride = width * height
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
        code = process.wait(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    if code != 0 and not frames:
        raise EditorError(
            "TRACK_FAILED", f"the media engine could not decode this clip: {error!r}", 502
        )
    return width, height, frames


def _template_side(half: int) -> int:
    side = max(4, 2 * half)
    while side * side > MAX_TEMPLATE and side > 4:
        side -= 2
    return side


def _crop(frame: bytes, width: int, cx: int, cy: int, side: int) -> tuple[int, int, bytes]:
    """Take the `side`×`side` template centred on (cx, cy), clamped inside the frame."""
    height = len(frame) // width
    x0 = max(0, min(width - side, cx - side // 2))
    y0 = max(0, min(height - side, cy - side // 2))
    rows = [frame[(y0 + row) * width + x0 : (y0 + row) * width + x0 + side] for row in range(side)]
    return x0, y0, b"".join(rows)


def _resample(template: bytes, side: int, target: int) -> bytes:
    if target == side:
        return template
    out = bytearray(target * target)
    for y in range(target):
        source_row = (y * side // target) * side
        base = y * target
        for x in range(target):
            out[base + x] = template[source_row + (x * side // target)]
    return bytes(out)


def _zeroed(patch: bytes) -> tuple[list[float], float]:
    """Centre a template on its own mean and return its energy: the two halves of an NCC match."""
    mean = sum(patch) / len(patch)
    zero = [value - mean for value in patch]
    return zero, math.sqrt(sum(value * value for value in zero))


def _ncc(
    frame: bytes, width: int, x0: int, y0: int, zero: list[float], side: int, tsqrt: float
) -> float:
    """Correlate the window at (x0, y0) with a mean-free template, normalized to at most 1.0."""
    dot = total = square = 0
    offset = y0 * width + x0
    for row in range(side):
        start = offset + row * width
        window = frame[start : start + side]
        dot += sum(map(mul, window, zero[row * side : (row + 1) * side]))
        total += sum(window)
        square += sum(map(mul, window, window))
    count = side * side
    mean = total / count
    variance = square / count - mean * mean
    if variance <= 1.0 or tsqrt <= 1e-9:
        return -1.0
    return dot / math.sqrt(count * max(variance, 1e-9)) / tsqrt


def _search(
    frame: bytes,
    width: int,
    height: int,
    zero: list[float],
    side: int,
    tsqrt: float,
    centre_x: float,
    centre_y: float,
    radius: int,
    step: int,
) -> tuple[float, int, int]:
    """Best score and window origin on a clamped grid of `step` around the last centre."""
    base_x = round(centre_x) - side // 2
    base_y = round(centre_y) - side // 2
    best = (-2.0, max(0, min(width - side, base_x)), max(0, min(height - side, base_y)))
    for dy in range(-radius, radius + 1, step):
        for dx in range(-radius, radius + 1, step):
            x0 = max(0, min(width - side, base_x + dx))
            y0 = max(0, min(height - side, base_y + dy))
            score = _ncc(frame, width, x0, y0, zero, side, tsqrt)
            if score > best[0]:
                best = (score, x0, y0)
    return best


def _match(
    frame: bytes,
    width: int,
    height: int,
    zero: list[float],
    side: int,
    tsqrt: float,
    centre_x: float,
    centre_y: float,
    radius: int,
) -> tuple[float, int, int]:
    """Sweep the search square two pixels at a time, then refine the winner pixel by pixel."""
    score, x0, y0 = _search(frame, width, height, zero, side, tsqrt, centre_x, centre_y, radius, 2)
    fine = _search(frame, width, height, zero, side, tsqrt, x0 + side / 2, y0 + side / 2, 2, 1)
    return (score, x0, y0) if fine[0] <= score else fine


SCALES = (0.85, 0.92, 1.0, 1.09, 1.18)
SCALE_RADIUS = 4
GAP_LIMIT = 30
MIN_SCORE = 0.35
RELAX = 0.8


def track_box(
    frames: list[bytes],
    width: int,
    box: tuple[float, float, float, float],
    search: int,
    scale: bool = True,
    max_gap: int = GAP_LIMIT,
    min_score: float = MIN_SCORE,
) -> dict:
    """Follow one box: translation, optional scale, and a constant-velocity glide through occlusion.

    A frame is accepted when its best window correlates with the frame-0 template at least `RELAX`
    of the confidence the last few frames reached, and never below `min_score`. Below that the
    centre is extrapolated and marked; a gap open when the media ends is dropped and reported as
    `lost_at`, because gliding past the last sighting would be a guess the editor cannot check.
    """
    height = len(frames[0]) // width
    cx = box[0] * width
    cy = box[1] * height
    half = max(4, min(round(box[2] * width / 2), round(box[3] * height / 2), 48))
    side0 = min(_template_side(half), width - 2, height - 2)
    _, _, anchor = _crop(frames[0], width, round(cx), round(cy), side0)
    templates: dict[int, tuple[list[float], float]] = {}

    def probe_template(probe: int) -> tuple[list[float], float]:
        found = templates.get(probe)
        if found is None:
            found = _zeroed(_resample(anchor, side0, probe))
            templates[probe] = found
        return found

    side = side0

    boxes: list[tuple[float, float, float]] = [(cx / width, cy / height, 1.0)]
    scores: list[float] = []
    velocity = (0.0, 0.0)
    predicted: list[int] = []
    gaps: list[tuple[int, int]] = []
    gap_start: int | None = None
    lost_at: int | None = None

    for index, frame in enumerate(frames[1:], start=1):
        glide_x, glide_y = cx + velocity[0], cy + velocity[1]
        hidden = gap_start is not None
        centre_x, centre_y = (glide_x, glide_y) if hidden else (cx, cy)
        zero, tsqrt = probe_template(side)
        score, x0, y0 = _match(
            frame,
            width,
            height,
            zero,
            side,
            tsqrt,
            centre_x,
            centre_y,
            search * 2 if hidden else search,
        )
        best: tuple[float, float, float, int] = (score, x0 + side / 2, y0 + side / 2, side)
        if scale and not hidden:
            # A new size only needs testing near the centre the translation pass settled on.
            for factor in SCALES:
                probe = max(6, min(width - 2, height - 2, round(side * factor)))
                if probe == side:
                    continue
                probe_zero, probe_tsqrt = probe_template(probe)
                sized, sx, sy = _search(
                    frame,
                    width,
                    height,
                    probe_zero,
                    probe,
                    probe_tsqrt,
                    best[1],
                    best[2],
                    SCALE_RADIUS,
                    2,
                )
                if sized > best[0]:
                    best = (sized, sx + probe / 2, sy + probe / 2, probe)
        score, found_x, found_y, probe = best
        floor = min_score
        if len(scores) >= 8:
            floor = max(min_score, min(RELAX * median(scores[-8:]), 0.75))
        if score < floor:
            if gap_start is None:
                gap_start = index
            if index - gap_start >= max_gap:
                break
            cx, cy = glide_x, glide_y
            predicted.append(index)
            boxes.append((cx / width, cy / height, side / side0))
            continue
        if gap_start is not None:
            gaps.append((gap_start, index))
            gap_start = None
        velocity = (
            0.6 * velocity[0] + 0.4 * (found_x - cx),
            0.6 * velocity[1] + 0.4 * (found_y - cy),
        )
        cx, cy = found_x, found_y
        side = probe
        scores.append(score)
        boxes.append((cx / width, cy / height, side / side0))

    if gap_start is not None:
        # The target never came back: stop at the last confident sighting rather than glide on.
        boxes = boxes[:gap_start]
        predicted = [position for position in predicted if position < gap_start]
        lost_at = gap_start
    return {
        "boxes": boxes,
        "predicted": predicted,
        "gaps": gaps,
        "lost_at": lost_at,
        "template_side": side0,
        "analysis_height": height,
    }


def track_mask(
    ffmpeg: Path,
    source: Path,
    source_width: int,
    source_height: int,
    rate: FrameRate,
    box: tuple[float, float, float, float],
    frames: int,
    start_ticks: int,
    frame_ticks: int,
    search: int,
    scale: bool = True,
    max_gap: int = GAP_LIMIT,
) -> dict:
    """Track the mask box for `frames` frames and return mask keyframes in clip-local ticks."""
    duration = frames * frame_ticks / TIMEBASE
    width, height, decoded = decode_luma(
        ffmpeg, source, start_ticks / TIMEBASE, duration, rate, source_width, source_height, frames
    )
    if len(decoded) < 2:
        raise EditorError("TRACK_FAILED", "too few frames to track", 422)
    result = track_box(decoded, width, box, search, scale=scale, max_gap=max_gap)
    points = [
        {
            "at_ticks": index * frame_ticks,
            "mask_x": min(0.999, max(0.001, centre[0])),
            "mask_y": min(0.999, max(0.001, centre[1])),
            "width": min(2.0, max(0.01, box[2] * centre[2])),
            "height": min(2.0, max(0.01, box[3] * centre[2])),
        }
        for index, centre in enumerate(result["boxes"])
    ]
    return {
        "analysis_width": width,
        "analysis_height": height,
        "sampled_frames": len(decoded),
        "tracked_frames": len(points),
        "predicted_frames": len(result["predicted"]),
        "gaps": [
            {"from_ticks": start * frame_ticks, "to_ticks": end * frame_ticks}
            for start, end in result["gaps"]
        ],
        "scale": scale,
        "frame_ticks": frame_ticks,
        "lost_at_ticks": None if result["lost_at"] is None else result["lost_at"] * frame_ticks,
        "points": points,
    }
