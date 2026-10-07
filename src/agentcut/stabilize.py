"""Picture stabilisation: measure how the frame itself moves, and write the inverse as keyframes.

剪映 and Premiere call this Warp Stabilizer; the useful part of the idea is not the warp but the
question "what is the camera doing?". This module asks that with the same normalised-correlation
tracker the mask follow uses, only aimed at four anchors placed on the picture rather than on a
subject, and answers with ordinary `x`/`y`/`scale` keyframes — the ones the renderer and the browser
already agree on, so a stabilised clip previews exactly as it exports.

Four anchors, not one, because a moving subject is the thing an editor least wants to follow: the
median of the anchors' translations is the motion all of them share, which is the camera, while a
subject that walks through one anchor's box only moves that one.

The correction is measured minus smoothed, never measured minus zero. Holding the picture still in
absolute terms would freeze the shot and drift it out of frame; a shot is supposed to move, and what
an editor wants gone is the jitter on top of that motion. So the smooth path stays and the wiggle
comes off, and `strength` is how wide a window decides what counts as smooth.
"""

from math import isfinite
from statistics import median

from .animation import sample
from .contracts import (
    STABILIZE_MAX_CROP_LIMIT,
    STABILIZE_SMOOTHING_FRAMES,
    STABILIZE_STRENGTH_LIMIT,
    TIMEBASE,
    Clip,
    EditorError,
    Keyframe,
    Project,
)
from .tracking import MAX_FRAMES, decode_luma, track_box

# Anchors sit inset from the corners: a template that touches an edge has nowhere to search when the
# frame slides, and the corner of a shot is where a rolling shutter and lens vignetting show up.
ANCHORS = (
    (0.27, 0.27),
    (0.73, 0.27),
    (0.27, 0.73),
    (0.73, 0.73),
)
ANCHOR_SIZE = 0.22
SEARCH_RADIUS = 12
STRENGTH_LIMIT = STABILIZE_STRENGTH_LIMIT
MAX_CROP_LIMIT = STABILIZE_MAX_CROP_LIMIT
# Half-width of the smoothing window, in frames, at full strength: 30 frames at 30fps is a second,
# which is about how long a handheld shot is allowed to wander before it reads as intended motion.
MAX_SMOOTH_RADIUS = STABILIZE_SMOOTHING_FRAMES
# A correction can only remove what the curve can hold: a per-frame jolt needs a keyframe in every
# frame, and a linear segment between two frames half a jolt apart leaves the rest in the picture.
# So the writer spends one point per measured frame while the clip's own budget allows it, and only
# thins the path when the budget runs out.
MAX_POINTS = 240
# The most a clip's own budget allows; read off the contract so the writer cannot promise more.
KEYFRAME_LIMIT = next(
    int(rule.max_length)
    for rule in Clip.model_fields["keyframes"].metadata
    if getattr(rule, "max_length", None)
)


def measure(
    ffmpeg,
    source,
    source_width: int,
    source_height: int,
    rate,
    start_ticks: int,
    duration_ticks: int,
    frame_ticks: int,
) -> dict:
    """Follow four anchors over the clip's own frames and return the camera's translation.

    Offsets are fractions of the frame, relative to the first analysed frame, so the caller can hand
    them straight to the compositor's `x`/`y`. An anchor that loses the picture is dropped rather
    than guessed at, and `anchor_frames` says how many of the four survived to each frame.
    """
    seconds = duration_ticks / TIMEBASE
    frames_wanted = max(3, round(seconds * rate.numerator / rate.denominator))
    width, height, frames = decode_luma(
        ffmpeg,
        source,
        start_ticks / TIMEBASE,
        seconds,
        rate,
        source_width,
        source_height,
        # One frame per rendered frame, capped by the tracker's own frame limit.
        min(MAX_FRAMES, frames_wanted),
    )
    tracks = []
    for centre_x, centre_y in ANCHORS:
        box = (centre_x, centre_y, ANCHOR_SIZE, ANCHOR_SIZE)
        tracks.append(track_box(frames, width, box, SEARCH_RADIUS, scale=False))
    count = min(len(track["boxes"]) for track in tracks)
    if count < 3:
        raise EditorError(
            "STABILIZE_FAILED",
            f"only {count} frame(s) of the clip could be matched against the first one; the source "
            "may be too short, too dark, or cut faster than the tracker can follow",
            422,
            frames=count,
        )
    offsets: list[list[float]] = []
    lost = 0
    for index in range(1, count):
        step_x = []
        step_y = []
        for track in tracks:
            boxes = track["boxes"]
            if len(boxes) <= index or index in track["predicted"]:
                continue
            step_x.append(boxes[index][0] - boxes[0][0])
            step_y.append(boxes[index][1] - boxes[0][1])
        if len(step_x) < 3:
            # Fewer than three anchors agree on where the frame went: this frame is a hole, not a
            # measurement, so the correction interpolates across it instead of trusting a pair.
            lost += 1
            offsets.append(list(offsets[-1]) if offsets else [0.0, 0.0])
            continue
        offsets.append([median(step_x), median(step_y)])
    return {
        "offsets": offsets,
        "analysis_width": width,
        "analysis_height": height,
        "analysed_frames": count,
        "dropped_frames": lost,
        "frame_ticks": frame_ticks,
    }


