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

from math import atan2, degrees, isfinite, radians
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
# One pixel of anchor quantisation across the ~300 px between anchors is 0.19 degrees; anything the
# roll estimate finds below that is the measurement's own grain, not the camera.
ROLL_DEADBAND_DEGREES = 0.25
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
    rolls: list[float] = []
    lost = 0
    for index in range(1, count):
        step_x = []
        step_y = []
        # Arun's rigid fit: the angle that best carries the four first-frame anchor centres onto the
        # four found this frame, in the picture's own pixel metric. One pair would give the same
        # angle class but with a pixel of quantisation over a ~300 px baseline (0.2 degrees), so the
        # fit averages the four anchors instead of trusting one edge.
        before: list[tuple[float, float]] = []
        after: list[tuple[float, float]] = []
        for track in tracks:
            boxes = track["boxes"]
            if len(boxes) <= index or index in track["predicted"]:
                continue
            step_x.append(boxes[index][0] - boxes[0][0])
            step_y.append(boxes[index][1] - boxes[0][1])
            before.append((boxes[0][0] * width, boxes[0][1] * height))
            after.append((boxes[index][0] * width, boxes[index][1] * height))
        if len(step_x) < 3:
            # Fewer than three anchors agree on where the frame went: this frame is a hole, not a
            # measurement, so the correction interpolates across it instead of trusting a pair.
            lost += 1
            offsets.append(list(offsets[-1]) if offsets else [0.0, 0.0])
            rolls.append(rolls[-1] if rolls else 0.0)
            continue
        offsets.append([median(step_x), median(step_y)])
        rolls.append(_rigid_angle(before, after))
    return {
        "offsets": offsets,
        "rolls": rolls,
        "analysis_width": width,
        "analysis_height": height,
        "analysed_frames": count,
        "dropped_frames": lost,
        "frame_ticks": frame_ticks,
    }


def _rigid_angle(before: list[tuple[float, float]], after: list[tuple[float, float]]) -> float:
    """The rotation (degrees) that best carries `before` onto `after`, centred on their means."""
    n = len(before)
    bx = sum(point[0] for point in before) / n
    by = sum(point[1] for point in before) / n
    ax = sum(point[0] for point in after) / n
    ay = sum(point[1] for point in after) / n
    cross = sum(
        (px - bx) * (qy - ay) - (py - by) * (qx - ax) for (px, py), (qx, qy) in zip(before, after)
    )
    dot = sum(
        (px - bx) * (qx - ax) + (py - by) * (qy - ay) for (px, py), (qx, qy) in zip(before, after)
    )
    return degrees(atan2(cross, dot))


