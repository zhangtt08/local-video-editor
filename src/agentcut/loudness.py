"""Loudness measurement for one clip's audio, using FFmpeg's own EBU R128 meter.

The engine never re-implements a loudness standard: `ebur128` does the measuring, and this module
turns the integrated level into one linear `effects.gain`. A linear gain is deliberate — no dynamics
processing means the browser preview and the export apply exactly the same number, and the clip's
dynamics stay as recorded.
"""

import math
import re
import subprocess
from pathlib import Path
from subprocess import run

from .contracts import EditorError

LOUDNESS_TIMEOUT = 300
DEFAULT_TARGET_LUFS = -16.0
CEILING_DBTP = -1.0
MAX_GAIN = 4.0
_MIN_GAIN = 1e-4
_INTEGRATED = re.compile(r"I:\s*(-?[\d.]+)\s*LUFS")
_PEAK = re.compile(r"Peak:\s*(-?[\d.]+)\s*dBFS")
_LRA = re.compile(r"LRA:\s*(-?[\d.]+)\s*LU")


def volume_problem(clip) -> str | None:
    """Why a single static gain would not be what the viewer hears for this clip."""
    if any(key.property == "gain" for key in clip.keyframes):
        return "this clip's volume is animated by keyframes; edit those rather than one static gain"
    return None


def measure(
    ffmpeg, source, start_seconds: float = 0.0, duration_seconds: float | None = None
) -> dict:
    """Read the integrated loudness, true peak and loudness range of a window of one file."""
    argv = [str(ffmpeg), "-hide_banner", "-v", "info", "-nostdin"]
    if start_seconds > 0:
        argv += ["-ss", f"{start_seconds:.6f}"]
    argv += ["-i", str(source)]
    if duration_seconds is not None:
        argv += ["-t", f"{duration_seconds:.6f}"]
    argv += ["-af", "ebur128=peak=true", "-vn", "-f", "null", "-"]
    process = run(argv, capture_output=True, timeout=LOUDNESS_TIMEOUT)
    text = process.stderr.decode(errors="replace")
    # Only the summary block counts: the running per-frame lines also print an `I:` that is still
    # below the absolute gate at the start of the file.
    summary = text.rsplit("Summary:", 1)[-1]
    integrated = _INTEGRATED.search(summary)
    peak = _PEAK.search(summary)
    if process.returncode != 0 or not integrated or not peak:
        raise EditorError(
            "LOUDNESS_FAILED",
            f"the media engine could not measure this audio: {text[-600:]}",
            502,
        )
    range_ = _LRA.search(summary)
    return {
        "integrated_lufs": float(integrated.group(1)),
        "true_peak_dbtp": float(peak.group(1)),
        "lra_lu": None if range_ is None else float(range_.group(1)),
    }


def normalize_gain(
    measured: dict, *, target_lufs: float = DEFAULT_TARGET_LUFS, ceiling_dbtp: float = CEILING_DBTP
) -> dict:
    """The one linear gain that lands the clip on target without crossing the true-peak ceiling."""
    integrated = measured["integrated_lufs"]
    if integrated <= -99.0:
        raise EditorError(
            "LOUDNESS_FAILED", "this audio is silent, so there is no loudness to match", 422
        )
    wanted = 10 ** ((target_lufs - integrated) / 20)
    headroom = 10 ** ((ceiling_dbtp - measured["true_peak_dbtp"]) / 20)
    gain = max(_MIN_GAIN, min(wanted, headroom, MAX_GAIN))
    limited_by = ""
    if gain < wanted - 1e-9:
        limited_by = "ceiling" if headroom < wanted else "gain_range"
    predicted = integrated + 20 * math.log10(gain)
    return {
        "gain": round(gain, 4),
        "predicted_lufs": round(predicted, 2),
        "predicted_peak_dbtp": round(measured["true_peak_dbtp"] + 20 * math.log10(gain), 2),
        "limited_by": limited_by,
        "reaches_target": abs(predicted - target_lufs) <= 0.2,
    }


PROBE_PRESET = "h264-source-quality"
PROBE_CANVAS = (64, 36)


def probe_mix(ffmpeg, project, work: Path) -> dict:
    """Render the project's audio through the real graph at a throwaway size, then measure it.

    Summing per-clip LUFS numbers would be a guess: gating, overlaps, fades, ducking and the master
    gain all move the sum. A 64x36 probe costs a second and measures the actual mix instead.
    """
    from .render import compile_render_plan

    work.mkdir(parents=True, exist_ok=True)
    plan = compile_render_plan(project, PROBE_PRESET, preview_size=PROBE_CANVAS)
    for name, body in plan.text_files.items():
        (work / name).write_text(body, encoding="utf-8")
    probe = work / "mix-probe.mp4"
    process = subprocess.run(
        plan.ffmpeg_argv(str(ffmpeg), str(probe)),
        cwd=work,
        capture_output=True,
        timeout=LOUDNESS_TIMEOUT,
    )
    if process.returncode != 0:
        text = process.stderr.decode(errors="replace")
        raise EditorError(
            "LOUDNESS_FAILED", f"the mix probe could not be rendered: {text[-600:]}", 502
        )
    try:
        return measure(ffmpeg, probe)
    finally:
        probe.unlink(missing_ok=True)


def master_plan(measured: dict, current: float, *, target_lufs: float, ceiling_dbtp: float) -> dict:
    """The master gain that lands the mix on target, and what that means for the project field."""
    plan = normalize_gain(measured, target_lufs=target_lufs, ceiling_dbtp=ceiling_dbtp)
    proposed = max(0.0, min(4.0, current * plan["gain"]))
    applied = proposed / current if current > 0 else 0.0
    predicted = measured["integrated_lufs"] + 20 * math.log10(applied) if applied > 0 else -99.0
    return {
        **plan,
        "current_master_gain": round(current, 6),
        "proposed_master_gain": round(proposed, 6),
        "predicted_lufs": round(predicted, 2),
        "reaches_target": abs(predicted - target_lufs) <= 0.5,
        "limited_by": plan["limited_by"]
        or ("" if abs(proposed - current * plan["gain"]) < 1e-9 else "gain_range"),
    }
