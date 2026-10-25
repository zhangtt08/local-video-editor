"""One picture of the whole cut, with the time of every cell stated.

Why this exists: `preview_frame` shows one instant. An agent that wants to know whether a cut
*looks right* — pacing, a black frame, a caption covering a face — has to ask for N frames and
pay N round trips plus N images. A contact sheet answers that in one image, and the metadata
says which tick each cell came from, so nobody has to guess the reading order.

The cells are the shipped renderer's own frames (the same bytes `GET /v1/frame` returns), tiled
by FFmpeg. Nothing here re-implements compositing: if the frame is wrong, the sheet is wrong.
"""

from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .contracts import TIMEBASE, EditorError, Project

MIN_CELLS = 2
MAX_CELLS = 12


def pick_times(
    project: Project,
    count: int,
    *,
    from_ticks: int | None = None,
    to_ticks: int | None = None,
) -> list[int]:
    """Spread `count` frame-aligned ticks over the timeline (or over the asked-for window).

    Cells sit half a step in from each end: the very first and very last instant of a timeline
    are the two most likely places to find a black frame, and a sheet whose first cell is black
    tells you nothing you could not have read off the project.
    """
    if count < MIN_CELLS or count > MAX_CELLS:
        raise EditorError(
            "OVERVIEW_COUNT",
            f"one sheet holds between {MIN_CELLS} and {MAX_CELLS} cells; ask for a coarser "
            "sheet or take the range in two passes",
            422,
            count=count,
            minimum=MIN_CELLS,
            maximum=MAX_CELLS,
        )
    frame = project.settings.frame_ticks
    end = max(
        (clip.position_ticks + clip.duration_ticks for clip in project.clips.values()),
        default=0,
    )
    start = max(0, int(from_ticks or 0))
    stop = min(int(to_ticks) if to_ticks else end, end)
    if stop <= start:
        raise EditorError(
            "OVERVIEW_RANGE",
            "that window has nothing to look at: the end must move forward from the start and "
            "sit inside the timeline",
            422,
            from_ticks=start,
            to_ticks=stop,
            timeline_ticks=end,
        )
    span = stop - start
    step = span / count
    return [
        min(stop - frame, start + int(step * (index + 0.5))) // frame * frame
        for index in range(count)
    ]


def grid(count: int) -> tuple[int, int]:
    """A sheet that is roughly square: columns first, then the rows they need."""
    columns = math.ceil(math.sqrt(count))
    return columns, math.ceil(count / columns)


def render_overview(
    ffmpeg: str | Path,
    render: Callable[[int], bytes],
    times: list[int],
    cell_size: tuple[int, int],
) -> bytes:
    """Tile the given frames into one PNG with FFmpeg's `tile` filter.

    Every cell is the same size because every cell came out of the same renderer with the same
    project settings, so no scaling is needed here — and none is silently done either.
    """
    columns, rows = grid(len(times))
    with tempfile.TemporaryDirectory(prefix="overview-") as work:
        folder = Path(work)
        for index, at in enumerate(times):
            (folder / f"cell{index:03d}.png").write_bytes(render(at))
        done = subprocess.run(
            [
                str(ffmpeg), "-v", "error", "-y", "-nostdin",
                "-start_number", "0", "-i", str(folder / "cell%03d.png"),
                "-filter_complex", f"tile={columns}x{rows}:padding=2:margin=2:color=0x101018",
                "-frames:v", "1", str(folder / "sheet.png"),
            ],
            capture_output=True,
            timeout=120,
        )
        target = folder / "sheet.png"
        if done.returncode != 0 or not target.exists():
            raise EditorError(
                "OVERVIEW_STITCH_FAILED",
                "the sheet could not be assembled from those frames; the frames themselves are "
                "still readable one at a time",
                500,
                detail=done.stderr.decode("utf-8", "replace")[-240:],
                cells=len(times),
                cell_width=cell_size[0],
                cell_height=cell_size[1],
            )
        return target.read_bytes()


def seconds_label(ticks: int) -> str:
    """A short human time for logs and headers; the sheet itself carries no text."""
    total = ticks / TIMEBASE
    return f"{int(total // 60):02d}:{total % 60:05.2f}"
