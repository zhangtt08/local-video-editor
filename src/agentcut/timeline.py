"""Deterministic, side-effect-free editing. Intervals are [start, end)."""

import hashlib
from bisect import bisect_right
from math import lcm
from pathlib import Path

from pydantic import ValidationError

from .contracts import (
    GRADE_INLINE_SAMPLE_LIMIT,
    MAX_TICKS,
    SCHEMA_VERSION,
    Asset,
    Clip,
    ClipColor,
    ClipEffects,
    Command,
    EditorError,
    FadeEnvelope,
    Identifier,
    Keyframe,
    Project,
    Sequence,
    SpeedPoint,
    TextStyle,
    Track,
    Transition,
    project_content_ticks,
    render_presets,
)
from .masks import fit_box
from .speed import base_source_ticks, consumed_source_ticks, scale_curve, slice_curve
from .subtitles import parse_srt

# Read off the contract, so a tracking plan can never promise a write the clip has no room for.
CLIP_KEYFRAME_LIMIT = next(
    int(rule.max_length)
    for rule in Clip.model_fields["keyframes"].metadata
    if getattr(rule, "max_length", None)
)
MASK_TRACK_CURVES = ("mask_x", "mask_y")
MASK_TRACK_SIZED_CURVES = (*MASK_TRACK_CURVES, "mask_width", "mask_height")


