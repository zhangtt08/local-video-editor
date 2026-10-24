"""Scene-change detection for one clip, plus the cut plan that splits it at shot changes.

Why not FFmpeg's `scene` score: it is a luma-only SAD. A cut between two flat colours with the
same luma — pure red `#ff0000` (Y≈76) to pure green `#008000` (Y≈75) — scores **0.0**; measured on
this machine's bundled FFmpeg 6.1.1, `scdet` reported the green→blue cut at 4.0 s and nothing at
the red→green cut at 2.0 s. Graphics, slides and flat-colour animation are exactly the material
where that happens, so this module measures **colour** instead:

* decode the clip's source range at 30 fps, scaled to 64×36 RGB (area averaging);
* the difference of each frame against the previous one is the mean absolute channel change,
  0..255 normalised to 0..1 — red→green is ≈0.50, a hard cut in real footage is typically >0.2,
  camera motion on the same downscale stays below ≈0.05;
* a frame whose difference reaches `threshold` is a cut; cuts closer than `min_scene_ms` merge
  into one (flicker), and the first/last frame of the clip are never cuts.

The detector returns source-relative seconds; `analyse` maps them onto clip-local ticks with the
constant speed folded in once. `cut_plan` turns them into ordinary `clip.split` commands, so the
reducer stays the only place that decides what a cut does to the source clock, keyframes,
transitions and links.

Why it lives next to the engine instead of the interface: the browser only has the current frame.
A client-side version would be a second, weaker detector and the two would disagree on the same
file. One detector, one plan, human and Agent both submit the same commands.
"""

from __future__ import annotations

import subprocess

from .contracts import (
    SCENE_MAX_CUTS,
    SCENE_MIN_MS_DEFAULT,
    SCENE_THRESHOLD_DEFAULT,
    SCENE_THRESHOLD_MAX,
    SCENE_THRESHOLD_MIN,
    TIMEBASE,
    EditorError,
)

SCENE_TIMEOUT = 600
THRESHOLD_FLOOR = SCENE_THRESHOLD_MIN
THRESHOLD_CEILING = SCENE_THRESHOLD_MAX
SAMPLE_FPS = 30
SAMPLE_W, SAMPLE_H = 64, 36
_FRAME_BYTES = SAMPLE_W * SAMPLE_H * 3


