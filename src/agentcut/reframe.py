"""Subject-follow reframe: read the mask path a track already produced, and write the layer motion
that keeps that subject centred.

A 16:9 shot survives a 9:16 export only if the subject is where the crop looks. 剪映 solves this by
panning and zooming automatically; doing it by hand means keyframing `x`, `y` and `scale` against a
path the tracker already knows. This module turns one into the other and says out loud when the
framing cannot follow (a full-frame layer that slides half a frame wide exposes an edge, so the
follow needs zoom — and zoom has a ceiling).

The follow is sampled, not copied. The zoom a centre offset demands is hyperbolic, `1/(1-2·d)`, so
two of the mask's own keyframes joined by a straight line overshoot badly in the middle — measured
at 0.22 of a frame width on a two-point tail. Segments are refined until the framing the
renderer would actually produce is inside the requested tolerance of the best the ceiling allows.
"""

from math import isfinite

from .animation import sample
from .contracts import REFRAME_TOLERANCE, Clip, EditorError, Keyframe, Project

# The compositor scales the layer about the frame centre and then places it at
# `(W-w)/2 + W*x`, so a subject at `cx` lands at `0.5 + scale*(cx-0.5) + x`. Centring it takes
# `x = scale*(0.5-cx)`, and the zoomed layer still covers the picture while `|x| <= (scale-1)/2`,
# i.e. `scale >= 1/(1-2|0.5-cx|)`. Measured against real exports, not inferred from the docs.
MAX_SCALE_LIMIT = 4.0
MAX_POINTS = 48
PROBES = 8
# Read off the contract, so the planner can never promise a write the clip has no room for.
KEYFRAME_LIMIT = next(
    int(rule.max_length)
    for rule in Clip.model_fields["keyframes"].metadata
    if getattr(rule, "max_length", None)
)


def _framing(
    centre_x: float, centre_y: float, max_scale: float
) -> tuple[float, float, float, bool]:
    offset_x = 0.5 - centre_x
    offset_y = 0.5 - centre_y
    need = 1.0
    for offset in (offset_x, offset_y):
        distance = abs(offset)
        need = MAX_SCALE_LIMIT if distance >= 0.5 else max(need, 1.0 / (1.0 - 2.0 * distance))
    scale = min(need, max_scale)
    # Centring at this zoom moves the layer by `scale * d`, and the layer still covers the picture
    # only while that stays within `(scale - 1) / 2` of a frame.
    room = max(0.0, (scale - 1.0) / 2.0)

    def limit(offset: float) -> tuple[float, bool]:
        if abs(scale * offset) <= room + 1e-12:
            return scale * offset, False
        return (room if offset > 0 else -room), True

    moved_x, cut_x = limit(offset_x)
    moved_y, cut_y = limit(offset_y)
    return moved_x, moved_y, scale, cut_x or cut_y


def _landed(moved_x: float, scale: float, centre_x: float) -> float:
    """Where the subject ends up, signed, measured from the middle of the frame."""
    return moved_x + scale * (centre_x - 0.5)