def mask_track_capacity(
    clip: Clip, curves_per_point: int, merge: bool, from_ticks: int, frame_ticks: int
) -> int:
    """How many frames a tracking run starting at `from_ticks` still fits on this clip.

    One sighting costs `curves_per_point` curves — 2 for a centre-only path, 4 when the box also
    follows the subject's scale — and every curve the run cannot reach stays on the clip: with
    `merge` those before the window, and those past the end the run would have to overshoot to
    reach a longer window. Because a longer window swallows tail curves, the count is widened and
    re-checked rather than solved once, and it stops as soon as the window it proposes really fits.
    A whole-path rewrite (`merge` off) is credited with clearing every mask-motion curve the clip
    carries, which is exactly what `_apply_mask_track` does with it.
    """
    produced = set(
        MASK_TRACK_SIZED_CURVES if curves_per_point > len(MASK_TRACK_CURVES) else MASK_TRACK_CURVES
    )
    cleared = set(MASK_TRACK_SIZED_CURVES) if not merge else produced
    start = clip.animation_offset_ticks + from_ticks
    fixed = sum(1 for key in clip.keyframes if key.property not in cleared)
    before = (
        0
        if not merge
        else sum(1 for key in clip.keyframes if key.property in produced and key.at_ticks < start)
    )
    frames = max(0, (CLIP_KEYFRAME_LIMIT - fixed - before) // curves_per_point)
    if not merge:
        return frames
    for _ in range(4):
        if frames < 2:
            return frames
        stop = start + (frames - 1) * frame_ticks
        beyond = sum(
            1 for key in clip.keyframes if key.property in produced and key.at_ticks > stop
        )
        room = (CLIP_KEYFRAME_LIMIT - fixed - before - beyond) // curves_per_point
        if room >= frames:
            return frames
        frames = room
    return frames


def sequence_view(project: Project, sequence_id: str | None = None) -> Project:
    """A read projection; assets/settings/revision always belong to the root project."""
    if sequence_id is None:
        return project
    sequence = project.sequences.get(sequence_id)
    if sequence is None:
        raise EditorError("NOT_FOUND", "sequence does not exist", 404, sequence_id=sequence_id)
    return project.model_copy(update={"tracks": sequence.tracks, "clips": sequence.clips})


def validate_timeline(project: Project) -> None:
    if len(project.clips) + sum(len(s.clips) for s in project.sequences.values()) > 20_000:
        raise EditorError("PROJECT_LIMIT", "root and sequence clips exceed 20000")
    if len({marker.id for marker in project.markers}) != len(project.markers):
        raise EditorError("INVALID_PROJECT", "marker ids have to be unique")
    if project.settings.out_ticks is not None:
        horizon = project_content_ticks(project)
        if project.settings.out_ticks > horizon:
            raise EditorError(
                "INVALID_MARKS",
                f"the out point has to sit inside the current content (0..{horizon} ticks)",
                422,
                in_ticks=project.settings.in_ticks,
                out_ticks=project.settings.out_ticks,
            )
    for key, asset in project.assets.items():
        if key != asset.id:
            raise EditorError("INVALID_PROJECT", "asset map key must match asset id")
        if asset.kind == "sequence":
            sequence = project.sequences.get(asset.sequence_id)
            if sequence is None or asset.duration_ticks != sequence.duration_ticks:
                raise EditorError("MISSING_REFERENCE", "sequence asset needs its exact duration")
    _validate_scope(project)
    for key, sequence in project.sequences.items():
        if key != sequence.id:
            raise EditorError("INVALID_PROJECT", "sequence map key must match sequence id")
        if sequence.duration_ticks % project.settings.frame_ticks:
            raise EditorError("TIME_NOT_ALIGNED", "sequence duration must align to frames")
        _validate_scope(sequence_view(project, key))
        if any(
            c.position_ticks + c.duration_ticks > sequence.duration_ticks
            for c in sequence.clips.values()
        ):
            raise EditorError(
                "SEQUENCE_OUT_OF_BOUNDS", "extend the sequence before adding clips beyond its end"
            )
    memo = {}

    def size(sequence_id, visiting):
        if sequence_id in visiting:
            raise EditorError("SEQUENCE_CYCLE", "a sequence cannot contain itself")
        if len(visiting) >= 8:
            raise EditorError("SEQUENCE_DEPTH", "at most 8 nested sequence levels")
        if sequence_id in memo:
            depth, count = memo[sequence_id]
            if depth + len(visiting) > 8:
                raise EditorError("SEQUENCE_DEPTH", "at most 8 nested sequence levels")
            return depth, count
        depth, count = 1, 0
        for clip in project.sequences[sequence_id].clips.values():
            asset = project.assets[clip.asset_id]
            child_depth, child_count = (
                size(asset.sequence_id, visiting | {sequence_id})
                if asset.kind == "sequence"
                else (0, 1)
            )
            depth, count = max(depth, child_depth + 1), count + child_count
            if count > 20_000:
                raise EditorError("PROJECT_LIMIT", "expanded sequence exceeds 20000 clips")
        memo[sequence_id] = depth, max(1, count)
        return memo[sequence_id]

    for sequence_id in project.sequences:
        size(sequence_id, set())
    # ponytail: bounded graph expansion; raise this ceiling only after render/preview profiling.
    if (
        sum(
            memo[project.assets[c.asset_id].sequence_id][1]
            if project.assets[c.asset_id].kind == "sequence"
            else 1
            for c in project.clips.values()
        )
        > 20_000
    ):
        raise EditorError("PROJECT_LIMIT", "expanded timeline exceeds 20000 clips")


def _validate_scope(project: Project) -> None:
    tracks = {track.id: track for track in project.tracks}
    if len(tracks) != len(project.tracks):
        raise EditorError("DUPLICATE_ID", "track ids must be unique")
    for track in project.tracks:
        if track.kind != "video" and track.blend_mode != "normal":
            raise EditorError("INVALID_BLEND_MODE", "blend modes require a picture track")
    intervals: dict[str, list[Clip]] = {track_id: [] for track_id in tracks}
    for key, asset in project.assets.items():
        if key != asset.id:
            raise EditorError("INVALID_PROJECT", "asset map key must match asset id")
    for key, clip in project.clips.items():
        if key != clip.id:
            raise EditorError("INVALID_PROJECT", "clip map key must match clip id")
        asset, track = project.assets.get(clip.asset_id), tracks.get(clip.track_id)
        if asset is None or track is None:
            raise EditorError(
                "MISSING_REFERENCE", "clip requires an existing asset and track", clip_id=clip.id
            )
        if asset.kind == "audio" and track.kind == "video":
            raise EditorError(
                "TRACK_KIND_MISMATCH", "asset kind does not match track kind", clip_id=clip.id
            )
        if asset.kind in {"image", "text", "sequence"} and track.kind == "audio":
            raise EditorError(
                "TRACK_KIND_MISMATCH", "asset kind does not match track kind", clip_id=clip.id
            )
        if asset.kind in {"image", "text"} and clip.source_in_ticks != 0:
            raise EditorError("INVALID_SOURCE_RANGE", "images must have source_in_ticks=0")
        if asset.kind in {"image", "text"} and clip.speed_percent != 100:
            raise EditorError("INVALID_SPEED", "images have no playback speed")
        if (asset.kind == "text") != (clip.text is not None):
            raise EditorError(
                "INVALID_TEXT", "text clips require text style; media clips cannot carry text"
            )
        if clip.mask and track.kind != "video":
            raise EditorError("INVALID_MASK", "masks require a picture track", clip_id=clip.id)
        problem = clip.mask_animation_problem()
        if problem:
            raise EditorError("INVALID_MASK", problem, clip_id=clip.id)
        end = clip.position_ticks + clip.duration_ticks
        if clip.animation_offset_ticks + clip.duration_ticks > MAX_TICKS:
            raise EditorError("TIME_OVERFLOW", "animation clock exceeds exact integer range")
        if clip.speed_curve:
            if asset.kind in {"image", "text", "sequence"}:
                raise EditorError("INVALID_SPEED", "only media clips can carry a speed curve")
            if clip.link_id or clip.transition_in:
                raise EditorError(
                    "INVALID_SPEED", "a speed curve cannot combine with a link or transition"
                )
            if any(
                other.transition_in and other.transition_in.from_clip_id == clip.id
                for other in project.clips.values()
            ):
                raise EditorError("INVALID_SPEED", "a speed clip cannot feed a transition")
            source_end = clip.source_in_ticks + consumed_source_ticks(
                clip,
                project.settings.frame_ticks
                if track.kind == "video"
                else project.settings.timebase // project.settings.sample_rate,
            )
        else:
            source_end = clip.source_in_ticks + base_source_ticks(clip)
        if end > MAX_TICKS or source_end > MAX_TICKS:
            raise EditorError("TIME_OVERFLOW", "time exceeds exact JSON integer range")
        if asset.duration_ticks is not None and source_end > asset.duration_ticks:
            raise EditorError(
                "SOURCE_OUT_OF_BOUNDS", "clip exceeds registered source duration", clip_id=clip.id
            )
        quantum = (
            project.settings.frame_ticks
            if track.kind == "video"
            else project.settings.timebase // project.settings.sample_rate
        )
        if clip.position_ticks % quantum or clip.duration_ticks % quantum:
            raise EditorError(
                "TIME_NOT_ALIGNED",
                "position/duration must align to frames or samples",
                clip_id=clip.id,
                quantum_ticks=quantum,
            )
        intervals[track.id].append(clip)
    for clip in project.clips.values():
        transition = clip.transition_in
        if not transition:
            continue
        left = project.clips.get(transition.from_clip_id)
        if (
            not left
            or left.id == clip.id
            or left.track_id != clip.track_id
            or tracks[clip.track_id].kind != "video"
            or left.position_ticks >= clip.position_ticks
            or left.position_ticks + left.duration_ticks > clip.position_ticks + clip.duration_ticks
            or left.position_ticks + left.duration_ticks - clip.position_ticks
            != transition.duration_ticks
        ):
            raise EditorError(
                "INVALID_TRANSITION",
                "transition requires two adjacent overlapping video clips",
                clip_id=clip.id,
            )
    for clips in intervals.values():
        clips.sort(key=lambda clip: (clip.position_ticks, clip.id))
        for left, right in zip(clips, clips[1:]):
            if left.position_ticks + left.duration_ticks > right.position_ticks:
                if right.transition_in and right.transition_in.from_clip_id == left.id:
                    continue
                raise EditorError(
                    "CLIP_OVERLAP",
                    "same-track overlap requires an explicit transition",
                    clip_ids=[left.id, right.id],
                )
        if any(
            left.position_ticks + left.duration_ticks > third.position_ticks
            for left, third in zip(clips, clips[2:])
        ):
            raise EditorError("TRANSITION_EDIT_CONFLICT", "three clips cannot overlap on one track")


def _node_inline_samples(node) -> int:
    """How many numbers one grade node keeps inline (parallel branches carry the same payload)."""
    kind = getattr(node, "kind", None)
    if kind == "lut":
        return sum(len(channel) for channel in node.channels)
    if kind == "lut3d":
        return len(node.cells)
    if kind == "parallel":
        return sum(_node_inline_samples(branch) for branch in node.branches)
    return 0


def grade_inline_samples(project) -> int:
    """The project-wide count of samples stored inside grade chains, nested sequences included."""

    def walk(target) -> int:
        total = sum(
            _node_inline_samples(node)
            for clip in target.clips.values()
            for node in clip.color.grade
        )
        for nested in getattr(target, "sequences", {}).values():
            total += walk(nested)
        return total

    return walk(project)


def grade_capacity(project) -> dict:
    """The inline lookup-table budget read from the other side: used, left, and by whom.

    Same function the reducer refuses with, so an Agent that wants to put a look on a whole
    track can see how many cubes still fit before it edits rather than by being refused. The
    breakdown names the clips that actually hold tables; `nested_samples` is what the nested
    compositions contribute, so the parts add back up to `samples`.
    """
    by_clip = {
        clip_id: sum(_node_inline_samples(node) for node in clip.color.grade)
        for clip_id, clip in project.clips.items()
    }
    used = grade_inline_samples(project)
    ranked = sorted(by_clip.items(), key=lambda item: (-item[1], item[0]))
    listed = dict(item for item in ranked[:20] if item[1])
    return {
        "samples": used,
        "limit": GRADE_INLINE_SAMPLE_LIMIT,
        "room": max(0, GRADE_INLINE_SAMPLE_LIMIT - used),
        "clips_with_tables": sum(1 for value in by_clip.values() if value),
        "worst_clip_id": ranked[0][0] if listed else None,
        "worst_clip_samples": ranked[0][1] if listed else 0,
        "by_clip": listed,
        "nested_samples": used - sum(by_clip.values()),
    }


def _grade_inline_budget(project, before: int) -> None:
    """Refuse the edit that would push the project past its inline lookup-table budget.

    Checked on the finished candidate against what the project held before the batch: an edit
    that only renames a clip must stay possible even if the project is already at the ceiling,
    so the budget stops growth rather than freezing the project. The numbers travel in every
    history snapshot, so one chain at a time is the wrong unit to count — a project of a
    hundred clips each holding a 17-cube is the thing that actually hurts.
    The refusal hands back both totals and the worst clip, because the only way to make room
    is to delete or shrink a table someone else placed.
    """
    total = grade_inline_samples(project)
    if total <= GRADE_INLINE_SAMPLE_LIMIT or total <= before:
        return
    worst = max(
        project.clips.values(),
        key=lambda clip: sum(_node_inline_samples(node) for node in clip.color.grade),
        default=None,
    )
    worst_samples = sum(_node_inline_samples(node) for node in worst.color.grade) if worst else 0
    raise EditorError(
        "GRADE_INLINE_BUDGET",
        f"the project's inline lookup tables would hold {total} samples and the budget is "
        f"{GRADE_INLINE_SAMPLE_LIMIT}",
        422,
        samples=total,
        limit=GRADE_INLINE_SAMPLE_LIMIT,
        worst_clip_id=worst.id if worst else None,
        worst_clip_samples=worst_samples,
    )


def apply_commands(
    project: Project, commands: list[Command], sequence_id: str | None = None
) -> Project:
    root = project.model_copy(deep=True)
    root.schema_version = SCHEMA_VERSION
    candidate = sequence_view(root, sequence_id)
    inline_before = grade_inline_samples(candidate)
    explicit_transitions = set()
    for index, command in enumerate(commands):
        try:
            if command.op == "sequence.nest":
                _nest(candidate, command)
            elif command.op == "sequence.add":
                if command.sequence.id in candidate.sequences:
                    raise EditorError("DUPLICATE_ID", "sequence already exists")
                candidate.sequences[command.sequence.id] = command.sequence.model_copy(deep=True)
            elif command.op == "sequence.update":
                sequence = candidate.sequences.get(command.sequence_id)
                if sequence is None:
                    raise EditorError(
                        "NOT_FOUND", "sequence does not exist", 404, sequence_id=command.sequence_id
                    )
                if command.name is not None:
                    sequence.name = command.name
                if command.duration_ticks is not None:
                    sequence.duration_ticks = command.duration_ticks
                for asset in candidate.assets.values():
                    if asset.sequence_id == sequence.id:
                        asset.duration_ticks = sequence.duration_ticks
                        asset.label = sequence.name
            elif command.op == "sequence.remove":
                if command.sequence_id == sequence_id:
                    raise EditorError(
                        "SEQUENCE_IN_USE",
                        "return to the main timeline before removing this sequence",
                    )
                if command.sequence_id not in candidate.sequences:
                    raise EditorError(
                        "NOT_FOUND", "sequence does not exist", 404, sequence_id=command.sequence_id
                    )
                assets = {
                    a.id for a in candidate.assets.values() if a.sequence_id == command.sequence_id
                }
                if any(c.asset_id in assets for c in _all_clips(root, candidate)):
                    raise EditorError("SEQUENCE_IN_USE", "remove clips using the sequence first")
                for asset_id in assets:
                    del candidate.assets[asset_id]
                del candidate.sequences[command.sequence_id]
            elif command.op == "captions.import":
                if command.asset_id in candidate.assets or any(
                    t.id == command.track_id for t in candidate.tracks
                ):
                    raise EditorError("DUPLICATE_ID", "subtitle asset and track need new ids")
                cues = parse_srt(command.srt, candidate.settings.frame_ticks, command.offset_ticks)
                candidate.tracks.append(Track(id=command.track_id, kind="video", name="字幕"))
                candidate.assets[command.asset_id] = Asset(
                    id=command.asset_id, kind="text", label="字幕", reference="generated:subtitles"
                )
                for number, (start, stop, body) in enumerate(cues):
                    clip_id = (
                        "sub-"
                        + hashlib.sha256(f"{command.track_id}:{number}".encode()).hexdigest()[:24]
                    )
                    if clip_id in candidate.clips:
                        raise EditorError("DUPLICATE_ID", "subtitle clip id already exists")
                    candidate.clips[clip_id] = Clip(
                        id=clip_id,
                        asset_id=command.asset_id,
                        track_id=command.track_id,
                        position_ticks=start,
                        duration_ticks=stop - start,
                        text=TextStyle(body=body),
                        effects=ClipEffects(y=0.35),
                    )
            elif command.op == "track.add":
                if any(track.id == command.track.id for track in candidate.tracks):
                    raise EditorError("DUPLICATE_ID", "track already exists")
                track = command.track.model_copy(deep=True)
                if command.index is None:
                    candidate.tracks.append(track)
                else:
                    candidate.tracks.insert(min(command.index, len(candidate.tracks)), track)
            elif command.op == "track.remove":
                target = next(
                    (track for track in candidate.tracks if track.id == command.track_id), None
                )
                if target is None:
                    raise EditorError("NOT_FOUND", "track does not exist", 404)
                if target.locked:
                    raise EditorError("TRACK_LOCKED", "unlock the track before editing")
                if any(clip.track_id == target.id for clip in candidate.clips.values()):
                    raise EditorError(
                        "TRACK_NOT_EMPTY", "remove or move the clips on this track first"
                    )
                candidate.tracks = [track for track in candidate.tracks if track.id != target.id]
            elif command.op == "track.update":
                for number, track in enumerate(candidate.tracks):
                    if track.id != command.track_id:
                        continue
                    if command.blend_mode is not None:
                        _unlocked(candidate, track.id)
                    updates = command.model_dump(exclude={"op", "track_id"}, exclude_none=True)
                    candidate.tracks[number] = track.model_copy(update=updates)
                    break
                else:
                    raise EditorError("NOT_FOUND", "track does not exist", 404)
            elif command.op == "marker.set":
                marker = command.marker
                horizon = project_content_ticks(candidate)
                if marker.at_ticks > horizon:
                    raise EditorError(
                        "INVALID_MARKER",
                        f"a marker has to sit inside the current content (0..{horizon} ticks)",
                        422,
                        marker_id=marker.id,
                    )
                for number, existing in enumerate(candidate.markers):
                    if existing.id == marker.id:
                        candidate.markers[number] = marker.model_copy(deep=True)
                        break
                else:
                    candidate.markers.append(marker.model_copy(deep=True))
                candidate.markers.sort(key=lambda item: (item.at_ticks, item.id))
            elif command.op == "marker.remove":
                kept = [item for item in candidate.markers if item.id != command.marker_id]
                if len(kept) == len(candidate.markers):
                    raise EditorError("NOT_FOUND", "marker does not exist", 404)
                candidate.markers = kept
            elif command.op == "recipe.set":
                recipe = command.recipe
                known = {preset["id"] for preset in render_presets()}
                for item in recipe.items:
                    if item.preset_id not in known:
                        raise EditorError(
                            "INVALID_RECIPE",
                            f"unknown render preset {item.preset_id!r} in deliverable "
                            f"{item.filename!r}",
                            422,
                            recipe_id=recipe.id,
                        )
                for number, existing in enumerate(candidate.recipes):
                    if existing.id == recipe.id:
                        candidate.recipes[number] = recipe.model_copy(deep=True)
                        break
                else:
                    candidate.recipes.append(recipe.model_copy(deep=True))
            elif command.op == "recipe.remove":
                kept = [item for item in candidate.recipes if item.id != command.recipe_id]
                if len(kept) == len(candidate.recipes):
                    raise EditorError("NOT_FOUND", "delivery recipe does not exist", 404)
                candidate.recipes = kept
            elif command.op == "asset.register":
                if command.asset.id in candidate.assets:
                    raise EditorError("DUPLICATE_ID", "asset already exists")
                candidate.assets[command.asset.id] = command.asset.model_copy(deep=True)
            elif command.op == "asset.import":
                verified = command.verified
                if verified.probe_id != command.probe_id:
                    raise EditorError("INVALID_PROBE", "probe id does not match the media record")
                if not Path(verified.path).is_absolute():
                    raise EditorError("INVALID_PROBE", "verified media needs an absolute path")
                existing = candidate.assets.get(command.asset_id)
                if (
                    existing
                    and existing.verified
                    and existing.verified.content_sha256 != verified.content_sha256
                ):
                    raise EditorError(
                        "ASSET_MEDIA_CONFLICT",
                        "this asset id already holds different media; remove it first",
                        409,
                    )
                kind = verified.kind
                candidate.assets[command.asset_id] = Asset(
                    id=command.asset_id,
                    kind=kind,
                    label=command.label,
                    reference=verified.probe_id,
                    duration_ticks=None if kind == "image" else max(1, verified.duration_ticks),
                    verified=verified,
                )
            elif command.op == "asset.remove":
                if command.asset_id not in candidate.assets:
                    raise EditorError("NOT_FOUND", "asset does not exist", 404)
                if any(clip.asset_id == command.asset_id for clip in _all_clips(root, candidate)):
                    raise EditorError("ASSET_IN_USE", "remove the clips using this asset first")
                del candidate.assets[command.asset_id]
            elif command.op == "clips.add":
                for clip in command.clips:
                    _unlocked(candidate, clip.track_id)
                    if clip.id in candidate.clips:
                        raise EditorError("DUPLICATE_ID", "clip already exists")
                    candidate.clips[clip.id] = clip.model_copy(deep=True)
                    if clip.transition_in:
                        explicit_transitions.add(clip.id)
            elif command.op in {"clips.group", "clips.link"}:
                _associate(candidate, command)
            elif command.op in {"clips.move", "clips.remove", "clips.split"}:
                clips = _selected_clips(candidate, command.clip_ids)
                if command.op == "clips.split":
                    if command.right_clip_ids.keys() != set(command.clip_ids):
                        raise EditorError(
                            "INVALID_SELECTION", "provide a right id for each selected clip"
                        )
                    for clip in clips:
                        _split_clip(
                            candidate, clip, command.at_ticks, command.right_clip_ids[clip.id]
                        )
                elif command.op == "clips.move":
                    sources = {clip.track_id for clip in clips}
                    if command.track_map.keys() - sources:
                        raise EditorError("INVALID_TRACK_MAP", "map only selected source tracks")
                    for clip in clips:
                        destination = command.track_map.get(clip.track_id, clip.track_id)
                        _unlocked(candidate, destination)
                        position = clip.position_ticks + command.delta_ticks
                        if not 0 <= position <= MAX_TICKS:
                            raise EditorError("TIME_OVERFLOW", "group move exceeds exact clock")
                        clip.position_ticks = position
                        clip.track_id = destination
                else:
                    if command.ripple:
                        _ripple_group(candidate, clips)
                    for clip in clips:
                        del candidate.clips[clip.id]
            elif command.op in {"clip.add", "clip.insert", "clip.overwrite"}:
                _unlocked(candidate, command.clip.track_id)
                if command.clip.id in candidate.clips:
                    raise EditorError("DUPLICATE_ID", "clip already exists")
                if command.op != "clip.add":
                    _place_clip(candidate, command)
                candidate.clips[command.clip.id] = command.clip.model_copy(deep=True)
                if command.clip.transition_in:
                    explicit_transitions.add(command.clip.id)
            else:
                clip = candidate.clips.get(command.clip_id)
                if clip is None:
                    raise EditorError(
                        "NOT_FOUND", "clip does not exist", 404, clip_id=command.clip_id
                    )
                _unlocked(candidate, clip.track_id)
                if command.op == "transition.set":
                    _set_transition(candidate, clip, command)
                    explicit_transitions.add(clip.id)
                elif command.op == "transition.remove":
                    if not clip.transition_in:
                        raise EditorError("NOT_FOUND", "clip has no incoming transition", 404)
                    delta = clip.transition_in.duration_ticks
                    _shift_tail(candidate, clip, delta)
                    clip.transition_in = None
                elif command.op == "clip.ripple_remove":
                    incoming = clip.transition_in.duration_ticks if clip.transition_in else 0
                    outgoing = next(
                        (
                            c.transition_in.duration_ticks
                            for c in candidate.clips.values()
                            if c.transition_in and c.transition_in.from_clip_id == clip.id
                        ),
                        0,
                    )
                    removed = clip.duration_ticks - incoming - outgoing
                    if removed < 0:
                        raise EditorError(
                            "TRANSITION_EDIT_CONFLICT", "transitions overlap each other"
                        )
                    del candidate.clips[clip.id]
                    for other in candidate.clips.values():
                        if (
                            other.track_id == clip.track_id
                            and other.position_ticks >= clip.position_ticks + incoming
                        ):
                            other.position_ticks -= removed
                elif command.op == "clip.detach_audio":
                    asset = candidate.assets[clip.asset_id]
                    if asset.kind != "video":
                        raise EditorError("INVALID_DETACH", "only video clips embed audio")
                    if clip.embedded_audio is False:
                        raise EditorError("ALREADY_DETACHED", "audio was already detached")
                    if not asset.verified or not asset.verified.has_audio:
                        raise EditorError("NO_EMBEDDED_AUDIO", "clip has no embedded audio track")
                    target = next((t for t in candidate.tracks if t.id == command.track_id), None)
                    if target is None or target.kind != "audio":
                        raise EditorError(
                            "TRACK_KIND_MISMATCH", "pick an audio track for the sound"
                        )
                    if target.locked:
                        raise EditorError("TRACK_LOCKED", "track is locked")
                    if command.audio_clip_id in candidate.clips:
                        raise EditorError("DUPLICATE_ID", "clip already exists")
                    clip.embedded_audio = False
                    link = clip.link_id or f"link-detach-{clip.id}"
                    clip.link_id = link
                    audio = clip.model_copy(
                        update={
                            "id": command.audio_clip_id,
                            "track_id": command.track_id,
                            "transition_in": None,
                            "mask": None,
                            "keyframes": [k for k in clip.keyframes if k.property == "gain"],
                            "link_id": link,
                            "link_source_offset_ticks": 0,
                        }
                    )
                    candidate.clips[command.audio_clip_id] = audio
                elif command.op == "clip.effects":
                    clip.effects = command.effects.model_copy(deep=True)
                elif command.op == "clip.patch":
                    if command.effects:
                        clip.effects = ClipEffects.model_validate(
                            clip.effects.model_dump() | command.effects
                        )
                    if command.color:
                        if candidate.assets[clip.asset_id].kind == "audio":
                            raise EditorError("INVALID_COLOR", "audio has no color properties")
                        clip.color = ClipColor.model_validate(
                            clip.color.model_dump() | command.color
                        )
                    if command.text:
                        if clip.text is None:
                            raise EditorError("INVALID_TEXT", "select a text clip")
                        clip.text = TextStyle.model_validate(clip.text.model_dump() | command.text)
                elif command.op == "clip.mask":
                    clip.mask = command.mask.model_copy(deep=True) if command.mask else None
                elif command.op == "clip.mask_track":
                    _apply_mask_track(clip, command.points, command.merge)
                elif command.op == "clip.color":
                    if candidate.assets[clip.asset_id].kind == "audio":
                        raise EditorError("INVALID_COLOR", "audio has no color properties")
                    clip.color = command.color.model_copy(deep=True)
                elif command.op == "clip.grade":
                    if candidate.assets[clip.asset_id].kind == "audio":
                        raise EditorError("INVALID_COLOR", "audio has no color properties")
                    clip.color = ClipColor.model_validate(
                        {**clip.color.model_dump(), "grade": command.grade}
                    )
                elif command.op == "clip.text":
                    if candidate.assets[clip.asset_id].kind != "text":
                        raise EditorError("INVALID_TEXT", "select a text clip")
                    clip.text = command.text.model_copy(deep=True)
                elif command.op == "clip.fade":
                    if (
                        command.property == "opacity"
                        and candidate.assets[clip.asset_id].kind == "audio"
                    ):
                        raise EditorError(
                            "INVALID_FADE",
                            "audio has no opacity to fade",
                            422,
                            clip_id=clip.id,
                            asset_kind=candidate.assets[clip.asset_id].kind,
                        )
                    envelope = (clip.fade or FadeEnvelope()).model_copy(deep=True)
                    sides = ("in", "out") if command.mode == "both" else (command.mode,)
                    for side in sides:
                        if command.duration_ticks is not None:
                            setattr(
                                envelope, f"{command.property}_{side}_ticks", command.duration_ticks
                            )
                    if command.shape is not None:
                        setattr(envelope, f"{command.property}_shape", command.shape)
                    in_ticks, out_ticks = envelope.window(command.property)
                    if in_ticks + out_ticks > clip.duration_ticks:
                        raise EditorError(
                            "INVALID_FADE",
                            "this clip is too short for both windows: a fade-in and a fade-out "
                            "share the same edge-to-edge span",
                            422,
                            clip_id=clip.id,
                            clip_duration_ticks=clip.duration_ticks,
                            fade_in_ticks=in_ticks,
                            fade_out_ticks=out_ticks,
                            room_ticks=clip.duration_ticks - max(in_ticks, out_ticks),
                        )
                    # A shape with no window anywhere still records the choice, so the envelope is
                    # only dropped when nothing at all is left.
                    shaped = any(
                        envelope.shape(prop) != "ease_in_out" for prop in ("opacity", "gain")
                    )
                    clip.fade = envelope if in_ticks or out_ticks or shaped else None
                elif command.op == "clip.fade_adopt":
                    if (
                        command.property == "opacity"
                        and candidate.assets[clip.asset_id].kind == "audio"
                    ):
                        raise EditorError(
                            "INVALID_FADE",
                            "audio has no opacity to fade",
                            422,
                            clip_id=clip.id,
                            asset_kind=candidate.assets[clip.asset_id].kind,
                        )
                    adopted, reason, details = _fade_adoption(clip, command.property)
                    if adopted is None:
                        raise EditorError(
                            "FADE_ADOPT_SHAPE",
                            f"this fade cannot be moved into the edge windows: {reason}",
                            422,
                            **details,
                        )
                    envelope = (clip.fade or FadeEnvelope()).model_copy(deep=True)
                    setattr(envelope, f"{command.property}_in_ticks", adopted["in"])
                    setattr(envelope, f"{command.property}_out_ticks", adopted["out"])
                    setattr(envelope, f"{command.property}_shape", "ease_in_out")
                    # 两头都是从实际点位置读出来的，所以 `in + out <= duration` 是构造保证的，
                    # 不需要再判一次 INVALID_FADE（斜坡互相越过时读到的就是它们真正占的那两段）。
                    in_ticks, out_ticks = envelope.window(command.property)
                    # 被搬走的那几条关键帧要一起删掉，否则同一条淡会被乘两次。
                    clip.keyframes = [k for k in clip.keyframes if k.property != command.property]
                    clip.fade = envelope
                elif command.op == "clip.speed":
                    if candidate.assets[clip.asset_id].kind in {"image", "text"}:
                        raise EditorError("INVALID_SPEED", "images have no playback speed")
                    if clip.stabilization is not None and command.speed_percent != 100:
                        # Same reason as the speed-curve guard above: the correction was measured
                        # against this clip's source frames one-for-one, so a new rate plays an
                        # existing correction at the wrong speed instead of removing it.
                        raise EditorError(
                            "STABILIZE_LOCKED",
                            "this clip is stabilised: the correction is one keyframe per source "
                            "frame, so a new speed would play it at the wrong rate. Clear the "
                            "stabilisation (`clip.stabilize_record` with no record, or 画面稳定 at "
                            "strength 0) and change the speed before stabilising again.",
                            422,
                            clip_id=clip.id,
                            speed_percent=command.speed_percent,
                        )
                    track = next(t for t in candidate.tracks if t.id == clip.track_id)
                    quantum = (
                        candidate.settings.frame_ticks
                        if track.kind == "video"
                        else candidate.settings.timebase // candidate.settings.sample_rate
                    )
                    duration = (
                        clip.duration_ticks
                        * clip.speed_percent
                        // command.speed_percent
                        // quantum
                        * quantum
                    )
                    if duration < quantum:
                        raise EditorError(
                            "INVALID_SPEED", "result must contain at least one frame or sample"
                        )
                    if command.ripple:
                        tail_start = next(
                            (
                                c.position_ticks
                                for c in candidate.clips.values()
                                if c.transition_in and c.transition_in.from_clip_id == clip.id
                            ),
                            clip.position_ticks + clip.duration_ticks,
                        )
                        for other in candidate.clips.values():
                            if (
                                other.track_id == clip.track_id
                                and other.position_ticks >= tail_start
                            ):
                                other.position_ticks += duration - clip.duration_ticks
                    if clip.speed_curve:
                        clip.speed_curve = [
                            SpeedPoint.model_validate(point)
                            for point in scale_curve(
                                [point.model_dump() for point in clip.speed_curve],
                                duration,
                                clip.duration_ticks,
                            )
                        ]
                    clip.duration_ticks = duration
                    clip.speed_percent = command.speed_percent
                elif command.op == "clip.speed_curve":
                    if candidate.assets[clip.asset_id].kind in {"image", "text", "sequence"}:
                        raise EditorError(
                            "INVALID_SPEED", "only media clips can carry a speed curve"
                        )
                    if clip.stabilization is not None and command.points:
                        raise EditorError(
                            "STABILIZE_LOCKED",
                            "this clip is stabilised: the correction is one keyframe per source "
                            "frame, and a changing rate would play it at the wrong speed. Clear "
                            "the "
                            "stabilisation (`clip.stabilize_record` with no record, or 画面稳定 at "
                            "strength 0) before ramping the speed.",
                            422,
                            clip_id=clip.id,
                        )
                    if command.points is None:
                        clip.speed_curve = None
                    else:
                        marks = [point.model_dump() for point in command.points]
                        if any(
                            right <= left
                            for left, right in zip(
                                [mark["at_ticks"] for mark in marks],
                                [mark["at_ticks"] for mark in marks][1:],
                            )
                        ):
                            raise EditorError("INVALID_SPEED", "curve offsets must increase")
                        if marks[0]["at_ticks"] != 0 or marks[-1]["at_ticks"] > clip.duration_ticks:
                            raise EditorError(
                                "INVALID_SPEED", "the curve must start at the clip head and fit it"
                            )
                        if all(mark["percent"] == 100 for mark in marks):
                            raise EditorError(
                                "INVALID_SPEED", "a flat 100% curve is the clip's base speed"
                            )
                        clip.speed_curve = [SpeedPoint.model_validate(mark) for mark in marks]
                elif command.op in {"keyframe.move", "keyframes.move"}:
                    moves = [command] if command.op == "keyframe.move" else command.moves
                    _move_keyframes(clip, moves)
                elif command.op == "keyframes.remove":
                    sources = [(k.property, k.at_ticks) for k in command.keyframes]
                    _remove_keyframes(clip, sources)
                elif command.op == "clip.stabilize_record":
                    # The record is the only state this feature has; the curves it describes are
                    # written by the same batch, so a half-applied stabilisation cannot exist.
                    clip.stabilization = command.record
                elif command.op == "keyframes.replace":
                    offset = clip.animation_offset_ticks
                    written = [
                        key.model_copy(update={"at_ticks": offset + key.at_ticks})
                        for key in command.keyframes
                    ]
                    others = [k for k in clip.keyframes if k.property != command.property]
                    clip.keyframes = sorted(
                        others + written, key=lambda k: (k.property, k.at_ticks)
                    )
                elif command.op in {"keyframe.set", "keyframe.remove"}:
                    point = command.keyframe if command.op == "keyframe.set" else command
                    at = clip.animation_offset_ticks + point.at_ticks
                    _remove_keyframes(clip, [(point.property, point.at_ticks)])
                    if command.op == "keyframe.set":
                        clip.keyframes.append(point.model_copy(update={"at_ticks": at}))
                    clip.keyframes.sort(key=lambda k: (k.property, k.at_ticks))
                elif command.op == "clip.remove":
                    del candidate.clips[clip.id]
                elif command.op == "clip.move":
                    _unlocked(candidate, command.track_id)
                    candidate.clips[clip.id] = clip.model_copy(
                        update={
                            "track_id": command.track_id,
                            "position_ticks": command.position_ticks,
                        }
                    )
                elif command.op == "clip.slip":
                    if clip.speed_curve:
                        raise EditorError(
                            "INVALID_SLIP",
                            "a clip with a speed curve cannot be slipped: the curve belongs to the "
                            "timeline window, so trim it instead",
                            422,
                            clip_id=clip.id,
                        )
                    if clip.link_id:
                        raise EditorError(
                            "INVALID_SLIP",
                            "this clip is linked to another one; slip would break the sync, so use "
                            "clip.trim or unlink it first",
                            409,
                            clip_id=clip.id,
                        )
                    _trim_clip(
                        candidate,
                        clip,
                        clip.position_ticks,
                        clip.source_in_ticks + command.source_offset_ticks,
                        clip.duration_ticks,
                    )
                elif command.op == "clip.slide":
                    _slide_clip(candidate, clip, command.delta_ticks)
                elif command.op in {"clip.trim", "clip.trim_linked"}:
                    members = [clip]
                    if command.op == "clip.trim_linked" and clip.link_id:
                        status = link_status(candidate)[clip.link_id]
                        if not status["synchronized"]:
                            raise EditorError(
                                "LINK_OUT_OF_SYNC", "restore sync or unlink before linked trimming"
                            )
                        members = _selected_clips(candidate, status["clip_ids"])
                    position = (
                        clip.position_ticks
                        if command.position_ticks is None
                        else command.position_ticks
                    )
                    source_delta = command.source_in_ticks - clip.source_in_ticks
                    old_ends = {
                        member.id: member.position_ticks + member.duration_ticks
                        for member in members
                    }
                    old_tracks = {member.id: member.track_id for member in members}
                    for member in members:
                        _trim_clip(
                            candidate,
                            member,
                            position,
                            member.source_in_ticks + source_delta,
                            command.duration_ticks,
                        )
                    if getattr(command, "ripple", False):
                        # Shift everything to the right of the edited clip on its track,
                        # keeping explicit transitions attached to the seam (their width is
                        # preserved because both ends move by the same amount).
                        for member in members:
                            old_end = old_ends[member.id]
                            shift = position + command.duration_ticks - old_end
                            if shift == 0:
                                continue
                            for other in list(candidate.clips.values()):
                                if other.id == member.id or other.track_id != old_tracks[member.id]:
                                    continue
                                attached = (
                                    other.transition_in
                                    and other.transition_in.from_clip_id == member.id
                                )
                                if other.position_ticks >= old_end or attached:
                                    if other.position_ticks + shift < 0:
                                        raise EditorError(
                                            "TIME_OVERFLOW", "ripple trim moves a clip past zero"
                                        )
                                    other.position_ticks += shift
                elif command.op == "clip.roll":
                    left = candidate.clips.get(command.clip_id)
                    right = candidate.clips.get(command.other_clip_id)
                    if left is None or right is None:
                        missing = command.clip_id if left is None else command.other_clip_id
                        raise EditorError("NOT_FOUND", "clip does not exist", 404, clip_id=missing)
                    _unlocked(candidate, left.track_id)
                    if left.track_id != right.track_id:
                        raise EditorError("INVALID_ROLL", "roll needs one track")
                    _unlocked(candidate, right.track_id)
                    pairs = [(left, right)]
                    if (left.link_id or right.link_id) and not (left.link_id and right.link_id):
                        raise EditorError(
                            "LINK_OUT_OF_SYNC", "link both sides or unlink before rolling"
                        )
                    if left.link_id and right.link_id:
                        statuses = link_status(candidate)
                        if not all(
                            statuses[key]["synchronized"] for key in (left.link_id, right.link_id)
                        ):
                            raise EditorError("LINK_OUT_OF_SYNC", "restore sync before rolling")
                        left_members = _selected_clips(
                            candidate, statuses[left.link_id]["clip_ids"]
                        )
                        right_members = _selected_clips(
                            candidate, statuses[right.link_id]["clip_ids"]
                        )
                        left_tracks = {c.track_id: c for c in left_members}
                        right_tracks = {c.track_id: c for c in right_members}
                        if set(left_tracks) != set(right_tracks):
                            raise EditorError("LINK_OUT_OF_SYNC", "linked sides disagree")
                        pairs = [(left_tracks[t], right_tracks[t]) for t in sorted(left_tracks)]
                    delta = command.delta_ticks
                    for pair_left, pair_right in pairs:
                        _unlocked(candidate, pair_left.track_id)
                        _unlocked(candidate, pair_right.track_id)
                        overlap = (
                            pair_right.transition_in.duration_ticks
                            if pair_right.transition_in
                            and pair_right.transition_in.from_clip_id == pair_left.id
                            else 0
                        )
                        seam = pair_left.position_ticks + pair_left.duration_ticks - overlap
                        if pair_right.position_ticks != seam:
                            raise EditorError(
                                "NOT_ADJACENT", "roll needs two touching clips on one track"
                            )
                        left_duration = pair_left.duration_ticks + delta
                        right_duration = pair_right.duration_ticks - delta
                        if left_duration <= 0 or right_duration <= 0:
                            raise EditorError("INVALID_ROLL", "roll erases a clip")
                        static = candidate.assets[pair_right.asset_id].kind in {"image", "text"}
                        source = (
                            0
                            if static
                            else pair_right.source_in_ticks
                            + delta * pair_right.speed_percent // 100
                        )
                        if source < 0:
                            raise EditorError("SOURCE_OUT_OF_BOUNDS", "roll exceeds source head")
                        _trim_clip(
                            candidate,
                            pair_right,
                            pair_right.position_ticks + delta,
                            source,
                            right_duration,
                        )
                        pair_left.duration_ticks = left_duration
                elif command.op == "clip.split":
                    _split_clip(candidate, clip, command.at_ticks, command.right_clip_id)
        except EditorError as error:
            error.details["command_index"] = index
            raise
    _repair_transitions(candidate, explicit_transitions)
    _repair_associations(candidate)
    try:
        if sequence_id is None:
            root = candidate
        else:
            root.sequences[sequence_id].tracks = candidate.tracks
            root.sequences[sequence_id].clips = candidate.clips
        candidate = Project.model_validate(root.model_dump())
    except ValidationError as error:
        raise EditorError(
            "PROJECT_LIMIT", "project exceeds the supported contract limits"
        ) from error
    # One rule for every way a mask can arrive: a free-form outline's box *is* the outline it was
    # drawn in. The exporter places the cut with that box and the browser sizes the same unit image
    # by it, so a clip added whole, a mask edited in place and one inside a nested sequence have to
    # agree — fitting the final state means no ingest path can forget it and no command can store a
    # box the picture would ignore.
    for entry in _all_clips(candidate, candidate):
        if entry.mask is not None and entry.mask.shape == "path":
            entry.mask = fit_box(entry.mask)
    # A stabilisation record is a claim about the curves the run wrote. Ordinary keyframe commands
    # can delete those curves from under it, and a clip that no longer steadies anything must not
    # keep telling the editor and the Agent that it is stabilised — the row would read 已稳定 while
    # the speed and reframe locks went on refusing on behalf of a correction that is not there.
    for entry in _all_clips(candidate, candidate):
        if entry.stabilization is not None and not any(
            key.property in {"x", "y", "rotation", "scale"} for key in entry.keyframes
        ):
            entry.stabilization = None
    # Validate the final batch state, allowing atomic swaps with temporary overlaps.
    validate_timeline(candidate)
    _grade_inline_budget(candidate, inline_before)
    return candidate


def _fade_adoption(clip, prop: str) -> tuple[dict | None, str, dict]:
    """Recognise the fade the pre-1.90 reducer wrote, and say how long each edge's window is.

    That reducer left exactly this shape behind: two points per edge, `0.0` at the edge and the
    property's resting value where the ramp ends, both eased, and nothing else on the property
    (it cleared the curve first). Anything looser is a hand-keyed curve, not a fade, so it is
    refused with the points quoted back rather than half-converted.
    """
    head = clip.animation_offset_ticks or 0
    tail = head + clip.duration_ticks
    resting = round(getattr(clip.effects, prop), 9)
    points = sorted((k for k in clip.keyframes if k.property == prop), key=lambda k: k.at_ticks)
    details = {
        "clip_id": clip.id,
        "property": prop,
        "clip_duration_ticks": clip.duration_ticks,
        "resting_value": getattr(clip.effects, prop),
        "keyframes": [
            {"at_ticks": k.at_ticks, "value": k.value, "interpolation": k.interpolation}
            for k in points
        ],
    }
    if not points:
        return None, "there are no keyframes on this property", details
    if clip.fade is not None and any(clip.fade.window(prop)):
        return None, "this property already carries edge windows", details
    if any(k.at_ticks < head or k.at_ticks > tail for k in points):
        return None, "some keyframes sit outside the clip", details
    if any(round(k.value, 9) not in (0.0, resting) for k in points):
        return None, "the ramp does not run between 0.0 and the resting value", details
    if any(k.interpolation != "ease" for k in points):
        return None, "the ramp is not the eased shape a fade used", details
    zeros = {k.at_ticks for k in points if round(k.value, 9) == 0.0}
    in_ticks = out_ticks = 0
    if head in zeros:
        after = [k.at_ticks for k in points if k.at_ticks > head]
        if not after:
            return None, "the clip starts faded but never comes back", details
        in_ticks = min(after) - head
    if tail in zeros:
        before = [k.at_ticks for k in points if k.at_ticks < tail]
        if not before:
            return None, "the clip ends faded but never started from full", details
        out_ticks = tail - max(before)
    if not in_ticks and not out_ticks:
        return None, "neither ramp starts at an edge of the clip", details
    expected = {head, tail, head + in_ticks, tail - out_ticks}
    extra = sorted({k.at_ticks for k in points} - expected)
    if extra:
        return None, "other keyframes are mixed into the fade", {**details, "extra_at_ticks": extra}
    return {"in": in_ticks, "out": out_ticks}, "", details


FADE_PROPERTIES = ("opacity", "gain")


def fade_adopt_track_plan(project, track_id: str) -> dict:
    """Which of one track's pre-1.90 keyframe fades can become edge windows, and why the rest can't.

    The rule is the one `clip.fade_adopt` already applies (`_fade_adoption`), called once per clip
    and property, so the plan and the write can never disagree. A property with no keyframes at all
    is not mentioned: there is nothing there to move, and a whole-track report that lists every clip
    as "no fade here" would bury the ones that do have one.

    An opacity ramp on an audio asset is reported as skipped rather than turned into a command —
    the reducer refuses that combination (`INVALID_FADE`), and one bad command in the batch would
    roll the whole track back.
    """
    entries: list[dict] = []
    commands: list[dict] = []
    for clip in sorted(
        (item for item in project.clips.values() if item.track_id == track_id),
        key=lambda item: item.position_ticks,
    ):
        asset = project.assets.get(clip.asset_id)
        for prop in FADE_PROPERTIES:
            if not any(k.property == prop for k in clip.keyframes):
                continue
            if prop == "opacity" and asset is not None and asset.kind == "audio":
                entries.append(
                    {
                        "clip_id": clip.id,
                        "property": prop,
                        "skipped": "audio has no opacity to fade",
                        "asset_kind": asset.kind,
                    }
                )
                continue
            adopted, reason, details = _fade_adoption(clip, prop)
            if adopted is None:
                entries.append({"clip_id": clip.id, "property": prop, "skipped": reason, **details})
                continue
            entries.append(
                {
                    "clip_id": clip.id,
                    "property": prop,
                    "in_ticks": adopted["in"],
                    "out_ticks": adopted["out"],
                    "shape": "ease_in_out",
                    "keyframe_count": len(details["keyframes"]),
                }
            )
            commands.append({"op": "clip.fade_adopt", "clip_id": clip.id, "property": prop})
    return {
        "track_id": track_id,
        "clips": entries,
        "adopted": len(commands),
        "skipped": len(entries) - len(commands),
        "commands": commands,
    }


def _apply_mask_track(clip, points, merge: bool = True) -> None:
    """Rewrite a mask's motion from a tracked path, in one clip."""
    mask = clip.mask
    if mask is None or mask.inverted:
        raise EditorError(
            "INVALID_MASK",
            "an inverted mask keeps the outside, which tracking cannot follow",
            clip_id=clip.id,
        )
    if clip.speed_curve:
        raise EditorError(
            "INVALID_MASK",
            "a tracked mask path cannot follow a speed curve yet",
            clip_id=clip.id,
        )
    if points[-1].at_ticks > clip.duration_ticks:
        raise EditorError("INVALID_KEYFRAME", "tracked points exceed the clip", clip_id=clip.id)
    offset = clip.animation_offset_ticks
    sized = points[0].width is not None
    values = {"mask_x": "center_x", "mask_y": "center_y"}
    if sized:
        values |= {"mask_width": "width", "mask_height": "height"}
    start = offset + points[0].at_ticks
    stop = offset + points[-1].at_ticks
    # A merge rewrites only the curves this run produced, over the ticks it was given. A sized run
    # joined onto a centre-only path therefore keeps the earlier centres and adds sizes from where
    # the second run starts, which is what the renderer samples anyway: a curve clamps at its ends
    # instead of inventing a value, so no mixture here needs refusing on the user's behalf.
    tracked = [
        Keyframe(
            property=name,
            at_ticks=offset + point.at_ticks,
            value=getattr(point, attribute),
            interpolation="linear",
        )
        for point in points
        for name, attribute in values.items()
    ]

    def survives(key) -> bool:
        if not merge:
            # 从头重跟 means the mask's animation comes from this run alone: a path that was sized
            # before and is re-tracked centre-only must not keep the old size curves behind it.
            return key.property not in MASK_TRACK_SIZED_CURVES
        if key.property not in values:
            return True
        return not start <= key.at_ticks <= stop

    kept = [key for key in clip.keyframes if survives(key)]
    if len(kept) + len(tracked) > CLIP_KEYFRAME_LIMIT:
        raise EditorError(
            "MASK_TRACK_BUDGET",
            f"a tracked path this long needs {len(tracked)} curves and the clip has room for "
            f"{CLIP_KEYFRAME_LIMIT - len(kept)}",
            422,
            clip_id=clip.id,
            curves_written=len(tracked),
            curves_room=CLIP_KEYFRAME_LIMIT - len(kept),
            curves_per_point=len(values),
            keyframe_limit=CLIP_KEYFRAME_LIMIT,
            frames=len(points),
        )
    clip.keyframes = kept
    clip.keyframes.extend(tracked)
    clip.keyframes.sort(key=lambda key: (key.property, key.at_ticks))
    # The drawn box describes the head of the path. A continuation joins onto an earlier segment,
    # and then the head is still that segment's first sighting — moving the box to the new window
    # would change what the frames before the first keyframe fall back to.
    first = points[0]
    update: dict[str, float] = {"center_x": first.center_x, "center_y": first.center_y}
    if sized:
        update |= {"width": first.width, "height": first.height}
    if merge:
        heads = sorted(
            {
                key.at_ticks
                for key in clip.keyframes
                if key.property == "mask_x" and key.at_ticks < start
            }
        )
        if heads:
            drawn = {key.property: key.value for key in clip.keyframes if key.at_ticks == heads[0]}
            update["center_x"] = drawn["mask_x"]
            update["center_y"] = drawn.get("mask_y", update["center_y"])
            if sized and "mask_width" in drawn:
                update["width"] = drawn["mask_width"]
                update["height"] = drawn.get("mask_height", update["height"])
    clip.mask = mask.model_copy(update=update)


def _remove_keyframes(clip, sources):
    if len(set(sources)) != len(sources):
        raise EditorError("INVALID_SELECTION", "keyframe selection must be unique")
    if any(at > clip.duration_ticks for _, at in sources):
        raise EditorError("INVALID_KEYFRAME", "keyframe lies outside the clip")
    source_ids = {(prop, at + clip.animation_offset_ticks) for prop, at in sources}
    clip.keyframes = [k for k in clip.keyframes if (k.property, k.at_ticks) not in source_ids]


def _move_keyframes(clip, moves):
    sources = [(m.keyframe.property, m.from_ticks) for m in moves]
    if len(set(sources)) != len(sources):
        raise EditorError("INVALID_SELECTION", "keyframe selection must be unique")
    if any(max(m.from_ticks, m.keyframe.at_ticks) > clip.duration_ticks for m in moves):
        raise EditorError("INVALID_KEYFRAME", "keyframe lies outside the clip")
    offset = clip.animation_offset_ticks
    source_ids = {(prop, at + offset) for prop, at in sources}
    occupied = {(k.property, k.at_ticks) for k in clip.keyframes}
    if not source_ids <= occupied:
        raise EditorError("KEYFRAME_NOT_FOUND", "select existing keyframes", 404)
    targets = [(m.keyframe.property, m.keyframe.at_ticks + offset) for m in moves]
    if len(set(targets)) != len(targets) or set(targets) & (occupied - source_ids):
        raise EditorError("KEYFRAME_COLLISION", "another keyframe occupies that time")
    _remove_keyframes(clip, sources)
    clip.keyframes.extend(
        m.keyframe.model_copy(update={"at_ticks": m.keyframe.at_ticks + offset}) for m in moves
    )
    clip.keyframes.sort(key=lambda k: (k.property, k.at_ticks))


def _all_clips(root: Project, view: Project):
    yield from root.clips.values()
    if view is not root:
        yield from view.clips.values()
    for sequence in root.sequences.values():
        yield from sequence.clips.values()


def _nest(project: Project, command) -> None:
    clips = _selected_clips(project, command.clip_ids)
    selected = set(command.clip_ids)
    if (
        command.sequence_id in project.sequences
        or command.asset_id in project.assets
        or command.clip_id in project.clips
    ):
        raise EditorError("DUPLICATE_ID", "nesting needs new sequence/asset/clip ids")
    track_ids = {c.track_id for c in clips}
    tracks = [t for t in project.tracks if t.id in track_ids]
    if not any(t.kind == "video" and not t.hidden for t in tracks):
        raise EditorError("INVALID_SELECTION", "nesting requires visible picture clips")
    for field in ("group_id", "link_id"):
        groups = {getattr(c, field) for c in clips} - {None}
        if any(
            getattr(c, field) in groups and c.id not in selected for c in project.clips.values()
        ):
            raise EditorError("INVALID_SELECTION", "select every member of a group or AV link")
    if any(
        c.transition_in and ((c.id in selected) != (c.transition_in.from_clip_id in selected))
        for c in project.clips.values()
    ):
        raise EditorError("INVALID_SELECTION", "select both ends of a transition")
    q = project.settings.frame_ticks
    for t in tracks:
        q = lcm(
            q,
            project.settings.timebase // project.settings.sample_rate
            if t.kind == "audio"
            else project.settings.frame_ticks,
        )
    start = min(c.position_ticks for c in clips) // q * q
    frame = project.settings.frame_ticks
    stop = (max(c.position_ticks + c.duration_ticks for c in clips) + frame - 1) // frame * frame
    picture_order = [t.id for t in project.tracks if t.kind == "video"]
    used = [picture_order.index(t.id) for t in tracks if t.kind == "video"]
    for c in project.clips.values():
        if c.id in selected or c.track_id not in picture_order:
            continue
        if (
            min(used) <= picture_order.index(c.track_id) <= max(used)
            and c.position_ticks < stop
            and c.position_ticks + c.duration_ticks > start
        ):
            raise EditorError(
                "NEST_LAYER_CONFLICT",
                "select overlapping picture clips between the selected layers",
            )
    track_id = "nest-" + hashlib.sha256(command.sequence_id.encode()).hexdigest()[:24]
    if any(t.id == track_id for t in project.tracks):
        raise EditorError("DUPLICATE_ID", "compound track already exists")
    top = picture_order[max(used)]
    insert = next(i for i, t in enumerate(project.tracks) if t.id == top) + 1
    project.tracks.insert(insert, Track(id=track_id, kind="video", name=command.name[:128]))
    project.sequences[command.sequence_id] = Sequence(
        id=command.sequence_id,
        name=command.name,
        duration_ticks=stop - start,
        tracks=[t.model_copy(deep=True) for t in tracks],
        clips={
            c.id: c.model_copy(update={"position_ticks": c.position_ticks - start}, deep=True)
            for c in clips
        },
    )
    project.assets[command.asset_id] = Asset(
        id=command.asset_id,
        kind="sequence",
        sequence_id=command.sequence_id,
        label=command.name,
        reference=f"sequence://{command.sequence_id}",
        duration_ticks=stop - start,
    )
    for c in clips:
        del project.clips[c.id]
    project.clips[command.clip_id] = Clip(
        id=command.clip_id,
        asset_id=command.asset_id,
        track_id=track_id,
        position_ticks=start,
        duration_ticks=stop - start,
    )


def link_status(project: Project) -> dict:
    """Report source phase, timeline placement and length independently of selection."""
    links: dict[str, list[Clip]] = {}
    for clip in project.clips.values():
        if clip.link_id:
            links.setdefault(clip.link_id, []).append(clip)
    result = {}
    for link_id, members in links.items():
        anchor = min(members, key=lambda c: (project.assets[c.asset_id].kind != "video", c.id))
        baseline = anchor.source_in_ticks - anchor.link_source_offset_ticks
        result[link_id] = {
            "clip_ids": [c.id for c in members],
            "synchronized": all(
                c.position_ticks == anchor.position_ticks
                and c.duration_ticks == anchor.duration_ticks
                and c.speed_percent == anchor.speed_percent
                and [point.model_dump() for point in c.speed_curve or []]
                == [point.model_dump() for point in anchor.speed_curve or []]
                and c.source_in_ticks - c.link_source_offset_ticks == baseline
                for c in members
            ),
            "anchor_clip_id": anchor.id,
            "differences": {
                c.id: {
                    "position_ticks": c.position_ticks - anchor.position_ticks,
                    "source_ticks": c.source_in_ticks - c.link_source_offset_ticks - baseline,
                    "duration_ticks": c.duration_ticks - anchor.duration_ticks,
                    "speed_percent": c.speed_percent - anchor.speed_percent,
                }
                for c in members
            },
        }
    return result


def _associate(project: Project, command: Command) -> None:
    members = _selected_clips(project, command.clip_ids)
    field = "group_id" if command.op == "clips.group" else "link_id"
    value = getattr(command, field)
    if value is None:
        old_ids = {getattr(c, field) for c in members} - {None}
        members = (
            _selected_clips(
                project, [c.id for c in project.clips.values() if getattr(c, field) in old_ids]
            )
            if old_ids
            else members
        )
    else:
        if len(members) < 2:
            raise EditorError("INVALID_SELECTION", "select at least two clips")
        selected = set(command.clip_ids)
        if any(getattr(c, field) == value and c.id not in selected for c in project.clips.values()):
            raise EditorError("DUPLICATE_ID", "association id is already in use")
        if field == "link_id":
            if any(c.asset_id not in project.assets for c in members):
                raise EditorError("MISSING_REFERENCE", "register the assets before linking")
            if {project.assets[c.asset_id].kind for c in members} != {"video", "audio"}:
                raise EditorError("INVALID_AV_LINK", "link timed video and audio clips")
            anchor = members[0]
            if any(
                (c.position_ticks, c.duration_ticks, c.speed_percent)
                != (anchor.position_ticks, anchor.duration_ticks, anchor.speed_percent)
                for c in members
            ):
                raise EditorError(
                    "INVALID_AV_LINK", "align position, duration and speed before linking"
                )
            for c in members:
                c.link_source_offset_ticks = c.source_in_ticks - anchor.source_in_ticks
    for c in members:
        setattr(c, field, value)
        if field == "link_id" and value is None:
            c.link_source_offset_ticks = 0


def _repair_associations(project: Project) -> None:
    groups: dict[str, list[Clip]] = {}
    links: dict[str, list[Clip]] = {}
    for c in project.clips.values():
        if c.group_id:
            groups.setdefault(c.group_id, []).append(c)
        if c.link_id:
            links.setdefault(c.link_id, []).append(c)
    for members in groups.values():
        if len(members) < 2:
            members[0].group_id = None
    links_by_track: dict[Identifier, str] = {t.id: t.kind for t in project.tracks}
    for members in links.values():
        kinds = {project.assets[c.asset_id].kind for c in members if c.asset_id in project.assets}
        detached_mix = kinds == {"video"} and any(
            links_by_track.get(c.track_id) == "audio" for c in members
        )
        if not kinds or any(kind not in {"video", "audio"} for kind in kinds):
            clear = True
        elif detached_mix:
            clear = False
        else:
            clear = kinds != {"video", "audio"}
        if clear:
            for c in members:
                c.link_id = None
                c.link_source_offset_ticks = 0


def _trim_clip(project: Project, clip: Clip, position: int, source: int, duration: int) -> None:
    if source < 0:
        raise EditorError("SOURCE_OUT_OF_BOUNDS", "linked trim exceeds a member's source head")
    offset = clip.animation_offset_ticks + position - clip.position_ticks
    if offset < 0:
        # Extending the head freezes the first animation sample until its old start.
        clip.keyframes = [
            k.model_copy(update={"at_ticks": k.at_ticks - offset}) for k in clip.keyframes
        ]
        offset = 0
    updates: dict = {
        "position_ticks": position,
        "animation_offset_ticks": offset,
        "source_in_ticks": source,
        "duration_ticks": duration,
    }
    if clip.speed_curve:
        updates["speed_curve"] = [
            SpeedPoint.model_validate(point)
            for point in slice_curve(
                [entry.model_dump() for entry in clip.speed_curve],
                position - clip.position_ticks,
                position - clip.position_ticks + duration,
            )
        ]
    project.clips[clip.id] = clip.model_copy(update=updates)


def _neighbour(project: Project, clip: Clip, *, side: str) -> Clip | None:
    """The clip touching this one on the given side of the same track, if any."""
    edge = clip.position_ticks if side == "left" else clip.position_ticks + clip.duration_ticks
    touching = [
        other
        for other in project.clips.values()
        if other.track_id == clip.track_id
        and other.id != clip.id
        and (
            other.position_ticks + other.duration_ticks == edge
            if side == "left"
            else other.position_ticks == edge
        )
    ]
    if not touching:
        return None
    return max(touching, key=lambda other: other.position_ticks)


def _slide_clip(project: Project, clip: Clip, delta: int) -> None:
    """Slide a clip along its track, giving frames to one neighbour and taking them from the other.

    A slide is only a slide when the track keeps its length and both neighbours keep their own
    source clock, so a missing neighbour, a gap, or a clip whose length is not enough to give away
    is refused rather than half-applied. Speed curves and links are refused too: both would make
    the frames that move mean something different on each side.
    """
    if delta == 0:
        raise EditorError("INVALID_SLIDE", "a slide needs a non-zero delta", 422, clip_id=clip.id)
    if clip.speed_curve or clip.link_id:
        raise EditorError(
            "INVALID_SLIDE",
            "a clip with a speed curve or an audio link cannot be slid: trim it instead",
            422,
            clip_id=clip.id,
        )
    left = _neighbour(project, clip, side="left")
    right = _neighbour(project, clip, side="right")
    if left is None or right is None:
        raise EditorError(
            "INVALID_SLIDE",
            "a slide needs clips touching both ends of this one on the same track",
            422,
            clip_id=clip.id,
        )
    step = abs(delta)
    eaten, grown = (right, left) if delta > 0 else (left, right)
    if eaten.duration_ticks <= step:
        raise EditorError(
            "INVALID_SLIDE",
            "the neighbour being eaten into is too short for this slide",
            422,
            clip_id=eaten.id,
        )
    _trim_clip(
        project,
        eaten,
        eaten.position_ticks + (step if delta > 0 else 0),
        eaten.source_in_ticks + (step if delta > 0 else 0),
        eaten.duration_ticks - step,
    )
    _trim_clip(
        project, clip, clip.position_ticks + delta, clip.source_in_ticks, clip.duration_ticks
    )
    _trim_clip(
        project,
        grown,
        grown.position_ticks + (0 if delta > 0 else -step),
        grown.source_in_ticks + (0 if delta > 0 else -step),
        grown.duration_ticks + step,
    )


def _split_clip(project: Project, clip: Clip, at: int, right_id: str) -> None:
    _outside_transition(project, clip.track_id, at, at)
    if clip.asset_id not in project.assets:
        raise EditorError("MISSING_REFERENCE", "register the asset before splitting")
    if right_id in project.clips:
        raise EditorError("DUPLICATE_ID", "right clip id already exists")
    left_duration = at - clip.position_ticks
    if not 0 < left_duration < clip.duration_ticks:
        raise EditorError("INVALID_SPLIT", "split must be strictly inside clip")
    project.clips[clip.id] = _slice_clip(project, clip, 0, left_duration)
    project.clips[right_id] = _slice_clip(
        project, clip, left_duration, clip.duration_ticks, clip_id=right_id
    )
    # A fade belongs to an edge the audience sees. The cut made by a split is not such an edge — it
    # was one continuous shot a moment ago — so each half keeps only the window the parent had on
    # the side it inherited. Copying both windows onto both halves would dip to silence or black at
    # the cut, which is a picture the person never asked for.
    for half, side in ((clip.id, "out"), (right_id, "in")):
        envelope = project.clips[half].fade
        if envelope is None:
            continue
        for prop in ("opacity", "gain"):
            setattr(envelope, f"{prop}_{side}_ticks", 0)
        if not any(envelope.model_dump().values()):
            project.clips[half].fade = None
    _relink_outgoing(project, clip.id, right_id)


def _slice_clip(
    project: Project, clip: Clip, start: int, stop: int, *, clip_id: str | None = None
) -> Clip:
    """Preserve the source and animation clocks of a surviving interval."""
    static = project.assets[clip.asset_id].kind in {"image", "text"}
    return clip.model_copy(
        deep=True,
        update={
            "id": clip_id or clip.id,
            "position_ticks": clip.position_ticks + start,
            "source_in_ticks": clip.source_in_ticks
            + (
                0
                if static
                else start * clip.speed_percent // 100
                if not clip.speed_curve
                else consumed_source_ticks(
                    clip.model_copy(update={"duration_ticks": start}),
                    project.settings.frame_ticks
                    if next(t for t in project.tracks if t.id == clip.track_id).kind == "video"
                    else project.settings.timebase // project.settings.sample_rate,
                )
            ),
            "speed_curve": None
            if not clip.speed_curve
            else [
                SpeedPoint.model_validate(point)
                for point in slice_curve(
                    [entry.model_dump() for entry in clip.speed_curve], start, stop
                )
            ],
            "animation_offset_ticks": clip.animation_offset_ticks + start,
            "duration_ticks": stop - start,
            "transition_in": None if start else clip.transition_in,
            "link_id": (
                "link-cut-"
                + hashlib.sha256(
                    f"{clip.link_id}:{clip.position_ticks + start}".encode()
                ).hexdigest()[:32]
                if clip.link_id and clip_id and clip_id != clip.id and start
                else clip.link_id
            ),
        },
    )


def _place_clip(project: Project, command: Command) -> None:
    incoming = command.clip
    start, stop = incoming.position_ticks, incoming.position_ticks + incoming.duration_ticks
    if stop > MAX_TICKS:
        raise EditorError("TIME_OVERFLOW", "edit exceeds exact JSON integer range")
    targets = [incoming.track_id]
    if command.op == "clip.insert" and command.ripple_track_ids is not None:
        targets = command.ripple_track_ids
    if len(set(targets)) != len(targets) or incoming.track_id not in targets:
        raise EditorError(
            "INVALID_RIPPLE_TRACKS", "ripple tracks must be unique and include destination"
        )
    for track_id in targets:
        track = next((t for t in project.tracks if t.id == track_id), None)
        if track is None:
            raise EditorError("MISSING_REFERENCE", "ripple track does not exist", track_id=track_id)
        _unlocked(project, track_id)
        _outside_transition(
            project, track_id, start, start if command.op == "clip.insert" else stop
        )
        q = (
            project.settings.frame_ticks
            if track.kind == "video"
            else project.settings.timebase // project.settings.sample_rate
        )
        if start % q or incoming.duration_ticks % q:
            raise EditorError(
                "TIME_NOT_ALIGNED",
                "edit must align on every affected track",
                track_id=track_id,
                quantum_ticks=q,
            )
    # Generated ids are stable for dry-run, retries and Agent inspection.
    for clip in list(project.clips.values()):
        if clip.track_id not in targets:
            continue
        end = clip.position_ticks + clip.duration_ticks
        if command.op == "clip.insert":
            if clip.position_ticks >= start:
                if end + incoming.duration_ticks > MAX_TICKS:
                    raise EditorError("TIME_OVERFLOW", "ripple exceeds exact JSON integer range")
                clip.position_ticks += incoming.duration_ticks
                continue
            if end <= start:
                continue
            left_stop, right_start = start - clip.position_ticks, start - clip.position_ticks
        else:
            if end <= start or clip.position_ticks >= stop:
                continue
            left_stop, right_start = start - clip.position_ticks, stop - clip.position_ticks
        del project.clips[clip.id]
        if left_stop > 0:
            project.clips[clip.id] = _slice_clip(project, clip, 0, left_stop)
        if right_start < clip.duration_ticks:
            right_id = clip.id
            if left_stop > 0:
                right_id = (
                    "cut-"
                    + hashlib.sha256(f"{command.op}:{incoming.id}:{clip.id}".encode()).hexdigest()[
                        :32
                    ]
                )
                if right_id in project.clips or right_id == incoming.id:
                    raise EditorError("DUPLICATE_ID", "generated fragment id already exists")
            right = _slice_clip(project, clip, right_start, clip.duration_ticks, clip_id=right_id)
            if command.op == "clip.insert":
                right.position_ticks += incoming.duration_ticks
            project.clips[right_id] = right
            if right_id != clip.id:
                _relink_outgoing(project, clip.id, right_id)


def _shift_tail(project: Project, clip: Clip, delta: int) -> None:
    start = clip.position_ticks
    for other in project.clips.values():
        if other.track_id == clip.track_id and other.position_ticks >= start:
            if not 0 <= other.position_ticks + delta <= MAX_TICKS:
                raise EditorError("TIME_OVERFLOW", "transition edit exceeds exact clock")
            other.position_ticks += delta


def _set_transition(project: Project, right: Clip, command: Command) -> None:
    left = project.clips.get(command.from_clip_id)
    track = next(t for t in project.tracks if t.id == right.track_id)
    if not left or left.track_id != right.track_id or track.kind != "video":
        raise EditorError("INVALID_TRANSITION", "select consecutive clips on one video track")
    ordered = sorted(
        (c for c in project.clips.values() if c.track_id == track.id),
        key=lambda c: (c.position_ticks, c.id),
    )
    if ordered.index(right) == 0 or ordered[ordered.index(right) - 1].id != left.id:
        raise EditorError("INVALID_TRANSITION", "transition clips must be consecutive")
    old = right.transition_in
    prior_duration = old.duration_ticks if old else 0
    if (
        old and old.from_clip_id != left.id
    ) or left.position_ticks + left.duration_ticks - right.position_ticks != prior_duration:
        raise EditorError("INVALID_TRANSITION", "close the gap before adding a transition")
    if command.duration_ticks >= min(left.duration_ticks, right.duration_ticks):
        raise EditorError("INVALID_TRANSITION", "transition must be shorter than both clips")
    if command.duration_ticks % project.settings.frame_ticks:
        raise EditorError(
            "TIME_NOT_ALIGNED",
            "transition must align to sequence frames",
            quantum_ticks=project.settings.frame_ticks,
        )
    _shift_tail(project, right, prior_duration - command.duration_ticks)
    right.transition_in = Transition(
        from_clip_id=left.id, kind=command.kind, duration_ticks=command.duration_ticks
    )


def _relink_outgoing(project: Project, old_id: str, new_id: str) -> None:
    for clip in project.clips.values():
        if clip.transition_in and clip.transition_in.from_clip_id == old_id:
            clip.transition_in.from_clip_id = new_id


def _repair_transitions(project: Project, explicit: set[str]) -> None:
    for right in project.clips.values():
        transition = right.transition_in
        if not transition or right.id in explicit:
            continue
        left = project.clips.get(transition.from_clip_id)
        overlap = left.position_ticks + left.duration_ticks - right.position_ticks if left else 0
        if (
            not left
            or left.track_id != right.track_id
            or left.position_ticks >= right.position_ticks
            or overlap <= 0
        ):
            right.transition_in = None
        else:
            transition.duration_ticks = overlap


def _outside_transition(project: Project, track_id: str, start: int, stop: int) -> None:
    for right in project.clips.values():
        if right.track_id != track_id or not right.transition_in:
            continue
        a, b = right.position_ticks, right.position_ticks + right.transition_in.duration_ticks
        if a <= start < b if start == stop else start < b and stop > a:
            raise EditorError(
                "TRANSITION_EDIT_CONFLICT",
                "remove the transition before editing inside its overlap",
            )


def _selected_clips(project: Project, ids: list[str]) -> list[Clip]:
    if len(ids) != len(set(ids)):
        raise EditorError("INVALID_SELECTION", "clip ids must be unique")
    clips = []
    for clip_id in ids:
        clip = project.clips.get(clip_id)
        if not clip:
            raise EditorError("NOT_FOUND", "clip does not exist", 404, clip_id=clip_id)
        _unlocked(project, clip.track_id)
        clips.append(clip)
    return clips


def _merged_ranges(clips: list[Clip]) -> list[tuple[int, int]]:
    ranges = []
    for start, end in sorted(
        (c.position_ticks, c.position_ticks + c.duration_ticks) for c in clips
    ):
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(end, ranges[-1][1]))
        else:
            ranges.append((start, end))
    return ranges