def _smooth_series(values: list[float], radius: int) -> list[float]:
    """The same centred average, for the one series the compositor keeps in degrees."""
    if radius <= 0:
        return [0.0 for _ in values]
    return [
        sum(values[max(0, i - radius) : min(len(values), i + radius + 1)])
        / len(values[max(0, i - radius) : min(len(values), i + radius + 1)])
        for i in range(len(values))
    ]


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

    On a clip with no stabilisation record the correction is composed onto whatever `x`/`y`/
    `rotation`/`scale` the clip already animates, so a stabilised clip keeps its hand-keyed move
    rather than losing it to a rewrite — and a clip that animates them is refused outright, because
    composing a second copy of the same measurement over the first is how the picture ends up
    leaning the other way. On a clip that does carry the record those curves are this feature's own,
    so the run recomputes from the clip's static transform: pressing again at another strength costs
    one click, not an undo.
    """
    clip = project.clips.get(clip_id)
    if clip is None:
        raise EditorError("NOT_FOUND", "clip does not exist", 404, clip_id=clip_id)
    asset = project.assets.get(clip.asset_id)
    if asset is None or asset.kind != "video":
        raise EditorError(
            "STABILIZE_INVALID", "only a video clip can be stabilised", 422, clip_id=clip_id
        )
    keyed = sorted({point.property for point in clip.keyframes} & {"x", "y", "rotation", "scale"})
    if keyed and clip.stabilization is None:
        # The correction is composed onto whatever the clip already animates, so running this twice
        # would subtract the same motion twice and leave the picture leaning the other way. The
        # engine cannot tell its own previous correction from a hand-keyed move — unless this clip
        # carries the record of one, which is the only case where re-running replaces instead.
        raise EditorError(
            "STABILIZE_CONFLICT",
            "this clip already animates "
            + "、".join(keyed)
            + ": the correction is composed onto what is already there, so a second run would "
            "subtract the same camera motion twice and lean the picture the other way. The engine "
            "cannot tell its own previous correction from a hand-keyed move, so clear those "
            "keyframes (or undo / restore the revision from before the first stabilisation) and "
            "run it once.",
            422,
            clip_id=clip_id,
            properties=keyed,
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
    # Whether these four curves belong to the stabiliser decides everything downstream: an owned
    # clip recomputes from its static transform, an unowned one composes onto what it animates.
    owned = clip.stabilization is not None
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
    # The roll is smoothed with the same window and the same strength, so translation and rotation
    # come off at the same rate; a shot that pans while it rolls does not lose one and keep the
    # other.
    rolls = motion.get("rolls", [])
    roll_residual = [
        strength * (roll - base) for roll, base in zip(rolls, _smooth_series(rolls, radius))
    ]
    if strength == 0.0:
        # Nothing to write: a zero-valued keyframe in every frame is noise in the project, not a
        # gentler correction. On a clip the stabiliser already owns this is the affordance for
        # taking the correction off — the curves it wrote go, and the record with them.
        if owned:
            removed = [
                {"property": point.property, "at_ticks": point.at_ticks}
                for point in clip.keyframes
                if point.property in {"x", "y", "rotation", "scale"}
            ]
            commands = (
                [{"op": "keyframes.remove", "clip_id": clip_id, "keyframes": removed}]
                if removed
                else []
            ) + [{"op": "clip.stabilize_record", "clip_id": clip_id, "record": None}]
            return commands, {
                "smoothing_radius_frames": radius,
                "written_points": 0,
                "removed_points": len(removed),
                "replaces_previous": True,
                "keyframe_budget": min(MAX_POINTS, KEYFRAME_LIMIT // 3),
                "measured_travel": [
                    round(max(abs(point[0]) for point in offsets), 6),
                    round(max(abs(point[1]) for point in offsets), 6),
                ],
                "measured_roll": round(
                    max([abs(roll) for roll in motion.get("rolls", [])], default=0.0), 6
                ),
                "translation_correction": 0.0,
                "roll_correction": 0.0,
                "zoom_to_hide_borders": 1.0,
                "max_crop": max_crop,
                "clamped_axes": 0,
                "analysed_frames": motion["analysed_frames"],
                "dropped_frames": motion["dropped_frames"],
                "note": (
                    f"strength 0 took the previous stabilisation off this clip: {len(removed)} "
                    "keyframes and its record are cleared in the same revision"
                ),
            }
        return [], {
            "smoothing_radius_frames": radius,
            "written_points": 0,
            "keyframe_budget": min(MAX_POINTS, KEYFRAME_LIMIT // 3),
            "measured_travel": [
                round(max(abs(point[0]) for point in offsets), 6),
                round(max(abs(point[1]) for point in offsets), 6),
            ],
            "measured_roll": round(
                max([abs(roll) for roll in motion.get("rolls", [])], default=0.0), 6
            ),
            "translation_correction": 0.0,
            "roll_correction": 0.0,
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
    worst_roll = max([abs(roll) for roll in roll_residual], default=0.0)
    if worst_roll < ROLL_DEADBAND_DEGREES:
        # Nothing above was resolved: one pixel of anchor quantisation over the ~300 px baseline
        # between anchors is 0.19 degrees, so writing a rotation curve for less than that would be
        # the stabiliser inventing a roll the measurement cannot tell from its own noise.
        roll_residual = []
        worst_roll = 0.0

    commands: list[dict] = []
    written: dict[str, list[Keyframe]] = {}

    def starting_at(name: str, local: int) -> float:
        """What the correction is composed onto.

        A clip the stabiliser already owns recomputes from its static transform, so a second press
        replaces the previous one (change the strength, pay one click) instead of stacking a second
        copy of the same measurement. Anything else keeps whatever the editor animated by hand.
        """
        return getattr(clip.effects, name) if owned else sample(clip, name, local)

    for name, axis in (("x", 0), ("y", 1)):
        frames = []
        for index in picks:
            # `offsets` starts at the second analysed frame, so frame `index + 1` of the clip.
            local = min(clip.duration_ticks - 1, frame_ticks * (index + 1))
            current = starting_at(name, local)
            frames.append(
                Keyframe(
                    property=name,  # type: ignore[arg-type]
                    at_ticks=local,
                    value=round(current - residual[index][axis], 6),
                    interpolation="linear",
                )
            )
        written[name] = frames
    if roll_residual:
        written["rotation"] = [
            Keyframe(
                property="rotation",
                at_ticks=min(clip.duration_ticks - 1, frame_ticks * (index + 1)),
                value=round(
                    starting_at("rotation", min(clip.duration_ticks - 1, frame_ticks * (index + 1)))
                    - roll_residual[index],
                    6,
                ),
                interpolation="linear",
            )
            for index in picks
        ]
    # Rotating a frame-sized layer by θ uncovers its corners: with the picture `w` wide and `h`
    # tall, the height has to grow by w·sinθ, i.e. a scale of 1 + θ·(w/h) for small θ. Added to the
    # translation term rather than maxed with it, because both can be at their worst together.
    aspect = project.settings.width / project.settings.height
    zoom = 1.0 + 2.0 * worst + radians(worst_roll) * aspect
    written["scale"] = [
        Keyframe(
            property="scale",
            at_ticks=0,
            value=round(starting_at("scale", 0) * zoom, 6),
            interpolation="linear",
        ),
        Keyframe(
            property="scale",
            at_ticks=clip.duration_ticks - 1,
            value=round(starting_at("scale", clip.duration_ticks - 1) * zoom, 6),
            interpolation="linear",
        ),
    ]
    for name in ("x", "y", "rotation", "scale"):
        if name not in written:
            continue
        commands.append(
            {
                "op": "keyframes.replace",
                "clip_id": clip.id,
                "property": name,
                "keyframes": [point.model_dump() for point in written[name]],
            }
        )
    # The record rides in the same batch as the curves it describes: one revision either has both
    # or has neither, so a clip can never claim a stabilisation whose curves were thrown away.
    commands.append(
        {
            "op": "clip.stabilize_record",
            "clip_id": clip.id,
            "record": {
                "strength": strength,
                "max_crop": max_crop,
                "points": len(picks),
                "translation_correction": round(worst, 6),
                "roll_correction": round(worst_roll, 6),
                "zoom_to_hide_borders": round(zoom, 6),
                "analysed_frames": motion["analysed_frames"],
            },
        }
    )
    notes = {
        "smoothing_radius_frames": radius,
        "written_points": len(picks),
        "replaces_previous": owned,
        "keyframe_budget": budget,
        "measured_travel": [
            round(max(abs(point[0]) for point in offsets), 6),
            round(max(abs(point[1]) for point in offsets), 6),
        ],
        "measured_roll": round(max([abs(roll) for roll in rolls], default=0.0), 6),
        "translation_correction": round(worst, 6),
        "roll_correction": round(worst_roll, 6),
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