def _smoothed(offsets: list[list[float]], radius: int) -> list[list[float]]:
    """A centred moving average, shrinking its window at the ends rather than inventing frames."""
    if radius <= 0:
        return [[0.0, 0.0] for _ in offsets]
    smooth = []
    for index in range(len(offsets)):
        left = max(0, index - radius)
        right = min(len(offsets), index + radius + 1)
        window = offsets[left:right]
        smooth.append(
            [
                sum(point[0] for point in window) / len(window),
                sum(point[1] for point in window) / len(window),
            ]
        )
    return smooth


def plan(
    project: Project,
    motion: dict,
    *,
    clip_id: str,
    strength: float = STRENGTH_LIMIT,
    max_crop: float = 0.1,
) -> tuple[list[dict], dict]:
    """Return the commands that hold one clip steady, and the numbers behind the decision.

    The correction is composed onto whatever `x`/`y`/`scale` the clip already animates, so a
    stabilised clip keeps its hand-keyed move rather than losing it to a rewrite.
    """
    clip = project.clips.get(clip_id)
    if clip is None:
        raise EditorError("NOT_FOUND", "clip does not exist", 404, clip_id=clip_id)
    asset = project.assets.get(clip.asset_id)
    if asset is None or asset.kind != "video":
        raise EditorError(
            "STABILIZE_INVALID", "only a video clip can be stabilised", 422, clip_id=clip_id
        )
    if clip.speed_curve:
        raise EditorError(
            "STABILIZE_INVALID",
            "a clip with a speed curve cannot be stabilised yet: the motion is measured on source "
            "time, and this clip plays it at a changing rate",
            422,
            clip_id=clip_id,
        )
    if not 0.0 <= strength <= STRENGTH_LIMIT or not isfinite(strength):
        raise EditorError(
            "STABILIZE_INVALID",
            f"strength has to sit between 0 and {STRENGTH_LIMIT}",
            422,
            clip_id=clip_id,
            strength=strength,
        )
    if not 0.0 <= max_crop <= MAX_CROP_LIMIT or not isfinite(max_crop):
        raise EditorError(
            "STABILIZE_INVALID",
            f"max_crop has to sit between 0 and {MAX_CROP_LIMIT} of the frame",
            422,
            clip_id=clip_id,
            max_crop=max_crop,
        )
    offsets: list[list[float]] = motion["offsets"]
    if len(offsets) < 3:
        raise EditorError(
            "STABILIZE_FAILED", "too few frames measured to stabilise", 422, clip_id=clip_id
        )

    # A window wider than a quarter of the shot cannot tell the camera's jitter from the shot
    # itself: on a two-second clip the 30-frame default would smooth away the pan the operator
    radius = max(1, min(MAX_SMOOTH_RADIUS, len(offsets) // 4))
    smooth = _smoothed(offsets, radius)
    # The compositor scales about the frame centre and then shifts by `x`, so a layer moved by `x`
    # still covers the picture while `|x| <= (scale-1)/2`: the zoom that hides the border is exactly
    # `1 + 2*max|x|`, and `max_crop` is how much of the frame the editor is willing to spend on it.
    ceiling = max_crop
    # `strength` scales how much of the measured jitter is taken out, not how wide the window is:
    # 0 leaves the shot exactly as it was shot, 1 takes all of it out. Scaling the amount keeps the
    # two ends of the slider honest, where widening the window would quietly change what counts as
    # "the camera's intended motion" instead.
    residual = [
        [strength * (a - b) for a, b in zip(point, base)] for point, base in zip(offsets, smooth)
    ]
    clamped = 0
    for point in residual:
        for axis in (0, 1):
            if abs(point[axis]) > ceiling:
                point[axis] = ceiling if point[axis] > 0 else -ceiling
                clamped += 1

    frame_ticks = motion["frame_ticks"]
    if strength == 0.0:
        # Nothing to write: a zero-valued keyframe in every frame is noise in the project, not a
        # gentler correction.
        return [], {
            "smoothing_radius_frames": radius,
            "written_points": 0,
            "keyframe_budget": min(MAX_POINTS, KEYFRAME_LIMIT // 3),
            "measured_travel": [
                round(max(abs(point[0]) for point in offsets), 6),
                round(max(abs(point[1]) for point in offsets), 6),
            ],
            "residual_after": 0.0,
            "zoom_to_hide_borders": 1.0,
            "max_crop": max_crop,
            "clamped_axes": 0,
            "analysed_frames": motion["analysed_frames"],
            "dropped_frames": motion["dropped_frames"],
            "note": "strength 0 leaves the shot exactly as it was filmed; nothing was written",
        }
    budget = min(MAX_POINTS, KEYFRAME_LIMIT // 3)
    # Sampled evenly rather than at every extremum: the residual is smooth by construction, so a
    # uniform pick is what the renderer's linear interpolation between keyframes reproduces best.
    picks = sorted({round(index * (len(residual) - 1) / (budget - 1)) for index in range(budget)})
    worst = max(max(abs(point[0]) for point in residual), max(abs(point[1]) for point in residual))

    commands: list[dict] = []
    written: dict[str, list[Keyframe]] = {}
    for name, axis in (("x", 0), ("y", 1)):
        frames = []
        for index in picks:
            # `offsets` starts at the second analysed frame, so frame `index + 1` of the clip.
            local = min(clip.duration_ticks - 1, frame_ticks * (index + 1))
            current = sample(clip, name, local)
            frames.append(
                Keyframe(
                    property=name,  # type: ignore[arg-type]
                    at_ticks=local,
                    value=round(current - residual[index][axis], 6),
                    interpolation="linear",
                )
            )
        written[name] = frames
    zoom = 1.0 + 2.0 * worst
    written["scale"] = [
        Keyframe(
            property="scale",
            at_ticks=0,
            value=round(sample(clip, "scale", 0) * zoom, 6),
            interpolation="linear",
        ),
        Keyframe(
            property="scale",
            at_ticks=clip.duration_ticks - 1,
            value=round(sample(clip, "scale", clip.duration_ticks - 1) * zoom, 6),
            interpolation="linear",
        ),
    ]
    for name in ("x", "y", "scale"):
        commands.append(
            {
                "op": "keyframes.replace",
                "clip_id": clip.id,
                "property": name,
                "keyframes": [point.model_dump() for point in written[name]],
            }
        )
    notes = {
        "smoothing_radius_frames": radius,
        "written_points": len(picks),
        "keyframe_budget": budget,
        "measured_travel": [
            round(max(abs(point[0]) for point in offsets), 6),
            round(max(abs(point[1]) for point in offsets), 6),
        ],
        "residual_after": round(worst, 6),
        "zoom_to_hide_borders": round(zoom, 6),
        "max_crop": max_crop,
        "clamped_axes": clamped,
        "analysed_frames": motion["analysed_frames"],
        "dropped_frames": motion["dropped_frames"],
    }
    if clamped:
        notes["warning"] = (
            f"{clamped} of {len(residual) * 2} measured axes wanted more than {max_crop:g} of the "
            "frame: the jitter is removed only as far as that crop allows, so some of it stays in "
            "the picture. Raise max_crop, or stabilise a shorter stretch."
        )
    return commands, notes
