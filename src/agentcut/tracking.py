"""Mask tracking by normalized cross-correlation on a downscaled luma plane: stdlib and FFmpeg only.

The tracker follows one box by translation and scale, matched against the template cut from frame 0.
Correlation replaces the pixel difference because a difference always prefers the window whose area
equals the template: it cannot tell a target that has grown from one that has left. Normalized
correlation measures shape, so the box can follow a target walking toward the camera, which a
difference metric cannot do. While the target is hidden its centre is predicted from recent motion,
and every frame of that window is also searched again over the whole picture on a quarter-size copy,
so a target that comes back somewhere else — or after a long occlusion — is re-found rather than
guessed past. When a sighting ends such a window the guesses are re-anchored to it, and the shift
they needed is reported. What comes back are ordinary mask keyframes, so `apply_edits` stays the
only writer of project state. Decoding and following are two calls (`analyse_window`,
`follow_window`) so a group of targets that share a window shares one pass over the media while each
still gets its own path.
"""

import math
from operator import mul
from pathlib import Path
from statistics import median
from subprocess import Popen

from .contracts import (
    TIMEBASE,
    TRACK_GAP_DEFAULT,
    TRACK_REAQUIRE_SCALE,
    EditorError,
    FrameRate,
)
from .speed import analysis_rate

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
    speed_percent: int = 100,
) -> tuple[int, int, list[bytes]]:
    """Decode at most `limit` frames as gray bitmaps, never wider than the analysis width.

    `speed_percent` is how fast the clip plays: the samples are pulled at `rate / speed`, so sample
    `i` is the frame the timeline shows at its `i`-th frame rather than the `i`-th frame of the
    source. The window read from the file grows by the same factor, because a sped-up clip spends
    more source than it spends timeline.
    """
    width = _plan_width(source_width)
    height = max(2, round(source_height * width / source_width / 2) * 2)
    sample_num, sample_den = analysis_rate(rate, speed_percent)
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
        f"{duration_seconds * speed_percent / 100:.6f}",
        "-vf",
        f"fps={sample_num}/{sample_den},scale={width}:{height}:flags=area,format=gray",
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
GAP_LIMIT = TRACK_GAP_DEFAULT
MIN_SCORE = 0.35
RELAX = 0.8
REAQUIRE_SCALE = TRACK_REAQUIRE_SCALE
# The arithmetic that makes a whole-frame sweep affordable. With the gate's 34x34 template on a
# 256x144 analysis picture, scanning every window is (256-34+1)x(144-34+1) = 223x111 windows of
# 1156 pixels = 28.6M pixel multiplies; on the quarter-size picture it is (64-8+1)x(36-8+1) =
# 57x29 windows of 64 pixels = 0.11M — 270 times less work, and it only runs on hidden frames.


