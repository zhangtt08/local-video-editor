"""A CMX3600 edit decision list for one picture track.

Why an EDL instead of a render: a project that was cut here should be reviewable in the tools a
colourist or an online editor already owns. An EDL is the smallest interchange that every one of
them reads (Resolve, Premiere, Final Cut, Avid via conversion), and it is plain text — so the exact
cutting order, source in-points and record in-points can be diffed and tested here without another
application in the loop.

What this writes is deliberately narrow: one track, straight cuts, 100 % speed, video clips only.
Those are the only things a CMX3600 list carries without inventing syntax (transitions need `D`
records with a duration, speed changes need a time-warp comment that only some readers honour, and
gaps need black events). A clip that cannot be said honestly is refused by name instead of being
left out — an EDL that silently drops a shot is worse than no EDL.

Timecode is non-drop frames at an integer rate. A fractional rate (29.97, 23.976) needs the drop /
non-drop decision and its own arithmetic, so it is refused by name rather than rounded.
"""

from __future__ import annotations

import re

from .contracts import TIMEBASE, EditorError


def _rate_numbers(project) -> tuple[int, int]:
    rate = project.settings.frame_rate
    if rate.denominator != 1:
        raise EditorError(
            "EDL_RATE",
            "an EDL is written at whole frames per second; this timeline is "
            f"{rate.numerator}/{rate.denominator} fps. Switch the project to 24/25/30/50/60 or "
            "deliver a file instead.",
            422,
            numerator=rate.numerator,
            denominator=rate.denominator,
        )
    return rate.numerator, rate.denominator


def timecode(ticks: int, fps: int) -> str:
    """Non-drop HH:MM:SS:FF at a whole frame rate, rounded down to the frame the viewer sees."""
    frame_ticks = TIMEBASE // fps
    frames = max(0, int(ticks) // frame_ticks)
    seconds, frame = divmod(frames, fps)
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}:{frame:02d}"


def reel_name(label: str) -> str:
    """CMX reels are up to eight capitals/digits/underscores; anything else is replaced, not cut."""
    cleaned = re.sub(r"[^A-Z0-9]", "_", (label or "").upper())[:8].strip("_")
    return cleaned or "AX"


def _problem(project, clip) -> str | None:
    asset = project.assets.get(clip.asset_id)
    if asset is None or asset.kind != "video":
        return "an EDL carries picture only; this clip is not a video asset"
    if clip.speed_percent != 100:
        return "an EDL has no speed field; set the clip back to 100 % or deliver a file"
    if clip.transition_in is not None:
        return "an EDL needs a dissolve record for a transition; this clip has one"
    if clip.duration_ticks <= 0:
        return "a clip with no length has no source out-point"
    return None


def build_edl(project, track_id: str) -> dict:
    """The list for one picture track, as text plus the events it is made of."""
    track = next((item for item in project.tracks if item.id == track_id), None)
    if track is None:
        raise EditorError("NOT_FOUND", "track is not in this project", 404, track_id=track_id)
    if track.kind != "video":
        raise EditorError(
            "EDL_UNSUPPORTED",
            "an EDL lists picture; this track carries sound. Pick a picture track.",
            422,
            track_id=track_id,
        )
    clips = sorted(
        (clip for clip in project.clips.values() if clip.track_id == track_id),
        key=lambda clip: (clip.position_ticks, clip.id),
    )
    if not clips:
        raise EditorError("EDL_EMPTY", "this track has no clips to list", 422, track_id=track_id)
    refused = [
        {"clip_id": clip.id, "reason": problem}
        for clip in clips
        if (problem := _problem(project, clip)) is not None
    ]
    if refused:
        raise EditorError(
            "EDL_UNSUPPORTED",
            "this track holds edits a CMX3600 list cannot say; nothing was written. "
            "Remove or convert them, or deliver a file instead.",
            422,
            track_id=track_id,
            clips=refused,
        )
    fps, _ = _rate_numbers(project)
    events = []
    for number, clip in enumerate(clips, 1):
        asset = project.assets[clip.asset_id]
        events.append(
            {
                "number": number,
                "clip_id": clip.id,
                "reel": reel_name(asset.label),
                "source_in_ticks": clip.source_in_ticks,
                "record_in_ticks": clip.position_ticks,
                "duration_ticks": clip.duration_ticks,
                "source_in": timecode(clip.source_in_ticks, fps),
                "source_out": timecode(clip.source_in_ticks + clip.duration_ticks, fps),
                "record_in": timecode(clip.position_ticks, fps),
                "record_out": timecode(clip.position_ticks + clip.duration_ticks, fps),
                "label": asset.label,
            }
        )
    title = " ".join(project.name.replace("\r", " ").replace("\n", " ").split())[:64] or "AgentCut"
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    for event in events:
        lines.append(
            f"{event['number']:03d}  {event['reel']:<8} V     C        "
            f"{event['source_in']} {event['source_out']} {event['record_in']} {event['record_out']}"
        )
        lines.append(f"* FROM CLIP NAME: {event['label']}")
        lines.append("")
    end = max(event["record_in_ticks"] + event["duration_ticks"] for event in events)
    return {
        "track_id": track_id,
        "track_name": track.name,
        "frame_rate": fps,
        "duration_ticks": end,
        "events": events,
        "text": "\n".join(lines),
    }
