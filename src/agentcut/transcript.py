"""What is said, where it is said, and where the holes are — in one compact read.

Why this exists: an agent that has to *look* at a video to find a sentence pays for the whole
timeline in frames, and it still cannot say where a phrase begins. The captions this engine
already landed carry exact tick ranges, so the spoken structure of a cut is already in the
project — it just was not readable as one object. `phrase_view` hands back that object: phrases
in order, the silences between them as cut candidates, and a size you can actually put in a
prompt.

`cut_plan` is the other half, and the one that makes it worth having: pick the lines you do not
want and it returns the ordinary `clip.split` / `clip.ripple_remove` / `clip.remove` commands that
delete exactly those spans across every track. Deleting a sentence is the same algebra as deleting
a silence, so this module deliberately reuses `silence.cut_plan` instead of writing a second one —
the reducer stays the only place a cut decides what it does to the source clock, keyframes,
transitions and links.
"""

from __future__ import annotations

from math import ceil, floor

from . import silence
from .contracts import TIMEBASE, EditorError

DEFAULT_MERGE_GAP_MS = 350
DEFAULT_SILENCE_MS = 600
MAX_TEXT_CHARS = 120


def _ms(ticks: int) -> float:
    return round(ticks * 1000.0 / TIMEBASE, 1)


def _snap(ticks: int, frame_ticks: int, upward: bool) -> int:
    """Land a boundary on the frame grid, outward from the hole so no frame is left orphaned."""
    if frame_ticks <= 0:
        return int(ticks)
    steps = ticks / frame_ticks
    whole = ceil(steps) if upward else floor(steps)
    return int(whole * frame_ticks)


def _caption_clips(project) -> list:
    return sorted(
        (clip for clip in project.clips.values() if clip.text is not None),
        key=lambda clip: (clip.position_ticks, clip.id),
    )


def _merge(phrases: list[dict], gap_ticks: int) -> list[dict]:
    """Join phrases a conversation would call one breath; the gap must be small and real."""
    joined: list[dict] = []
    for phrase in phrases:
        previous = joined[-1] if joined else None
        if (
            previous is not None
            and phrase["clip_ids"][0] != previous["clip_ids"][-1]
            and phrase["from_ticks"] - previous["to_ticks"] <= gap_ticks
            and len(previous["text"]) + len(phrase["text"]) <= MAX_TEXT_CHARS
        ):
            previous["to_ticks"] = max(previous["to_ticks"], phrase["to_ticks"])
            previous["text"] = f"{previous['text']} {phrase['text']}".strip()
            previous["clip_ids"].extend(phrase["clip_ids"])
            continue
        joined.append(dict(phrase, clip_ids=list(phrase["clip_ids"])))
    return joined


def phrase_view(project, *, merge_gap_ms: float = DEFAULT_MERGE_GAP_MS,
                silence_ms: float = DEFAULT_SILENCE_MS) -> dict:
    """Read the spoken shape of this timeline: phrases in order, and the holes between them.

    Nothing is decoded and nothing is written. Phrases come from the caption clips that are
    already in the project, so the answer is exactly what a person sees on the subtitle track —
    which is the point: the agent and the editor read the same statement.
    """
    merge_gap = int(merge_gap_ms * TIMEBASE / 1000)
    silence_ticks = int(silence_ms * TIMEBASE / 1000)
    raw = [
        {
            "from_ticks": clip.position_ticks,
            "to_ticks": clip.position_ticks + clip.duration_ticks,
            "text": (clip.text.body or "").strip(),
            "clip_ids": [clip.id],
        }
        for clip in _caption_clips(project)
        if (clip.text.body or "").strip()
    ]
    if not raw:
        raise EditorError(
            "TRANSCRIPT_EMPTY",
            "this timeline has no caption text to read; run the speech recognition on a clip "
            "that carries voice first",
            422,
            clips=len(project.clips),
        )
    phrases = _merge(raw, merge_gap)
    for index, phrase in enumerate(phrases, start=1):
        phrase["index"] = index
        phrase["duration_ms"] = _ms(phrase["to_ticks"] - phrase["from_ticks"])
        phrase["from_ms"] = _ms(phrase["from_ticks"])
        phrase["to_ms"] = _ms(phrase["to_ticks"])
    holes = []
    for left, right in zip(phrases, phrases[1:]):
        gap = right["from_ticks"] - left["to_ticks"]
        if gap >= silence_ticks:
            holes.append({
                "from_ticks": left["to_ticks"],
                "to_ticks": right["from_ticks"],
                "from_ms": _ms(left["to_ticks"]),
                "to_ms": _ms(right["from_ticks"]),
                "duration_ms": _ms(gap),
            })
    end = max(phrase["to_ticks"] for phrase in phrases)
    return {
        "phrases": phrases,
        "silences": holes,
        "revision": project.revision,
        "speech_ticks": sum(phrase["to_ticks"] - phrase["from_ticks"] for phrase in phrases),
        "covered_to_ticks": end,
        "phrase_count": len(phrases),
        "silence_count": len(holes),
        "caption_clips": len(raw),
        "merge_gap_ms": merge_gap_ms,
        "silence_ms": silence_ms,
    }