def plan(
    project: Project,
    *,
    clip_id: str,
    max_scale: float = 2.0,
    tolerance: float = REFRAME_TOLERANCE,
) -> tuple[list[dict], dict]:
    """Return the commands that reframe one clip, and the numbers behind the decision."""
    clip = project.clips.get(clip_id)
    if clip is None:
        raise EditorError("NOT_FOUND", "clip does not exist", 404, clip_id=clip_id)
    asset = project.assets.get(clip.asset_id)
    if asset is None or asset.kind != "video":
        raise EditorError(
            "INVALID_REFRAME", "only a video clip can be reframed", 422, clip_id=clip_id
        )
    if clip.speed_curve:
        raise EditorError(
            "INVALID_REFRAME",
            "a clip with a speed curve cannot be reframed yet: the tracked path is measured on "
            "source time, and this clip plays it at a changing rate",
            422,
            clip_id=clip_id,
        )
    if clip.stabilization is not None:
        raise EditorError(
            "STABILIZE_LOCKED",
            "this clip is stabilised: the follow writes the same `x`/`y`/`scale` curves the "
            "correction lives in, and it writes them absolutely, so running it would delete the "
            "stabilisation while the clip still claimed to carry one. Take the stabilisation off "
            "first (stabilize at strength 0, or `clip.stabilize_record` with no record), then "
            "reframe.",
            422,
            clip_id=clip_id,
        )
    if not 1.0 <= max_scale <= MAX_SCALE_LIMIT or not isfinite(max_scale):
        raise EditorError(
            "INVALID_REFRAME",
            f"max_scale has to sit between 1 and {MAX_SCALE_LIMIT}",
            422,
            clip_id=clip_id,
            max_scale=max_scale,
        )
    mask = clip.mask
    if mask is None or mask.inverted:
        raise EditorError(
            "INVALID_REFRAME",
            "reframing follows a mask centre, and an inverted mask has no subject to follow",
            422,
            clip_id=clip_id,
        )
    keyed = [point for point in clip.keyframes if point.property in {"mask_x", "mask_y"}]
    if not keyed:
        raise EditorError(
            "INVALID_REFRAME",
            "the mask has no animated centre to follow: draw a mask over the subject and press "
            "跟踪主体 first, or keyframe 遮罩中心 yourself",
            422,
            clip_id=clip_id,
        )

    # Mask keyframes live on the clip's absolute animation clock, while `keyframes.replace` takes
    # clip-local ticks and adds `animation_offset_ticks` back. A split leaves the head's keyframes
    # on the tail as well, so only the visible window is followed, and it is followed through the
    # sampler the render itself uses so that the two can never disagree.
    offset = clip.animation_offset_ticks
    window_end = offset + clip.duration_ticks
    ticks = sorted({point.at_ticks for point in keyed})
    nodes: list[list] = []

    def add(at: int) -> list:
        local = at - offset
        centre_x = sample(clip, "mask_x", local)
        centre_y = sample(clip, "mask_y", local)
        moved_x, moved_y, scale, cut = _framing(centre_x, centre_y, max_scale)
        node = [at, moved_x, moved_y, scale, cut, centre_x, centre_y]
        nodes.append(node)
        return node

    seeds = [item for item in ticks if offset <= item <= window_end]
    if not seeds or seeds[0] > offset:
        # The path was already moving when this clip began, so the framing it had at the cut has to
        # be carried; otherwise the head of the clip slides off the subject.
        seeds.insert(0, offset)
    # A real track writes a mask keyframe per frame, and one clip cannot carry more keyframes than
    # the contract allows: three follow curves have to fit beside everything the clip already holds.
    # So the path is sampled to the budget the clip has room for, then refined inside it.
    room = (KEYFRAME_LIMIT - len(clip.keyframes)) // 3
    ceiling = max(2, min(MAX_POINTS, room))
    decimated = 0
    if len(seeds) > ceiling:
        positions = {round(index * (len(seeds) - 1) / (ceiling - 1)) for index in range(ceiling)}
        kept = [item for index, item in enumerate(seeds) if index in positions]
        decimated = len(seeds) - len(kept)
        seeds = kept
    for at in seeds:
        add(at)

    stepped = {point.at_ticks for point in keyed if point.interpolation == "hold"}
    refined = 0

    def drawn(left: list, right: list, at: int) -> tuple[float, float, float]:
        """The layer values the render clock will actually produce at `at` between two keyframes."""
        if left[0] in stepped:
            # A stepped follow holds the framing it reached, exactly as a stepped mask does.
            return left[1], left[2], left[3]
        mix = (at - left[0]) / (right[0] - left[0])
        return (
            left[1] + (right[1] - left[1]) * mix,
            left[2] + (right[2] - left[2]) * mix,
            left[3] + (right[3] - left[3]) * mix,
        )

    def segment_error(left: list, right: list) -> float:
        """The most this segment costs, anywhere along it, over the best the ceiling allows."""
        if right[0] - left[0] < 2:
            return 0.0
        worst = 0.0
        for index in range(1, PROBES):
            at = round(left[0] + (right[0] - left[0]) * index / PROBES)
            if not left[0] < at < right[0]:
                continue
            local = at - offset
            centre_x = sample(clip, "mask_x", local)
            centre_y = sample(clip, "mask_y", local)
            ideal_x, ideal_y, ideal_scale, _ = _framing(centre_x, centre_y, max_scale)
            drawn_x, drawn_y, drawn_scale = drawn(left, right, at)
            drift_x = _landed(drawn_x, drawn_scale, centre_x) - _landed(
                ideal_x, ideal_scale, centre_x
            )
            drift_y = _landed(drawn_y, drawn_scale, centre_y) - _landed(
                ideal_y, ideal_scale, centre_y
            )
            worst = max(worst, abs(drift_x), abs(drift_y))
        return worst

    while len(nodes) < MAX_POINTS:
        pairs = [pair for pair in zip(nodes, nodes[1:]) if pair[1][0] - pair[0][0] >= 2]
        if not pairs:
            break
        # Spend each new keyframe where it buys the most, rather than halving one branch to death.
        left, right = max(pairs, key=lambda pair: segment_error(pair[0], pair[1]))
        if segment_error(left, right) <= tolerance:
            break
        add((left[0] + right[0]) // 2)
        nodes.sort(key=lambda item: item[0])
        refined += 1

    clamped = sum(1 for item in nodes if item[4])
    reached = max([item[3] for item in nodes] + [1.0])

    def drift() -> float:
        """The largest distance from centre the emitted curves leave anywhere in the window."""
        worst = 0.0
        for index, item in enumerate(nodes):
            worst = max(worst, abs(_landed(item[1], item[3], item[5])))
            if index:
                left, right = nodes[index - 1], item
                for step in range(1, PROBES):
                    at = round(left[0] + (right[0] - left[0]) * step / PROBES)
                    if not left[0] < at < right[0]:
                        continue
                    local = at - offset
                    centre_x = sample(clip, "mask_x", local)
                    centre_y = sample(clip, "mask_y", local)
                    drawn_x, drawn_y, scale = drawn(left, right, at)
                    worst = max(
                        worst,
                        abs(_landed(drawn_x, scale, centre_x)),
                        abs(_landed(drawn_y, scale, centre_y)),
                    )
        return worst

    xs: list[Keyframe] = []
    ys: list[Keyframe] = []
    scales: list[Keyframe] = []
    for at, moved_x, moved_y, scale, _cut, centre_x, centre_y in nodes:
        # A stepped path stays stepped: the follow has to hold the value the mask holds, rather
        # than slide to the next one early.
        interpolation = "hold" if at in stepped else "linear"
        xs.append(
            Keyframe(
                property="x",
                at_ticks=at - offset,
                value=round(moved_x, 6),
                interpolation=interpolation,
            )
        )
        ys.append(
            Keyframe(
                property="y",
                at_ticks=at - offset,
                value=round(moved_y, 6),
                interpolation=interpolation,
            )
        )
        scales.append(
            Keyframe(
                property="scale",
                at_ticks=at - offset,
                value=round(scale, 6),
                interpolation=interpolation,
            )
        )

    commands = [
        {
            "op": "keyframes.replace",
            "clip_id": clip.id,
            "property": name,
            "keyframes": [point.model_dump() for point in points],
        }
        for name, points in (("x", xs), ("y", ys), ("scale", scales))
    ]
    worst = drift()
    notes = {
        "followed_points": len(nodes),
        "keyframes_added": refined,
        "keyframes_dropped": decimated,
        "keyframe_budget": ceiling,
        "first_centre": [round(nodes[0][5], 6), round(nodes[0][6], 6)],
        "last_centre": [round(nodes[-1][5], 6), round(nodes[-1][6], 6)],
        "max_offset": round(max(max(abs(i[1]) for i in nodes), max(abs(i[2]) for i in nodes)), 6),
        "max_scale": round(reached, 6),
        "requested_max_scale": max_scale,
        "clamped_points": clamped,
        "tolerance": tolerance,
        "worst_offset": round(worst, 6),
        # The same clip-local clock the emitted commands use.
        "ticks": [nodes[0][0] - offset, nodes[-1][0] - offset],
    }
    if clamped:
        notes["warning"] = (
            f"{clamped} of {len(nodes)} points could not stay centred inside {max_scale:g}x zoom: "
            "the framing follows as far as the picture allows and stops there, so the subject "
            "drifts a little at the extremes."
        )
    if decimated and worst > tolerance:
        # Saying it is the whole point: the path is denser than the clip's keyframe budget, so the
        # follow is sampled evenly and cannot hold as tightly as it was asked to.
        notes["warning"] = ((notes.get("warning", "") + " ") if clamped else "") + (
            f"the tracked path is denser than this clip's {ceiling}-keyframe budget, so {decimated}"
            f" samples were dropped and the subject is held {worst:.3f} wide instead of"
            f" {tolerance:g}: trim the clip, or follow a shorter stretch, for a tighter hold."
        )
    return commands, notes
