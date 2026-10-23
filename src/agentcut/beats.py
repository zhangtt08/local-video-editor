"""Beat detection for one audio window, in ticks, so a marked beat becomes a cut point.

The detector is deliberately small: FFmpeg decodes the window to mono PCM once, then a short-time
RMS envelope and its positive difference are scanned for peaks. A peak is a beat only when it clears
a floor derived from the window's own loudest onset and stays away from the previous mark by the
caller's minimum gap. No model, no network, no second copy of the timeline rules — what comes back
is a list of integer ticks; `marker.set` and `marker.split` are the existing writers.

The reported BPM is a convenience, not a metronome: it is the strongest autocorrelation lag of the
same envelope, folded into 70–180, and it is `None` when the window has no periodic structure.
"""

from __future__ import annotations

import math
import sys
from array import array
from subprocess import run

from .contracts import TIMEBASE, EditorError

SAMPLE_RATE = 11_025
HOP = 256  # 23.2 ms: fine enough to place a beat on a 30 fps frame, coarse enough to stay cheap.
DECODE_TIMEOUT = 300
# The floor is a fraction of this window's strongest onset, so a quiet recording still finds its own
# beats instead of failing an absolute loudness test. `sensitivity` divides it (bigger = more
# marks).
FLOOR_FRACTION = 0.08
PEAK_WINDOW = 43  # ±0.5 s at 43 envelopes per second
MIN_BPM = 70.0
MAX_BPM = 180.0


def _decode(ffmpeg, source, start_seconds: float, duration_seconds: float) -> array:
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
        str(SAMPLE_RATE),
        "-f",
        "s16le",
        "-",
    ]
    process = run(argv, capture_output=True, timeout=DECODE_TIMEOUT)
    if process.returncode != 0:
        raise EditorError(
            "BEAT_FAILED",
            "the media engine could not decode this audio: "
            + process.stderr.decode(errors="replace")[-600:],
            502,
        )
    pcm = array("h")
    pcm.frombytes(process.stdout[: len(process.stdout) // 2 * 2])
    if sys.byteorder != "little":
        pcm.byteswap()
    return pcm


def _envelope(pcm: array) -> list[float]:
    """Log RMS per hop, then its positive difference: a note's attack is a jump, its tail is not."""
    energy: list[float] = []
    for offset in range(0, len(pcm) - HOP + 1, HOP):
        total = 0
        for value in pcm[offset : offset + HOP]:
            total += value * value
        energy.append(math.log1p(math.sqrt(total / HOP)))
    flux = [0.0]
    for index in range(1, len(energy)):
        flux.append(max(0.0, energy[index] - energy[index - 1]))
    return flux


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _timing(flux: list[float], min_gap_hops: int, sensitivity: float) -> list[int]:
    if not flux:
        return []
    loudest = max(flux)
    if loudest <= 0.0:
        return []
    floor = loudest * FLOOR_FRACTION / max(0.1, sensitivity)
    peaks: list[int] = []
    last = -min_gap_hops
    for index in range(1, len(flux) - 1):
        value = flux[index]
        if value < floor or value < flux[index - 1] or value < flux[index + 1]:
            continue
        if index - last < min_gap_hops:
            # Keep the stronger of two attacks inside the same gap; a drum roll still gets one mark
            # per gap rather than a mark on every flam.
            if peaks and value > flux[peaks[-1]]:
                peaks[-1] = index
                last = index
            continue
        peaks.append(index)
        last = index
    return peaks


def _tempo(flux: list[float]) -> float | None:
    """Strongest periodic lag of the onset envelope, folded into a musical range."""
    if len(flux) < PEAK_WINDOW * 2:
        return None
    mean = sum(flux) / len(flux)
    centred = [value - mean for value in flux]
    hop_seconds = HOP / SAMPLE_RATE
    low = max(1, int(60.0 / MAX_BPM / hop_seconds))
    high = min(len(centred) - 2, int(60.0 / MIN_BPM / hop_seconds) + 1)
    best_lag, best = 0, 0.0
    scores: dict[int, float] = {}
    for lag in range(low, high + 1):
        total = 0.0
        for index in range(lag, len(centred)):
            total += centred[index] * centred[index - lag]
        score = total / (len(centred) - lag)
        scores[lag] = score
        if score > best:
            best_lag, best = lag, score
    if best_lag == 0 or best <= 0.0:
        return None
    energy = sum(value * value for value in centred) / len(centred)
    if best < energy * 0.12:
        return None
    # A 43 Hz envelope can only name a lag in whole hops; the peak between them is where the tempo
    # actually lives. Parabolic interpolation around the best lag keeps 120 from reading 117.5.
    left, mid, right = scores.get(best_lag - 1), best, scores.get(best_lag + 1)
    lag = float(best_lag)
    if left is not None and right is not None and left - 2 * mid + right != 0:
        lag += 0.5 * (left - right) / (left - 2 * mid + right)
    bpm = 60.0 / (lag * hop_seconds)
    while bpm < MIN_BPM:
        bpm *= 2
    while bpm > MAX_BPM:
        bpm /= 2
    return round(bpm, 1)


def analyse(
    ffmpeg,
    source,
    start_seconds: float,
    duration_seconds: float,
    *,
    min_gap_ms: int = 200,
    sensitivity: float = 1.0,
) -> dict:
    """Return beat positions in seconds relative to the window start, plus an optional tempo.

    The caller owns the mapping back to timeline ticks, because only it knows whether the window
    came from an asset (1:1) or from a clip that plays at a different speed.
    """
    if duration_seconds <= 0:
        raise EditorError("BEAT_FAILED", "the analysed window is empty", 422)
    pcm = _decode(ffmpeg, source, start_seconds, duration_seconds)
    flux = _envelope(pcm)
    hops_per_second = SAMPLE_RATE / HOP
    gap_hops = max(1, round(min_gap_ms / 1000 * hops_per_second))
    seconds = [index / hops_per_second for index in _timing(flux, gap_hops, sensitivity)]
    if not seconds:
        raise EditorError(
            "BEAT_QUIET",
            "no onset in this window clears the floor: raise sensitivity or pick a louder passage",
            422,
        )
    return {
        "seconds": seconds,
        "bpm": _tempo(flux),
        "sample_rate": SAMPLE_RATE,
        "hop": HOP,
        "window_seconds": len(pcm) / SAMPLE_RATE,
    }


def ticks_for(seconds: float, frame_ticks: int) -> int:
    """Snap to the frame grid: a marker is a place a cut can land, and cuts land on frames."""
    return int(round(seconds * TIMEBASE / frame_ticks)) * frame_ticks