def _clip_problem(project, clip) -> str | None:
    """Why this clip cannot be cut here, or None. Refusing to guess is the whole point."""
    track = next((item for item in project.tracks if item.id == clip.track_id), None)
    if track is not None and track.locked:
        return f"track {track.name} is locked"
    if clip.speed_curve:
        return "a speed curve makes time non-linear inside this clip"
    return None


def cut_plan(project, spans: list[dict]) -> dict:
    """Turn "delete these lines" into ordinary commands, applied right to left.

    `spans` are absolute timeline tick ranges. Every clip they touch — picture, voice, music,
    captions — is cut at the same boundaries, so the tracks stay in step instead of drifting by
    one removed sentence. A caption clip that falls entirely inside a span is removed outright
    rather than split into a zero-length piece.

    Nothing is written here. The caller reviews `commands` and submits them as one batch, so an
    accepted cut is one revision and undoes in one step.
    """
    if not isinstance(spans, list) or not spans:
        raise EditorError("TRANSCRIPT_NO_SPANS",
                          "pass the spans to delete: [{from_ticks, to_ticks}]", 422)
    cleaned: list[tuple[int, int]] = []
    for span in spans:
        if not isinstance(span, dict):
            raise EditorError("TRANSCRIPT_NO_SPANS",
                              "each span needs from_ticks and to_ticks", 422,
                              found=type(span).__name__)
        start, stop = int(span.get("from_ticks") or 0), int(span.get("to_ticks") or 0)
        if stop <= start or start < 0:
            raise EditorError("TRANSCRIPT_SPAN",
                              "a span must move forward and cannot start before zero", 422,
                              from_ticks=start, to_ticks=stop)
        cleaned.append((start, stop))
    cleaned.sort()
    merged: list[list[int]] = [list(cleaned[0])]
    for start, stop in cleaned[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], stop)
            continue
        merged.append([start, stop])

    frame_ticks = project.settings.frame_ticks
    commands: list[dict] = []
    touched: list[dict] = []
    skipped: list[dict] = []
    cut_spans: set[int] = set()
    removed_ticks = 0
    overlapping = [
        clip for clip in project.clips.values()
        if any(clip.position_ticks < stop and clip.position_ticks + clip.duration_ticks > start
               for start, stop in merged)
    ]
    for clip in sorted(overlapping, key=lambda item: (-item.position_ticks, item.id)):
        problem = _clip_problem(project, clip)
        if problem:
            skipped.append({"clip_id": clip.id, "reason": problem})
            continue
        covered = any(
            start <= clip.position_ticks
            and clip.position_ticks + clip.duration_ticks <= stop
            for start, stop in merged
        )
        if covered and clip.text is not None:
            commands.append({"op": "clip.remove", "clip_id": clip.id})
            for index, (start, stop) in enumerate(merged):
                inside = start <= clip.position_ticks and (
                    clip.position_ticks + clip.duration_ticks <= stop
                )
                if inside:
                    cut_spans.add(index)
            touched.append({"clip_id": clip.id, "track_id": clip.track_id,
                            "removed": clip.duration_ticks, "whole": True})
            continue
        gaps: list[dict] = []
        for index, (start, stop) in enumerate(merged):
            # Clip-local, then inward onto the frame grid: `clip.split` is only legal on a frame,
            # and an agent that passes a whole-number millisecond should still get a plan.
            local_from = _snap(max(0, start - clip.position_ticks), frame_ticks, True)
            local_to = _snap(min(clip.duration_ticks, stop - clip.position_ticks),
                             frame_ticks, False)
            if local_to <= local_from:
                continue
            cut_spans.add(index)
            gaps.append({
                "from_ticks": local_from,
                "to_ticks": local_to,
                "length_ticks": local_to - local_from,
            })
        if not gaps:
            continue
        plan = silence.cut_plan(clip, gaps, edges=True)
        commands.extend(plan)
        touched.append({"clip_id": clip.id, "track_id": clip.track_id,
                        "removed": sum(gap["length_ticks"] for gap in gaps),
                        "whole": False, "commands": len(plan)})
    # `removed_ticks` is how much shorter the timeline gets, not the sum over tracks: three
    # tracks losing the same one-second sentence is one second of hole, not three.
    removed_ticks = sum(merged[index][1] - merged[index][0] for index in cut_spans)
    if not touched:
        raise EditorError(
            "TRANSCRIPT_NOTHING_TO_CUT",
            "none of these spans can be cut; every clip they touch was refused, with the reason",
            422,
            skipped=skipped,
        )
    return {
        "commands": commands,
        "spans": [{"from_ticks": start, "to_ticks": stop} for start, stop in merged],
        "clips": touched,
        "skipped": skipped,
        "removed_ticks": removed_ticks,
        "revision": project.revision,
    }
