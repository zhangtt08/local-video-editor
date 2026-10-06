"""Turn the markers on the ruler into cut points.

Markers are placed by a human (M at the playhead) or by an Agent (`marker.set`), and the point of
keeping them is that a beat mark becomes a decision about the footage. This module only translates
marker ticks into the ordinary `clip.split` commands the interface already sends, so the reducer
stays the single authority on what a split does to the source clock, keyframes, transitions and
links. Callers submit the plan as one batch.
"""

from .contracts import Project, project_content_ticks


def split_plan(project: Project, track_ids: list[str] | None = None) -> dict:
    """Plan a split for every marker that falls strictly inside a clip.

    A marker on a clip edge, or over empty ruler, plans nothing rather than producing a zero-length
    piece; a marker closer than one frame to an edge is dropped for the same reason. Splits for one
    clip are emitted right to left so each earlier marker still refers to the coordinates the clip
    actually has at that moment.
    """
    frame = project.settings.frame_ticks
    wanted = None if track_ids is None else set(track_ids)
    ticks = sorted({marker.at_ticks for marker in project.markers})
    commands: list[dict] = []
    used: set[int] = set()
    clips = 0
    for clip in sorted(project.clips.values(), key=lambda item: (item.position_ticks, item.id)):
        if wanted is not None and clip.track_id not in wanted:
            continue
        start, stop = clip.position_ticks, clip.position_ticks + clip.duration_ticks
        inside = [tick for tick in ticks if start + frame <= tick <= stop - frame]
        if not inside:
            continue
        clips += 1
        for number, tick in enumerate(sorted(inside, reverse=True)):
            commands.append(
                {
                    "op": "clip.split",
                    "clip_id": clip.id,
                    "at_ticks": tick,
                    "right_clip_id": f"{clip.id}-m{number}",
                }
            )
            used.add(tick)
    return {
        "markers": len(ticks),
        "splits": len(commands),
        "clips": clips,
        "unused": [tick for tick in ticks if tick not in used],
        "content_ticks": project_content_ticks(project),
        "commands": commands,
    }