def _shrink(frame: bytes, width: int, height: int, factor: int) -> tuple[int, int, bytes]:
    """Box-average a bitmap down by an integer factor, so a coarse sweep sees whole regions."""
    out_width, out_height = max(1, width // factor), max(1, height // factor)
    out = bytearray(out_width * out_height)
    area = factor * factor
    for y in range(out_height):
        base = y * out_width
        origin = y * factor * width
        for x in range(out_width):
            left = origin + x * factor
            total = sum(
                sum(frame[row + left : row + left + factor])
                for row in range(0, factor * width, width)
            )
            out[base + x] = total // area
    return out_width, out_height, bytes(out)


def _sweep(
    frame: bytes, width: int, height: int, zero: list[float], side: int, tsqrt: float
) -> tuple[float, int, int]:
    """Best score and window origin over *every* position, for re-finding a target that is not where
    the motion model expects it."""
    best = (-2.0, 0, 0)
    for y0 in range(height - side + 1):
        for x0 in range(width - side + 1):
            score = _ncc(frame, width, x0, y0, zero, side, tsqrt)
            if score > best[0]:
                best = (score, x0, y0)
    return best


def track_box(
    frames: list[bytes],
    width: int,
    box: tuple[float, float, float, float],
    search: int,
    scale: bool = True,
    max_gap: int = GAP_LIMIT,
    min_score: float = MIN_SCORE,
    reacquire: bool = True,
) -> dict:
    """Follow one box: translation, optional scale, a constant-velocity glide through occlusion,
    and a whole-picture search that looks for the target again while it is hidden.

    A frame is accepted when its best window correlates with the frame-0 template at least `RELAX`
    of the confidence the last few frames reached, and never below `min_score`. Below that the
    centre is extrapolated and marked, and — when `reacquire` is on — every hidden frame is also
    swept at a quarter size and the winner is re-scored at full resolution, so a target that comes
    back anywhere in the picture ends the gap on a real sighting rather than on a guess. The guesses
    inside a closed gap are then shifted so the window lands on that sighting; how far the largest
    one had to move is reported as `closure`. A gap still open when the media ends is dropped and
    reported as `lost_at`, because gliding past the last sighting would be a guess the editor cannot
    check.
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

    # The sweep runs on a fixed-size copy, so the template it needs is decided once here: the anchor
    # shrunk by the same factor, clamped to fit the copy so `_sweep` never slices a template wider
    # than the patch it was zeroed from.
    sweep_w, sweep_h = max(1, width // REAQUIRE_SCALE), max(1, height // REAQUIRE_SCALE)
    coarse_side = min(sweep_w - 1, sweep_h - 1, max(1, side0 // REAQUIRE_SCALE))
    coarse: tuple[list[float], float] | None = None

    def coarse_template() -> tuple[list[float], float]:
        """The frame-0 anchor shrunk the same way the picture is, kept as a sweep template."""
        nonlocal coarse
        if coarse is None:
            shrunk_side, _, patch = _shrink(anchor, side0, side0, REAQUIRE_SCALE)
            zero, energy = _zeroed(_resample(patch, shrunk_side, coarse_side))
            coarse = (zero, energy)
        return coarse

    def locate(
        frame: bytes, centre_x: float, centre_y: float, radius: int, sized: bool, side: int
    ) -> tuple[float, float, float, int]:
        """Score the best window near a centre, testing the scale probes around it when allowed."""
        zero, tsqrt = probe_template(side)
        score, x0, y0 = _match(frame, width, height, zero, side, tsqrt, centre_x, centre_y, radius)
        best = (score, x0 + side / 2, y0 + side / 2, side)
        if sized:
            # A new size only needs testing near the centre the translation pass settled on.
            for factor in SCALES:
                probe = max(6, min(width - 2, height - 2, round(side * factor)))
                if probe == side:
                    continue
                probe_zero, probe_tsqrt = probe_template(probe)
                sized_score, sx, sy = _search(
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
                if sized_score > best[0]:
                    best = (sized_score, sx + probe / 2, sy + probe / 2, probe)
        return best

    side = side0

    boxes: list[tuple[float, float, float]] = [(cx / width, cy / height, 1.0)]
    scores: list[float] = []
    velocity = (0.0, 0.0)
    predicted: list[int] = []
    gaps: list[tuple[int, int]] = []
    reacquired: list[int] = []
    gap_start: int | None = None
    lost_at: int | None = None
    closure = 0.0

    for index, frame in enumerate(frames[1:], start=1):
        glide_x, glide_y = cx + velocity[0], cy + velocity[1]
        hidden = gap_start is not None
        centre_x, centre_y = (glide_x, glide_y) if hidden else (cx, cy)
        best = locate(
            frame,
            centre_x,
            centre_y,
            search * 2 if hidden else search,
            scale and not hidden,
            side,
        )
        floor = min_score
        if len(scores) >= 8:
            floor = max(min_score, min(RELAX * median(scores[-8:]), 0.75))
        jumped = False
        if best[0] < floor and hidden and reacquire and coarse_side >= 3:
            # The target is not where the motion model left it: look for it in the whole picture.
            probe_zero, probe_tsqrt = coarse_template()
            _, _, small = _shrink(frame, width, height, REAQUIRE_SCALE)
            _, origin_x, origin_y = _sweep(
                small, sweep_w, sweep_h, probe_zero, coarse_side, probe_tsqrt
            )
            candidate = locate(
                frame,
                (origin_x + coarse_side / 2) * REAQUIRE_SCALE,
                (origin_y + coarse_side / 2) * REAQUIRE_SCALE,
                max(search, 2 * REAQUIRE_SCALE),
                scale,
                side,
            )
            if candidate[0] >= floor:
                best = candidate
                jumped = True
        score, found_x, found_y, probe = best
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
        velocity = (
            0.6 * velocity[0] + 0.4 * (found_x - cx),
            0.6 * velocity[1] + 0.4 * (found_y - cy),
        )
        if jumped:
            # A re-acquired target may have moved by more than the glide can carry: start fresh.
            velocity = (0.0, 0.0)
            reacquired.append(index)
        cx, cy = found_x, found_y
        side = probe
        scores.append(score)
        boxes.append((cx / width, cy / height, side / side0))
        if gap_start is not None:
            # Land the guessed window on the sighting that ended it, spread evenly across the gap.
            target = boxes[index]
            span = index - gap_start + 1
            for offset in range(gap_start, index):
                share = (offset - gap_start + 1) / span
                before = boxes[offset]
                boxes[offset] = tuple(
                    before[axis] + share * (target[axis] - before[axis]) for axis in range(3)
                )
                closure = max(
                    closure,
                    share * abs(target[0] - before[0]),
                    share * abs(target[1] - before[1]),
                )
            gap_start = None

    if gap_start is not None:
        # The target never came back: stop at the last confident sighting rather than glide on.
        boxes = boxes[:gap_start]
        predicted = [position for position in predicted if position < gap_start]
        lost_at = gap_start
    return {
        "boxes": boxes,
        "predicted": predicted,
        "gaps": gaps,
        "reacquired": reacquired,
        "closure": closure,
        "lost_at": lost_at,
        "template_side": side0,
        "analysis_height": height,
    }


def analyse_window(
    ffmpeg: Path,
    source: Path,
    source_width: int,
    source_height: int,
    rate: FrameRate,
    start_ticks: int,
    frame_ticks: int,
    frames: int,
    speed_percent: int = 100,
) -> tuple[int, list[bytes]]:
    """Decode the samples one tracking run reads, at the analysis width and the clip's own rate.

    Decoding is the expensive half of a run, so it is a call of its own: a group of targets that ask
    for the same window of the same file asks for it once, which is what makes following three
    subjects in one shot cost one pass over the media rather than three.
    """
    duration = frames * frame_ticks / TIMEBASE
    width, height, decoded = decode_luma(
        ffmpeg,
        source,
        start_ticks / TIMEBASE,
        duration,
        rate,
        source_width,
        source_height,
        frames,
        speed_percent,
    )
    if len(decoded) < 2:
        raise EditorError("TRACK_FAILED", "too few frames to track", 422)
    return width, decoded


def follow_window(
    decoded: list[bytes],
    width: int,
    box: tuple[float, float, float, float],
    search: int,
    rate: FrameRate,
    frame_ticks: int,
    scale: bool = True,
    max_gap: int = GAP_LIMIT,
    reacquire: bool = True,
    speed_percent: int = 100,
) -> dict:
    """Follow one box through frames somebody else decoded, in clip-local ticks.

    Every target runs its own correlation pass over the shared samples, which is why the two calls
    are separate: the pictures are the same, the boxes — and therefore the answers — are not.
    """
    height = len(decoded[0]) // width
    sample_num, sample_den = analysis_rate(rate, speed_percent)
    result = track_box(
        decoded, width, box, search, scale=scale, max_gap=max_gap, reacquire=reacquire
    )
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
        "reacquire": reacquire,
        "reacquired_frames": len(result["reacquired"]),
        "reacquired_at": [position * frame_ticks for position in result["reacquired"]],
        "gap_closure": round(result["closure"], 6),
        "gaps": [
            {"from_ticks": start * frame_ticks, "to_ticks": end * frame_ticks}
            for start, end in result["gaps"]
        ],
        "scale": scale,
        "frame_ticks": frame_ticks,
        "speed_percent": speed_percent,
        "sample_rate": f"{sample_num}/{sample_den}",
        "lost_at_ticks": None if result["lost_at"] is None else result["lost_at"] * frame_ticks,
        "points": points,
    }