def _frames(ffmpeg, source, start_seconds: float, duration_seconds: float):
    """Yield raw RGB frames of the scanned window, one at a time (no whole-file buffering)."""
    argv = [
        str(ffmpeg),
        "-v",
        "error",
        "-nostdin",
        "-ss",
        f"{max(0.0, start_seconds):.6f}",
        "-t",
        f"{max(0.001, duration_seconds):.6f}",
        "-i",
        str(source),
        "-an",
        "-vf",
        f"fps={SAMPLE_FPS},scale={SAMPLE_W}:{SAMPLE_H}:flags=area,format=rgb24",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        previous: bytes | None = None
        index = 0
        while True:
            frame = process.stdout.read(_FRAME_BYTES) if process.stdout else b""
            if len(frame) < _FRAME_BYTES:
                break
            yield index, previous, frame
            previous = frame
            index += 1
        error = process.stderr.read().decode(errors="replace") if process.stderr else ""
        if process.wait(timeout=SCENE_TIMEOUT) != 0 and error.strip():
            raise EditorError(
                "SCENE_FAILED",
                f"the media engine could not read this picture: {error[-600:]}",
                502,
            )
    finally:
        for stream in (process.stdout, process.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:  # noqa: BLE001 - closing a dead pipe must not mask the real error
                pass
        try:
            process.kill()
        except Exception:  # noqa: BLE001
            pass


def _difference(previous: bytes, frame: bytes) -> float:
    """Mean absolute channel change between two RGB frames, normalised to 0..1."""
    total = 0
    for left, right in zip(previous, frame):
        total += abs(left - right)
    return total / (_FRAME_BYTES * 255)


def _detect(
    ffmpeg,
    source,
    start_seconds: float,
    duration_seconds: float,
    threshold: float,
) -> list[float]:
    """Timestamps (seconds, relative to the window) where the picture changes colour."""
    found: list[float] = []
    for index, previous, frame in _frames(ffmpeg, source, start_seconds, duration_seconds):
        if previous is None:
            continue
        if _difference(previous, frame) >= threshold:
            found.append(index / SAMPLE_FPS)
    return found


def analyse(
    ffmpeg,
    source,
    clip,
    frame_ticks: int,
    *,
    threshold: float = SCENE_THRESHOLD_DEFAULT,
    min_scene_ms: int = SCENE_MIN_MS_DEFAULT,
    from_ticks: int = 0,
    to_ticks: int | None = None,
) -> dict:
    """Find shot changes inside one clip and return them in clip-local ticks.

    Detection runs on the source range the clip actually reads, so a clip that starts mid-file or
    plays at 200% reports the cuts where the editor will see them. A constant speed is folded in as
    one division; a speed curve is refused rather than guessed at (its time mapping is not linear,
    and a wrong boundary cuts a shot in half).
    """
    if clip.speed_curve:
        raise EditorError(
            "INVALID_SCENE_TARGET",
            "a clip with a speed curve cannot be scanned for shot changes yet",
            422,
            clip_id=clip.id,
        )
    if not (THRESHOLD_FLOOR <= threshold <= THRESHOLD_CEILING):
        raise EditorError(
            "SCENE_THRESHOLD",
            f"the scene threshold has to sit inside {THRESHOLD_FLOOR}..{THRESHOLD_CEILING}",
            422,
            threshold=threshold,
        )
    end = clip.duration_ticks if to_ticks is None else min(to_ticks, clip.duration_ticks)
    start = max(0, min(from_ticks, end))
    if end - start < frame_ticks:
        raise EditorError(
            "INVALID_SCENE_TARGET",
            "the scanned range is shorter than one frame",
            422,
            clip_id=clip.id,
        )
    speed = clip.speed_percent / 100
    min_scene_ticks = max(1, min_scene_ms * TIMEBASE // 1000)
    source_start = int(clip.source_in_ticks + start * speed)
    window_ticks = int((end - start) * speed)
    seconds = _detect(
        ffmpeg,
        source,
        source_start / TIMEBASE,
        max(window_ticks, frame_ticks) / TIMEBASE,
        threshold,
    )
    cuts: list[dict] = []
    previous = -min_scene_ticks
    for value in sorted(seconds):
        # Source time -> clip-local time is one division by the constant speed.
        local = start + int(round(value * TIMEBASE / speed))
        # Round onto the frame grid, inward from both edges: a cut never lands on the first or the
        # last frame of the clip (a zero-length piece is not a shot).
        snapped = int(round(local / frame_ticks)) * frame_ticks
        snapped = max(frame_ticks, min(end - frame_ticks, snapped))
        if snapped - previous < min_scene_ticks:
            continue
        previous = snapped
        cuts.append({"at_ticks": snapped, "source_seconds": round(value, 6)})
        if len(cuts) >= SCENE_MAX_CUTS:
            break
    return {
        "threshold": threshold,
        "min_scene_ms": min_scene_ms,
        "speed_percent": clip.speed_percent,
        "duration_ticks": clip.duration_ticks,
        "scan": {"from_ticks": start, "to_ticks": end},
        "cuts": cuts,
        "truncated": len(cuts) >= SCENE_MAX_CUTS,
    }


def cut_plan(clip, cuts: list[dict]) -> list[dict]:
    """Turn cut points into ordinary `clip.split` commands, applied right to left.

    Right to left keeps every earlier cut at the coordinate the scanner reported: each split only
    changes the coordinate system of what follows it. Ids are derived from the clip id and the cut
    index so a retried plan lands on the same pieces instead of minting new ones.
    """
    commands: list[dict] = []
    for number, cut in enumerate(sorted(cuts, key=lambda item: -item["at_ticks"])):
        local = int(cut["at_ticks"])
        if local <= 0 or local >= clip.duration_ticks:
            continue
        commands.append(
            {
                "op": "clip.split",
                "clip_id": clip.id,
                "at_ticks": clip.position_ticks + local,
                "right_clip_id": f"{clip.id}-shot{number:02d}",
            }
        )
    return commands
