"""Plain SubRip subtitles on the project's exact frame clock."""

import re

from .contracts import MAX_TICKS, TIMEBASE, EditorError, Project

TIMING = re.compile(
    r"^(\d{2,6}):(\d{2}):(\d{2})[,.](\d{3})\s+-->\s+"
    r"(\d{2,6}):(\d{2}):(\d{2})[,.](\d{3})$"
)


def parse_srt(body: str, frame_ticks: int, offset_ticks: int = 0) -> list[tuple[int, int, str]]:
    cues = []
    for block in re.split(r"\n\s*\n", body.lstrip("\ufeff").replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():
            lines.pop(0)
        match = TIMING.fullmatch(lines[0].strip()) if lines else None
        if not match or len(lines) < 2:
            raise EditorError("INVALID_SUBTITLE", "each cue needs a SubRip time range and text")
        values = [int(value) for value in match.groups()]
        times = []
        for i in (0, 4):
            h, m, s, ms = values[i : i + 4]
            if m >= 60 or s >= 60:
                raise EditorError("INVALID_SUBTITLE", "minutes and seconds must be below 60")
            ticks = ((h * 3600 + m * 60 + s) * 1000 + ms) * (TIMEBASE // 1000)
            times.append((ticks + offset_ticks + frame_ticks // 2) // frame_ticks * frame_ticks)
        text = re.sub(r"</?(?:b|i|u|font)(?:\s+[^>]*)?>", "", "\n".join(lines[1:]), flags=re.I)
        if max(times) > MAX_TICKS:
            raise EditorError("TIME_OVERFLOW", "subtitle time exceeds exact integer range")
        if times[1] <= times[0] or not text.strip() or len(text) > 4000 or "\x00" in text:
            raise EditorError("INVALID_SUBTITLE", "cue must have text and at least one frame")
        cues.append((times[0], times[1], text))
        if len(cues) > 2000:
            raise EditorError("SUBTITLE_LIMIT", "at most 2000 cues per import")
    return cues


def export_srt(project: Project, track_id: str) -> str:
    if not any(track.id == track_id for track in project.tracks):
        raise EditorError("NOT_FOUND", "subtitle track does not exist", 404, track_id=track_id)
    clips = sorted(
        (c for c in project.clips.values() if c.track_id == track_id and c.text),
        key=lambda c: c.position_ticks,
    )

    def stamp(ticks):
        total = (ticks * 1000 + TIMEBASE // 2) // TIMEBASE
        seconds, ms = divmod(total, 1000)
        minutes, s = divmod(seconds, 60)
        h, m = divmod(minutes, 60)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    return "\n\n".join(
        f"{i}\n{stamp(c.position_ticks)} --> {stamp(c.position_ticks + c.duration_ticks)}\n"
        f"{c.text.body}"
        for i, c in enumerate(clips, 1)
    ) + ("\n" if clips else "")
