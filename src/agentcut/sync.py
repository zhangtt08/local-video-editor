"""Line up several camera angles by the sound they share.

Two cameras that recorded the same scene carry the same soundtrack at different clock offsets. The
honest way to find that offset without a cloud service is the one this module uses: decode a coarse
mono envelope (1 kHz PCM folded into 10 ms RMS windows, 100 numbers a second) and cross-correlate it
over the allowed range of lags. A burst of noise that lands 0.75 s later on the second file peaks
the correlation at +0.75 s — no guessing from file names or timecode metadata that may not exist.

What comes out is a plan of ordinary `clip.move` commands, so the reducer stays the only place that
decides what moving a clip does to its links and groups. A silent pair, a weak peak, or two angles
that sit on one track are refused by name instead of being aligned to a wrong offset.

This is deliberately a *sync planner*, not a multicam switcher: the editor (or the Agent) still
decides which angle is on screen, and cuts between the aligned clips with the ordinary tools.
"""

from __future__ import annotations

import math
import subprocess

from .contracts import TIMEBASE, EditorError

DECODE_RATE = 1000
HOP = 10  # samples per envelope cell: ten milliseconds at 1 kHz
MIN_OVERLAP_CELLS = 100  # two seconds of shared sound before a lag is believed
SYNC_MIN_SCORE = 0.5
SYNC_TIMEOUT = 300


def _pcm(ffmpeg, source, start_seconds: float, duration_seconds: float) -> list[int]:
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
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(DECODE_RATE),
        "-f",
        "s16le",
        "-",
    ]
    done = subprocess.run(argv, capture_output=True, timeout=SYNC_TIMEOUT)
    if done.returncode != 0:
        raise EditorError(
            "SYNC_FAILED",
            "the media engine could not read this clip's sound: "
            + done.stderr.decode(errors="replace")[-400:],
            502,
        )
    raw = done.stdout
    return [
        int.from_bytes(raw[index : index + 2], "little", signed=True)
        for index in range(0, len(raw) - 1, 2)
    ]


def envelope(samples: list[int]) -> list[float]:
    """Mean absolute amplitude per 10 ms, with the clip's own average removed.

    Removing the average is what makes a constant hum stop correlating with everything: a loud room
    tone is the same number everywhere, so it carries no position information and must not win.
    """
    cells = [
        sum(abs(value) for value in samples[index : index + HOP]) / HOP
        for index in range(0, len(samples) - HOP + 1, HOP)
    ]
    if not cells:
        return []
    average = sum(cells) / len(cells)
    return [value - average for value in cells]


def _correlation(reference: list[float], other: list[float], lag: int) -> float:
    start = max(0, -lag)
    end = min(len(reference), len(other) - lag)
    count = end - start
    if count < MIN_OVERLAP_CELLS:
        return -1.0
    # Centre inside the overlap, not over the whole file. A quiet stretch is a constant after the
    # file-wide average is removed, and two constants correlate at exactly 1.0 — which would let a
    # silent pair beat the real peak. With per-overlap centring a flat stretch has no variance and
    # scores -1; only sound that actually differs from its own mean can win.
    left_mean = sum(reference[start:end]) / count
    right_mean = sum(other[start + lag : end + lag]) / count
    cross = 0.0
    left_energy = 0.0
    right_energy = 0.0
    for index in range(start, end):
        left = reference[index] - left_mean
        right = other[index + lag] - right_mean
        cross += left * right
        left_energy += left * left
        right_energy += right * right
    if left_energy <= 1e-12 or right_energy <= 1e-12:
        return -1.0
    return cross / math.sqrt(left_energy * right_energy)


def best_lag(reference: list[float], other: list[float], max_lag: int) -> tuple[int, float]:
    """The lag with the highest normalised correlation, and that correlation."""
    best_lag_value = 0
    best_score = -1.0
    for lag in range(-max_lag, max_lag + 1):
        score = _correlation(reference, other, lag)
        if score > best_score:
            best_score = score
            best_lag_value = lag
    return best_lag_value, best_score


def lag_ticks(lag_samples: int) -> int:
    """Decoded samples (1 kHz) to timeline ticks, rounded onto the exact integer clock."""
    return int(round(lag_samples * TIMEBASE / DECODE_RATE))


