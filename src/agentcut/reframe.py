"""Subject-follow reframe: read the mask path a track already produced, and write the layer motion
that keeps that subject centred.

A 16:9 shot survives a 9:16 export only if the subject is where the crop looks. 剪映 solves this by
panning and zooming automatically; doing it by hand means keyframing `x`, `y` and `scale` against a
path the tracker already knows. This module turns one into the other and says out loud when the
framing cannot follow (a full-frame layer that slides half a frame wide exposes an edge, so the
follow needs zoom — and zoom has a ceiling).
"""

from math import isfinite

from .contracts import EditorError, Keyframe, Project

# The compositor scales the layer about the frame centre and then places it at
# `(W-w)/2 + W*x`, so a subject at `cx` lands at `0.5 + scale*(cx-0.5) + x`. Centring it takes
# `x = scale*(0.5-cx)`, and the zoomed layer still covers the picture while `|x| <= (scale-1)/2`,
# i.e. `scale >= 1/(1-2|0.5-cx|)`. Measured against real exports, not inferred from the docs.
MAX_SCALE_LIMIT = 4.0


def _centre_at(keyframes, at_ticks):
    """The one centre both curves agree on at this tick, or None if they disagree."""
    found = {point.at_ticks: point.value for point in keyframes if point.at_ticks == at_ticks}
    return found


def plan(
    project: Project,
    *,
    clip_id: str,
    max_scale: float = 2.0,
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
    if not 1.0 <= max_scale <= MAX_SCALE_LIMIT or not isfinite(max_scale):
        raise EditorError(
            "INVALID_REFRAME",
            f"max_scale has to sit between 1 and {MAX_SCALE_LIMIT}",
            422,
            clip_id=clip_id,
            max_scale=max_scale,
        )
    mask = clip.mask
    if mask is None or mask.shape == "path" or mask.inverted:
        raise EditorError(
            "INVALID_REFRAME",
            "reframing follows a rectangle or ellipse mask, not a path mask or an inverted one",
            422,
            clip_id=clip_id,
        )
    centres_x = [point for point in clip.keyframes if point.property == "mask_x"]
    centres_y = [point for point in clip.keyframes if point.property == "mask_y"]
    if not centres_x or not centres_y:
        raise EditorError(
            "INVALID_REFRAME",
            "the mask has no animated centre to follow: draw a rectangle or ellipse over the "
            "subject and press 跟踪主体 first, or keyframe 遮罩中心 yourself",
            422,
            clip_id=clip_id,
            keyframes_x=len(centres_x),
            keyframes_y=len(centres_y),
        )
    ticks = sorted(
        {point.at_ticks for point in centres_x} | {point.at_ticks for point in centres_y}
    )
    missing = [
        at for at in ticks if _centre_at(centres_x, at) is None or _centre_at(centres_y, at) is None
    ]
    if missing:
        raise EditorError(
            "INVALID_REFRAME",
            "the mask's horizontal and vertical centre curves have to keyframe together; "
            f"{len(missing)} tick(s) carry only one of them (first: {missing[0]})",
            422,
            clip_id=clip_id,
        )

    by_x = {point.at_ticks: point for point in centres_x}
    by_y = {point.at_ticks: point for point in centres_y}
    wanted: list[tuple[int, float, float, str]] = []
    for at in ticks:
        source_x = by_x[at]
        source_y = by_y[at]
        if source_x.interpolation != source_y.interpolation:
            raise EditorError(
                "INVALID_REFRAME",
                f"the two centre curves disagree at tick {at}: "
                f"{source_x.interpolation} horizontally, {source_y.interpolation} vertically",
                422,
                clip_id=clip_id,
            )
        wanted.append((at, 0.5 - source_x.value, 0.5 - source_y.value, source_x.interpolation))

    def clamp(offset: float, room: float) -> tuple[float, bool]:
        limit = max(0.0, room)
        if abs(offset) <= limit + 1e-12:
            return offset, False
        return (limit if offset > 0 else -limit), True

    def distance(centre: float) -> float:
        return abs(0.5 - centre)

    xs: list[Keyframe] = []
    ys: list[Keyframe] = []
    scales: list[Keyframe] = []
    clamped = 0
    reached = 1.0
    for at, offset_x, offset_y, interpolation in wanted:
        need = 1.0
        for offset in (offset_x, offset_y):
            d = abs(offset)
            need = MAX_SCALE_LIMIT if d >= 0.5 else max(need, 1.0 / (1.0 - 2.0 * d))
        scale = min(need, max_scale)
        # Centring at this zoom moves the layer by `scale * d`, and the layer still covers the
        # picture only while that stays within `(scale - 1) / 2` of a frame.
        room = (scale - 1.0) / 2.0
        moved_x, cut_x = clamp(scale * offset_x, room)
        moved_y, cut_y = clamp(scale * offset_y, room)
        clamped += cut_x or cut_y
        reached = max(reached, scale)
        xs.append(
            Keyframe(
                property="x", at_ticks=at, value=round(moved_x, 6), interpolation=interpolation
            )
        )
        ys.append(
            Keyframe(
                property="y", at_ticks=at, value=round(moved_y, 6), interpolation=interpolation
            )
        )
        scales.append(
            Keyframe(
                property="scale", at_ticks=at, value=round(scale, 6), interpolation=interpolation
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
    notes = {
        "followed_points": len(ticks),
        "first_centre": [by_x[ticks[0]].value, by_y[ticks[0]].value],
        "last_centre": [by_x[ticks[-1]].value, by_y[ticks[-1]].value],
        "max_offset": round(max(max(abs(p.value) for p in xs), max(abs(p.value) for p in ys)), 6),
        "max_scale": round(reached, 6),
        "requested_max_scale": max_scale,
        "clamped_points": clamped,
        "ticks": [ticks[0], ticks[-1]],
    }
    if clamped:
        notes["warning"] = (
            f"{clamped} of {len(ticks)} points could not stay centred inside {max_scale:g}x zoom: "
            "the framing follows as far as the picture allows and stops there, so the subject "
            "drifts a little at the extremes."
        )
    return commands, notes
