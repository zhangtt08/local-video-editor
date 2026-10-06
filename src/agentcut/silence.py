"""Silence detection for one clip, plus the cut plan that removes the gaps it finds.

FFmpeg's own `silencedetect` filter does the listening; this module only maps source-relative
intervals into clip-local ticks and turns them into ordinary `clip.split` / `clip.ripple_remove`
commands. The reducer therefore stays the only place timeline rules are written, and a client that
disagrees with the plan can edit it before submitting — the commands it gets back are the same ones
the interface sends.
"""

import re
from subprocess import run

from .contracts import TIMEBASE, EditorError

SILENCE_TIMEOUT = 300
DEFAULT_THRESHOLD_DB = -35.0
DEFAULT_MIN_SILENCE_MS = 250
_EVENTS = re.compile(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)")


def _detect(
    ffmpeg,
    source,
    start_seconds: float,
    duration_seconds: float,
    threshold_db: float,
    min_seconds: float,
) -> list[tuple[float, float]]:
    """Ask FFmpeg where the audio is quiet, in seconds relative to `start_seconds`."""
    argv = [
        str(ffmpeg),
        "-v",
        "info",
        "-nostdin",
        "-ss",
        f"{max(0.0, start_seconds):.6f}",
        "-t",
        f"{duration_seconds:.6f}",
        "-i",
        str(source),
        "-vn",
        "-af",
        f"aresample=async=1:first_pts=0,silencedetect=noise={threshold_db:.1f}dB:d={min_seconds:.6f}",
        "-f",
        "null",
        "-",
    ]
    process = run(argv, capture_output=True, timeout=SILENCE_TIMEOUT)
    text = process.stderr.decode(errors="replace")
    if process.returncode != 0:
        raise EditorError(
            "SILENCE_FAILED", f"the media engine could not read this audio: {text[-600:]}", 502
        )
    found: list[tuple[float, float]] = []
    open_at: float | None = None
    for match in _EVENTS.finditer(text):
        value = float(match.group(2))
        if match.group(1) == "start":
            open_at = value
        elif open_at is not None:
            found.append((open_at, value))
            open_at = None
    if open_at is not None:
        # A run that never ended is silence to the end of what we listened to.
        found.append((open_at, duration_seconds))
    return found


def _snap(value: float, frame_ticks: int, upward: bool) -> int:
    """Round onto the frame grid, always inward, so a cut never clips the picture or the word."""
    units = value / frame_ticks
    return int(-(-units // 1) if upward else units // 1) * frame_ticks


def analyse(
    ffmpeg,
    source,
    clip,
    frame_ticks: int,
    *,
    threshold_db: float = DEFAULT_THRESHOLD_DB,
    min_silence_ms: int = DEFAULT_MIN_SILENCE_MS,
    from_ticks: int = 0,
    to_ticks: int | None = None,
) -> dict:
    """Find quiet stretches inside one clip and return them in clip-local ticks.

    Detection happens on the source media the clip actually reads, so a clip that starts mid-file or
    plays at 200% reports gaps where the editor will see them. Speed curves are refused rather than
    guessed at: their time mapping is not linear, and a wrong boundary cuts a word.
    """
    if clip.speed_curve:
        raise EditorError(
            "INVALID_SILENCE_TARGET",
            "a clip with a speed curve cannot be scanned for silence yet",
            422,
            clip_id=clip.id,
        )
    end = clip.duration_ticks if to_ticks is None else min(to_ticks, clip.duration_ticks)
    start = max(0, min(from_ticks, end))
    if end - start < frame_ticks:
        raise EditorError(
            "INVALID_SILENCE_TARGET",
            "the scanned range is shorter than one frame",
            422,
            clip_id=clip.id,
        )
    speed = clip.speed_percent / 100
    min_silence_ticks = max(1, min_silence_ms * TIMEBASE // 1000)
    window_ticks = int((end - start) * speed)
    source_start = int(clip.source_in_ticks + start * speed)
    seconds = _detect(
        ffmpeg,
        source,
        source_start / TIMEBASE,
        max(window_ticks, frame_ticks) / TIMEBASE,
        threshold_db,
        max(1, min_silence_ticks) / TIMEBASE,
    )
    gaps: list[dict] = []
    for open_at, close_at in seconds:
        # Back from source seconds to clip-local ticks, then inward onto the frame grid.
        local_from = _snap(start + open_at * TIMEBASE / speed, frame_ticks, True)
        local_to = _snap(start + close_at * TIMEBASE / speed, frame_ticks, False)
        if local_to - local_from < min_silence_ticks or local_to <= local_from:
            continue
        if gaps and local_from <= gaps[-1]["to_ticks"]:
            gaps[-1]["to_ticks"] = max(gaps[-1]["to_ticks"], local_to)
            continue
        gaps.append({"from_ticks": local_from, "to_ticks": local_to})
    kept = [gap for gap in gaps if gap["from_ticks"] > 0 and gap["to_ticks"] < clip.duration_ticks]
    edges = [gap for gap in gaps if gap not in kept]
    for gap in gaps:
        gap["length_ticks"] = gap["to_ticks"] - gap["from_ticks"]
    return {
        "gaps": kept,
        "edges": edges,
        "scanned_from_ticks": start,
        "scanned_to_ticks": end,
        "threshold_db": threshold_db,
        "min_silence_ticks": min_silence_ticks,
        "frame_ticks": frame_ticks,
        "removed_ticks": sum(gap["length_ticks"] for gap in kept),
    }


def cut_plan(clip, gaps, *, edges: bool = False) -> list[dict]:
    """Turn quiet spans into split + ripple-remove commands, applied right to left.

    Working backwards means every earlier gap keeps the coordinates the scanner reported and each
    removal shifts only what follows it — that is how a leading hole closes too. An interior span
    needs two cuts; a span touching the clip edge needs one, because removing the piece that
    touches the edge is exactly a trim with ripple. The commands are the ordinary ones the
    interface already sends, so the reducer decides what a cut does to the source clock, keyframes,
    transitions and links — this function decides nothing on its own. Callers check `unsuitable`.
    """
    commands: list[dict] = []
    minted = 0

    def split_at(local: int) -> str:
        nonlocal minted
        piece = f"{clip.id}-gap{minted}"
        minted += 1
        commands.append(
            {
                "op": "clip.split",
                "clip_id": clip.id,
                "at_ticks": clip.position_ticks + local,
                "right_clip_id": piece,
            }
        )
        return piece

    for gap in sorted(gaps, key=lambda item: -item["from_ticks"]):
        start, stop = gap["from_ticks"], gap["to_ticks"]
        leading, trailing = start <= 0, stop >= clip.duration_ticks
        if leading and trailing:
            raise EditorError(
                "INVALID_SILENCE_TARGET",
                "the whole clip is quiet, so there is nothing to keep",
                422,
                clip_id=clip.id,
            )
        if not edges and (leading or trailing):
            continue
        if trailing:
            commands.append({"op": "clip.ripple_remove", "clip_id": split_at(start)})
        elif leading:
            split_at(stop)
            commands.append({"op": "clip.ripple_remove", "clip_id": clip.id})
        else:
            split_at(stop)
            commands.append({"op": "clip.ripple_remove", "clip_id": split_at(start)})
    return commands