def _sample_correlation(reference: list[int], other: list[int], lag: int) -> float:
    """Normalised correlation on the raw 1 kHz samples, centred over the overlap."""
    start = max(0, -lag)
    end = min(len(reference), len(other) - lag)
    count = end - start
    if count < MIN_OVERLAP_CELLS * HOP:
        return -1.0
    left_mean = sum(reference[start:end]) / count
    right_mean = sum(other[start + lag : end + lag]) / count
    cross = 0.0
    left_energy = 0.0
    right_energy = 0.0
    for index in range(start, end):
        left = reference[index] - left_mean
        right = other[index + lag] - right_mean
        cross += left * right
        left_energy += left * left
        right_energy += right * right
    if left_energy <= 1e-9 or right_energy <= 1e-9:
        return -1.0
    return cross / math.sqrt(left_energy * right_energy)


def refine(reference: list[int], other: list[int], coarse_cells: int) -> int:
    """The coarse envelope peak refined on raw samples within one cell either side.

    A 10 ms envelope cannot tell 0.73 s from 0.80 s inside one cell, and snapping that to frames put
    the angle on the wrong frame. The samples are already decoded, so the last step is cheap.
    """
    centre = coarse_cells * HOP
    best = centre
    best_score = -1.0
    for lag in range(centre - 2 * HOP, centre + 2 * HOP + 1):
        score = _sample_correlation(reference, other, lag)
        if score > best_score:
            best_score = score
            best = lag
    return best


def analyse(
    ffmpeg,
    project,
    clips: list,
    reference,
    *,
    max_offset_ms: int,
) -> dict:
    """The shared-sound offset of every other clip against the reference, in ticks."""
    frame_ticks = project.settings.frame_ticks
    max_lag = max(1, int(max_offset_ms / (HOP * 1000 / DECODE_RATE)))

    def window(clip) -> tuple[float, float]:
        speed = clip.speed_percent / 100
        return clip.source_in_ticks / TIMEBASE, clip.duration_ticks * speed / TIMEBASE

    start, length = window(reference)
    source = project.assets[reference.asset_id].verified.path
    reference_samples = _pcm(ffmpeg, source, start, length)
    reference_envelope = envelope(reference_samples)
    if len(reference_envelope) < MIN_OVERLAP_CELLS:
        raise EditorError(
            "SYNC_TARGET",
            "the reference clip is too short to hear: it needs at least two seconds of sound",
            422,
            clip_id=reference.id,
        )
    found = []
    for clip in clips:
        if clip.id == reference.id:
            continue
        start, length = window(clip)
        asset = project.assets[clip.asset_id]
        other_samples = _pcm(ffmpeg, asset.verified.path, start, length)
        other_envelope = envelope(other_samples)
        if len(other_envelope) < MIN_OVERLAP_CELLS:
            found.append(
                {
                    "clip_id": clip.id,
                    "skipped": "shorter than two seconds of sound, so there is nothing to line up",
                }
            )
            continue
        coarse, score = best_lag(reference_envelope, other_envelope, max_lag)
        lag = refine(reference_samples, other_samples, coarse)
        # A move has to land on the frame grid, so the offset is snapped here once — the plan never
        # asks the reducer for a position it is bound to refuse.
        delta = int(round(lag_ticks(lag) / frame_ticks)) * frame_ticks
        found.append(
            {
                "clip_id": clip.id,
                "offset_ticks": delta,
                "offset_frames": int(round(delta / frame_ticks)),
                "score": round(score, 4),
                "peak_at_edge": abs(lag) >= max_lag,
            }
        )
    usable = [item for item in found if "skipped" not in item]
    weakest = min((item["score"] for item in usable), default=0.0)
    if not usable:
        raise EditorError(
            "SYNC_WEAK",
            "no other clip carries at least two seconds of sound to line up against the reference",
            422,
            clips=found,
        )
    return {"reference_id": reference.id, "clips": found, "weakest_score": weakest}


def move_plan(clips: list, reference, results: list[dict]) -> tuple[list[dict], list[dict]]:
    """Ordinary `clip.move` commands, plus the ones refused for leaving the ruler."""
    by_id = {clip.id: clip for clip in clips}
    commands: list[dict] = []
    refused: list[dict] = []
    for result in results:
        if "offset_ticks" not in result:
            continue
        clip = by_id[result["clip_id"]]
        target = reference.position_ticks - result["offset_ticks"]
        if target < 0:
            refused.append(
                {
                    "clip_id": clip.id,
                    "reason": "lining this angle up would move it before zero; slide the reference "
                    "later on the ruler first",
                    "wanted_position_ticks": target,
                }
            )
            continue
        if target == clip.position_ticks:
            continue
        commands.append(
            {
                "op": "clip.move",
                "clip_id": clip.id,
                "track_id": clip.track_id,
                "position_ticks": target,
            }
        )
    return commands, refused
