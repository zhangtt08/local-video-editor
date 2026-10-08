"""Speed curves: one piecewise-linear rate profile compiled into constant-rate segments.

The same segment list drives the FFmpeg graph and the browser preview, so the exported ramp and what
the editor plays are the same approximation instead of two different ones. Source positions are
cumulative and snapped to the frame or sample clock, so consecutive segments share a boundary: no
source time is skipped or duplicated, and the total is exactly what the timeline validator checks.
"""

import math

MAX_SEGMENTS = 48
MIN_SOURCE_PER_SEGMENT = 2  # frames of source, so a rate stays meaningful after rounding


def _dump(points) -> list[dict]:
    return [{"at_ticks": point.at_ticks, "percent": point.percent} for point in points]


def _rate_at(points, position: int) -> float:
    """Instantaneous relative percent at a timeline offset, linear between points."""
    if position <= points[0]["at_ticks"]:
        return float(points[0]["percent"])
    last = points[-1]
    if position >= last["at_ticks"]:
        return float(last["percent"])
    for left, right in zip(points, points[1:]):
        if position <= right["at_ticks"]:
            span = right["at_ticks"] - left["at_ticks"]
            ratio = (position - left["at_ticks"]) / span
            return left["percent"] + ratio * (right["percent"] - left["percent"])
    return float(last["percent"])


def _consumed(points, base: float, start: int, stop: int) -> float:
    """Source ticks consumed between two timeline offsets: the integral of base * rate / 100."""
    if stop <= start:
        return 0.0
    total = 0.0
    for left, right in zip(points, points[1:]):
        low, high = max(start, left["at_ticks"]), min(stop, right["at_ticks"])
        if high <= low:
            continue
        first = base * _rate_at(points, low) / 100
        second = base * _rate_at(points, high) / 100
        total += (high - low) * (first + second) / 2
    return total


def round_to(value: float, quantum: int) -> int:
    return max(0, round(value / quantum) * quantum)


def base_source_ticks(clip) -> int:
    """The constant-speed source window, matching the pre-curve rule exactly."""
    return (clip.duration_ticks * clip.speed_percent + 99) // 100


def consumed_source_ticks(clip, quantum: int) -> int:
    """Total source duration a clip reads, aligned to the clock it must respect."""
    if not clip.speed_curve:
        aligned = base_source_ticks(clip)
        return (aligned + quantum - 1) // quantum * quantum
    total = _consumed(_dump(clip.speed_curve), clip.speed_percent / 100, 0, clip.duration_ticks)
    return round_to(total, quantum)


