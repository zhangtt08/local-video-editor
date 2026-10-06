"""Automatic ducking: where the driver is talking, the bed steps back.

The listening side reuses `silence.analyse`, so a duck boundary is exactly the boundary the
"去空白" button would cut on — one detector, one answer. What this module adds is only the maths
that turns "these spans are loud" into ordinary `gain` keyframes on the clips that must step back.
The rendering expression and the browser's animation plan already follow those keyframes, so the
duck needs no second implementation anywhere, and the reducer stays the only place that edits a
timeline.
"""

from .contracts import TIMEBASE, EditorError

# A breakpoint this close to the polyline it simplifies is invisible: 0.1 % of gain is about
# 0.009 dB, far below what the audio path can carry. The duck's own defaults live on
# `DuckRequest`, so the contract stays the single place that states them.
SIMPLIFY_TOLERANCE = 0.001


def depth_gain(depth_db: float) -> float:
    """Amplitude multiplier for a pull-down in dB: -6 dB is half the voltage, not a tenth."""
    return 10.0 ** (-depth_db / 20.0)


def ramp_ticks(milliseconds: float, frame_ticks: int) -> int:
    """Round a ramp onto whole frames, so the attack never lands between two rendered frames."""
    if milliseconds <= 0:
        return 0
    return max(frame_ticks, int(round(milliseconds * TIMEBASE / 1000)))


def loud_spans(clip, gaps) -> list[tuple[int, int]]:
    """The complement of the quiet spans inside one clip, in clip-local ticks.

    Silence detection answers "where is it quiet"; a duck wants the opposite. Taking the
    complement here keeps the two readings of one scan from drifting apart, and a clip that is
    quiet end to end yields no span at all — nothing to duck for.
    """
    spans: list[tuple[int, int]] = []
    cursor = 0
    for gap in sorted(gaps, key=lambda item: item["from_ticks"]):
        start = max(0, min(int(gap["from_ticks"]), clip.duration_ticks))
        stop = max(0, min(int(gap["to_ticks"]), clip.duration_ticks))
        if start > cursor:
            spans.append((cursor, start))
        cursor = max(cursor, stop)
    if cursor < clip.duration_ticks:
        spans.append((cursor, clip.duration_ticks))
    return spans


def _factor(
    at: int, span: tuple[int, int], low: float, attack: int, hold: int, release: int
) -> float:
    """One trapezoid: down over `attack`, hold through the utterance, back up over `release`."""
    start, stop = span
    if at <= start or at >= stop + hold + release:
        return 1.0
    if attack and at < start + attack:
        return 1.0 + (low - 1.0) * (at - start) / attack
    if at <= stop + hold:
        return low
    return low + (1.0 - low) * (at - stop - hold) / release


def envelope(
    spans: list[tuple[int, int]],
    duration_ticks: int,
    frame_ticks: int,
    *,
    low: float,
    attack_ticks: int,
    hold_ticks: int,
    release_ticks: int,
    tolerance: float = SIMPLIFY_TOLERANCE,
) -> list[tuple[int, float]]:
    """Sample the deepest duck wanted at each frame, then return the breakpoints of that curve.

    Sampling on the frame grid matters: `volume` is evaluated once per frame, so a polyline through
    frame times reproduces the intended gain exactly where it is ever read. Between those times the
    browser's plan and FFmpeg both interpolate linearly, which is what the simplification assumes.
    Where two utterances overlap the deeper one wins, as a real ducking compressor does.
    """
    if not spans or duration_ticks <= 0:
        return []
    frames = max(1, int(round(duration_ticks / frame_ticks)))
    sampled = []
    for index in range(frames + 1):
        at = min(duration_ticks, round(index * duration_ticks / frames))
        value = min(
            _factor(at, span, low, attack_ticks, hold_ticks, release_ticks) for span in spans
        )
        sampled.append((at, min(1.0, value)))
    return _simplify(sampled, tolerance)


def _deviation(point, start, end) -> float:
    """Vertical distance from `point` to the line through `start` and `end`, in gain units."""
    span = end[0] - start[0]
    if span <= 0:
        return abs(point[1] - start[1])
    along = (point[0] - start[0]) / span
    return abs(point[1] - (start[1] + (end[1] - start[1]) * along))


def _simplify(points: list[tuple[int, float]], tolerance: float) -> list[tuple[int, float]]:
    """Ramer–Douglas–Peucker on the sampled envelope, keeping the first and last breakpoint."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        worst, worst_at = tolerance, -1
        for position in range(first + 1, last):
            distance = _deviation(points[position], points[first], points[last])
            if distance > worst:
                worst, worst_at = distance, position
        if worst_at > first:
            keep[worst_at] = True
            stack.append((first, worst_at))
            stack.append((worst_at, last))
    return [point for point, flag in zip(points, keep) if flag]


def ducked_ticks(points: list[tuple[int, float]]) -> int:
    """How long the bed really sits below full gain, read off the polyline it became."""
    total = 0
    for (start, first), (stop, second) in zip(points, points[1:]):
        if min(first, second) < 1.0:
            total += stop - start
    return total


def plan_clip(clip, points: list[tuple[int, float]], *, property: str = "gain") -> list[dict]:
    """Hand back the single command that puts this envelope on one clip.

    Times go out clip-local, the same way `keyframe.set` reads them, so the reducer owns the
    mapping onto the shared animation clock. Points already stored for the same property are
    replaced: running the duck again is how you change your mind about the depth, not how you
    stack two envelopes on one clip.
    """
    if not points:
        return []
    keyframes = [
        {
            "property": property,
            "at_ticks": int(at),
            "value": round(value, 6),
            "interpolation": "linear",
        }
        for at, value in points
    ]
    times = [item["at_ticks"] for item in keyframes]
    if any(right <= left for left, right in zip(times, times[1:])):
        raise EditorError("DUCK_PLAN_INVALID", "the envelope times must increase", 500)
    return [
        {
            "op": "keyframes.replace",
            "clip_id": clip.id,
            "property": property,
            "keyframes": keyframes,
        }
    ]
