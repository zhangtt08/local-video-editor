"""Four-point editing: two source points and two destination points become ordinary commands.

DaVinci and Premiere both let an editor say "play this part of the clip in that part of the
timeline". The engine has insert and overwrite already; what was missing is a place that takes the
four integers, decides whether the source has to be trimmed or re-timed, and hands back the same
`clip.insert` / `clip.overwrite` commands a human or an Agent would otherwise compute by hand. No
new timeline state, and the reducer stays the only place that decides what a legal edit is.
"""

from typing import Literal

from .contracts import TIMEBASE, Clip, EditorError, Project, Ticks


def _frames(value: int, frame: int, label: str) -> int:
    if value % frame:
        raise EditorError(
            "INVALID_FOUR_POINT",
            f"{label} has to sit on a whole frame (multiple of {frame} ticks)",
            422,
            value=value,
        )
    return value


def plan(
    project: Project,
    *,
    asset_id: str,
    track_id: str,
    clip_id: str,
    source_in_ticks: int,
    source_out_ticks: int,
    dest_in_ticks: int,
    dest_out_ticks: int,
    fit: Literal["trim", "speed", "auto"] = "trim",
    mode: Literal["insert", "overwrite"] = "insert",
    ripple_track_ids: list[str] | None = None,
) -> tuple[list[dict], dict]:
    """Translate four points into commands, or refuse with the reason.

    Returns `(commands, notes)`; `notes` carries the measured lengths so the caller can show what
    the fit actually did instead of what was asked for.
    """
    frame = project.settings.frame_ticks
    asset = project.assets.get(asset_id)
    if asset is None:
        raise EditorError("NOT_FOUND", "asset does not exist", 404, asset_id=asset_id)
    verified = asset.verified
    if verified is None:
        raise EditorError(
            "UNVERIFIED_ASSET",
            "four-point editing needs a media record the engine probed itself",
            422,
            asset_id=asset_id,
        )
    track = next((item for item in project.tracks if item.id == track_id), None)
    if track is None:
        raise EditorError("NOT_FOUND", "track does not exist", 404, track_id=track_id)
    wants_video = verified.kind in ("video", "image")
    if wants_video != (track.kind == "video"):
        raise EditorError(
            "INVALID_FOUR_POINT",
            f"a {verified.kind} asset cannot be placed on a {track.kind} track",
            422,
            track_id=track_id,
        )
    for label, value in (
        ("source in", source_in_ticks),
        ("source out", source_out_ticks),
        ("destination in", dest_in_ticks),
        ("destination out", dest_out_ticks),
    ):
        _frames(value, frame, label)
    if source_in_ticks < 0 or source_out_ticks <= source_in_ticks:
        raise EditorError(
            "INVALID_FOUR_POINT", "the source range has to be at least one frame", 422
        )
    if dest_out_ticks <= dest_in_ticks or dest_in_ticks < 0:
        raise EditorError(
            "INVALID_FOUR_POINT", "the destination range has to be at least one frame", 422
        )
    if (
        verified.kind != "image"
        and verified.duration_ticks
        and source_out_ticks > verified.duration_ticks
    ):
        raise EditorError(
            "SOURCE_OUT_OF_BOUNDS",
            f"the source range runs past the asset ({verified.duration_ticks} ticks)",
            422,
            asset_id=asset_id,
        )

    source = source_out_ticks - source_in_ticks
    destination = dest_out_ticks - dest_in_ticks
    if fit == "auto":
        # "Do what the four numbers imply": trim when the source is long, re-time when it is short.
        # The interface sends this and lets the engine decide, so no client repeats the rule.
        fit = "trim" if source > destination else "speed"
    speed_percent = 100
    consumed = source
    if source > destination:
        if fit != "trim":
            raise EditorError(
                "INVALID_FOUR_POINT",
                "fit=speed only stretches a short source into a longer destination; for a longer"
                " source use fit=trim, which drops the tail",
                422,
                source_ticks=source,
                destination_ticks=destination,
            )
        consumed = destination
        note = "trimmed"
    elif source < destination:
        if fit != "speed":
            raise EditorError(
                "INVALID_FOUR_POINT",
                f"the source range ({source / TIMEBASE:.3f} s) is shorter than the destination"
                f" ({destination / TIMEBASE:.3f} s); use fit=speed to slow it down or trim the"
                " destination",
                422,
                source_ticks=source,
                destination_ticks=destination,
            )
        speed_percent = round(100 * source / destination)
        if not 25 <= speed_percent <= 400:
            raise EditorError(
                "INVALID_FOUR_POINT",
                f"the fit needs {round(100 * source / destination)}% speed, outside the 25–400%"
                " the engine supports",
                422,
            )
        consumed = round(destination * speed_percent / 100)
        if abs(consumed - source) > frame:
            raise EditorError(
                "INVALID_FOUR_POINT",
                f"whole-percent speed cannot land on this window: {consumed} ticks would be read"
                f" instead of {source}",
                422,
            )
        note = "re-timed"
    else:
        note = "exact"

    clip = Clip(
        id=clip_id,
        asset_id=asset_id,
        track_id=track_id,
        position_ticks=Ticks(dest_in_ticks),
        duration_ticks=Ticks(destination),
        source_in_ticks=Ticks(source_in_ticks if verified.kind != "image" else 0),
        speed_percent=speed_percent,
    )
    command: dict = {"op": f"clip.{mode}", "clip": clip.model_dump()}
    if mode == "insert" and ripple_track_ids:
        command["ripple_track_ids"] = list(ripple_track_ids)
    notes = {
        "source_ticks": source,
        "destination_ticks": destination,
        "consumed_source_ticks": consumed,
        "speed_percent": speed_percent,
        "fit": fit,
        "mode": mode,
        "resolution": note,
    }
    return [command], notes