def analysis_rate(rate, speed_percent: int) -> tuple[int, int]:
    """The source frame rate an analysis has to sample at, so one analysed frame is one shown frame.

    A clip at 200 % spends two seconds of source on every second of timeline, so pulling the
    sequence rate out of the source would measure frames the viewer never sees and write that curve
    onto the ticks it does. Sampling at `rate / speed` makes the analysis index and the timeline
    index the same frame: the mask path and the stabilisation correction then land on the picture
    they were measured from. A speed curve cannot be reduced to one rate, which is why both features
    still refuse it.
    """
    numbers = (100 * rate.numerator, max(1, rate.denominator * speed_percent))
    shared = math.gcd(*numbers)
    return (numbers[0] // shared, numbers[1] // shared)


def _marks(clip, points, base: float, quantum: int) -> list[int]:
    """Timeline boundaries: clip ends, curve nodes, and the subdivision a steep ramp needs."""
    wanted: list[tuple[int, int, int]] = []
    for left, right in zip(points, points[1:]):
        span = right["at_ticks"] - left["at_ticks"]
        if span <= quantum:
            continue
        swing = abs(right["percent"] - left["percent"]) * base / 100
        source_span = span * (left["percent"] + right["percent"]) * base / 200
        # A segment needs enough source to carry a rate, and little enough curvature to stay flat.
        by_granularity = max(1, int(source_span // (MIN_SOURCE_PER_SEGMENT * quantum)))
        by_accuracy = math.ceil(span * swing / (8 * quantum)) if swing else 1
        wanted.append((left["at_ticks"], span, max(1, min(by_granularity, by_accuracy))))
    used = sum(steps for _, _, steps in wanted)
    marks = {0, clip.duration_ticks}
    for start, span, steps in wanted:
        count = steps if used <= MAX_SEGMENTS else max(1, steps * MAX_SEGMENTS // used)
        for step in range(count + 1):
            marks.add(round_to(start + span * step / count, quantum))
    return sorted(mark for mark in marks if 0 <= mark <= clip.duration_ticks)


def segments(clip, quantum: int, marks_with: int | None = None) -> list[dict]:
    """Constant-rate pieces covering the clip: timeline window, source window, and rate percent.

    `quantum` is the clock the source positions must land on (a frame for picture, a sample for
    sound); `marks_with` is how finely the timeline may be cut, which is the frame clock even for
    sound — otherwise a steep ramp becomes tens of 83 ms pieces whose seams click.
    """
    duration = clip.duration_ticks
    if not clip.speed_curve:
        return [
            {
                "timeline": duration,
                "source": base_source_ticks(clip),
                "rate_percent": clip.speed_percent,
            }
        ]
    points = _dump(clip.speed_curve)
    base = clip.speed_percent / 100
    marks = _marks(clip, points, base, marks_with or quantum)
    if marks[0] != 0:
        marks.insert(0, 0)
    if marks[-1] != duration:
        marks.append(duration)

    positions = [round_to(_consumed(points, base, 0, mark), quantum) for mark in marks]
    for index in range(1, len(positions)):
        positions[index] = max(positions[index], positions[index - 1])
    positions[-1] = max(positions[-1], consumed_source_ticks(clip, quantum))

    pieces: list[dict] = []
    for index in range(len(marks) - 1):
        timeline = marks[index + 1] - marks[index]
        source = positions[index + 1] - positions[index]
        if timeline <= 0:
            continue
        rate = 0 if source <= 0 else max(1, round(source / timeline * 100))
        if pieces and pieces[-1]["rate_percent"] == rate:
            pieces[-1]["timeline"] += timeline
            pieces[-1]["source"] += source
            continue
        piece = {"timeline": timeline, "source": source, "rate_percent": rate}
        if rate == 0:
            # A freeze shows the last frame the window really contains, not one past its end.
            piece["hold"] = max(0, positions[index] - quantum)
        pieces.append(piece)
    return pieces


def describe(pieces: list[dict], timebase: int) -> list[dict]:
    """Seconds-based plan for the browser, in clip-relative time with cumulative offsets."""
    timeline = source = 0
    plan = []
    for piece in pieces:
        plan.append(
            {
                "at": timeline / timebase,
                "duration": piece["timeline"] / timebase,
                "source_at": piece.get("hold", source) / timebase,
                "source_duration": piece["source"] / timebase,
                "rate_percent": piece["rate_percent"],
            }
        )
        timeline += piece["timeline"]
        source += piece["source"]
    return plan


def slice_curve(points, start: int, stop: int) -> list[dict]:
    """Re-base a curve onto a surviving [start, stop] window of the old clip time."""
    if stop <= start:
        return []
    marks = {start, stop}
    for point in points:
        if start < point["at_ticks"] < stop:
            marks.add(point["at_ticks"])
    return [
        {"at_ticks": mark - start, "percent": round(_rate_at(points, mark))}
        for mark in sorted(marks)
    ]


def scale_curve(points, numerator: int, denominator: int) -> list[dict]:
    """Keep the same source consumption when the clip's timeline length changes."""
    if denominator <= 0:
        return []
    return [
        {
            "at_ticks": round(point["at_ticks"] * numerator / denominator),
            "percent": point["percent"],
        }
        for point in points
    ]
