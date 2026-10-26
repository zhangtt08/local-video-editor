"""Did the delivered file actually land as the plan said it would — measured on the file.

An Agent that queues a render today gets a job, an output path and a boolean
`output_checked` (which means only "something stood beside the FFmpeg that ran and agreed the file
is readable"). It then has to ffprobe and loudness-meter the file itself, which is why two of this
repo's own gates grew hand-written `ffprobe` / `ebur128` parsing — the third copy would be the
calling Agent's prompt. So the measurement moves here: one door, the engine's own instruments
(`ffprobe` for the container, `loudness.measure` for EBU R128), and the plan the job itself would
have rendered, recomputed at the job's own revision.

The answer is a verdict plus the numbers behind it. A failing check is not an exception: the
caller asked "is this delivery right", and the honest answer may be "no, by 5.6 LU".
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .contracts import EditorError, Project, RenderJob
from .loudness import measure
from .media import _NO_WINDOW

LOUDNESS_TOLERANCE_LU = 1.5
PEAK_TOLERANCE_DB = 0.5
DURATION_TOLERANCE_SECONDS = 0.25


def probe(ffprobe: Path, path: Path) -> dict[str, Any]:
    """The container's own statement: length, picture size and rate, and whether it has sound."""
    done = subprocess.run(
        [
            str(ffprobe), "-v", "error", "-show_entries", "format=duration",
            "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        creationflags=_NO_WINDOW,
    )
    if done.returncode != 0:
        raise EditorError(
            "MEDIA_MISSING",
            "读不到那个交付文件，验不下去",
            410,
            path=str(path),
            stderr=done.stderr[-300:],
        )
    payload = json.loads(done.stdout or "{}")
    streams = payload.get("streams") or [{}]
    video = streams[0] or {}
    audio = subprocess.run(
        [
            str(ffprobe), "-v", "error", "-select_streams", "a:0", "-show_entries",
            "stream=index", "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        creationflags=_NO_WINDOW,
    )
    has_audio = bool((json.loads(audio.stdout or "{}").get("streams") or []))
    return {
        "seconds": float((payload.get("format") or {}).get("duration") or 0.0),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "frame_rate": str(video.get("r_frame_rate") or ""),
        "has_audio": has_audio,
    }


def _check(name: str, expected: Any, measured: Any, ok: bool, **note: Any) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "expected": expected, "measured": measured, **note}


def verify_delivery(
    ffmpeg: Path | None,
    ffprobe: Path | None,
    job: RenderJob,
    project: Project,
    plan: dict[str, Any],
    *,
    target_lufs: float | None = None,
    ceiling_dbtp: float | None = None,
    duration_tolerance: float = DURATION_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Compare the file on disk with the plan this job queued, one instrumented check at a time.

    `plan` is the job's own compiled plan (same `plan_for` the worker uses, at the job's revision),
    so "expected" is never a number this module invented. Loudness joins the verdict only when the
    caller names a target — otherwise it is reported, because how loud a film should be stays the
    caller's decision.
    """
    checks: list[dict[str, Any]] = []
    checks.append(_check("status", "succeeded", job.status, job.status == "succeeded",
                         error_code=job.error_code))
    path = Path(job.output_path or "")
    present = path.is_file() and path.stat().st_size > 0
    checks.append(
        _check(
            "file",
            {"path": str(path), "size_bytes": job.output_size_bytes},
            {"exists": present, "size_bytes": path.stat().st_size if path.is_file() else 0},
            present,
        )
    )
    loudness: dict[str, Any] = {}
    if not present:
        checks.append(_check("container", "a readable file", "none", False,
                             note="没有可读的文件，后面的量法都无从下手"))
    else:
        if not ffprobe:
            raise RuntimeError("验交付文件要有 ffprobe 在场")
        read = probe(ffprobe, path)
        expected_seconds = float(plan.get("duration_seconds") or 0.0)
        checks.append(
            _check(
                "duration",
                expected_seconds,
                round(read["seconds"], 3),
                abs(read["seconds"] - expected_seconds) <= duration_tolerance,
                tolerance_seconds=duration_tolerance,
            )
        )
        target = str(plan.get("resolution") or "")
        got = f"{read['width']}x{read['height']}"
        checks.append(_check("resolution", target, got, (not target) or target == got))
        rate_expected = str(plan.get("frame_rate") or "")
        checks.append(
            _check(
                "frame_rate",
                rate_expected,
                read["frame_rate"],
                (not rate_expected) or rate_expected == read["frame_rate"],
            )
        )
        if read["has_audio"] and ffmpeg:
            loudness = measure(ffmpeg, path)
            measured_lufs = float(loudness.get("integrated_lufs"))
            measured_peak = float(loudness.get("true_peak_dbtp"))
            if target_lufs is None:
                checks.append(
                    _check("loudness", "报告，不判", measured_lufs, True,
                           true_peak_dbtp=measured_peak)
                )
            else:
                checks.append(
                    _check(
                        "loudness",
                        target_lufs,
                        measured_lufs,
                        abs(measured_lufs - target_lufs) <= LOUDNESS_TOLERANCE_LU,
                        tolerance_lu=LOUDNESS_TOLERANCE_LU,
                        true_peak_dbtp=measured_peak,
                    )
                )
            if ceiling_dbtp is not None:
                checks.append(
                    _check(
                        "true_peak",
                        ceiling_dbtp,
                        measured_peak,
                        measured_peak <= ceiling_dbtp + PEAK_TOLERANCE_DB,
                        tolerance_db=PEAK_TOLERANCE_DB,
                    )
                )
        elif not read["has_audio"]:
            checks.append(_check("loudness", "这一条没有声轨", "none", True))
    verdict = all(row["ok"] for row in checks)
    return {
        "job_id": job.id,
        "project_id": job.project_id,
        "revision": job.revision,
        "preset_id": job.preset_id,
        "output_path": str(path),
        "verdict": verdict,
        "checks": checks,
        "loudness": loudness or None,
        "plan": {
            key: plan.get(key)
            for key in ("duration_seconds", "resolution", "frame_rate", "inputs", "mode", "range")
        },
    }