def _ripple_group(project: Project, selected: list[Clip]) -> None:
    ids = {c.id for c in selected}
    for track_id in {c.track_id for c in selected}:
        removed = _merged_ranges([c for c in selected if c.track_id == track_id])
        survivors = [
            c for c in project.clips.values() if c.track_id == track_id and c.id not in ids
        ]
        retained = _merged_ranges(survivors)
        exclusive = []
        i = 0
        for start, end in removed:
            while i < len(retained) and retained[i][1] <= start:
                i += 1
            j = i
            cursor = start
            while j < len(retained) and retained[j][0] < end:
                a, b = retained[j]
                if a > cursor:
                    exclusive.append((cursor, min(a, end)))
                cursor = max(cursor, b)
                j += 1
            if cursor < end:
                exclusive.append((cursor, end))
        ends, totals = [], [0]
        for start, end in exclusive:
            ends.append(end)
            totals.append(totals[-1] + end - start)
        for clip in survivors:
            clip.position_ticks -= totals[bisect_right(ends, clip.position_ticks)]


def _unlocked(project: Project, track_id: str) -> None:
    track = next((track for track in project.tracks if track.id == track_id), None)
    if track and track.locked:
        raise EditorError("TRACK_LOCKED", "unlock the track before editing", track_id=track_id)
