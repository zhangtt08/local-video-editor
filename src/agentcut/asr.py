"""Offline speech recognition for one clip, handed back as an ordinary `captions.import` command.

Vosk does the listening — a small local model, no network at runtime, word-level timestamps. This
module only translates: FFmpeg resamples the clip's own source audio to 16 kHz mono, the recognizer
returns words in source seconds, and those are mapped onto clip-local ticks the same way
`silence.analyse` maps silence (linear in speed, refused on speed curves where it is not). Words are
grouped into subtitle lines and emitted as one SubRip body plus one `captions.import` command, so
the reducer stays the only place that creates the track, the text asset and the clips — the ASR
path inherits the importer's frame snapping, its 2000-cue cap, undo and dedup for free.
"""

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .contracts import TIMEBASE, EditorError

ASR_TIMEOUT = 600
RATE = 16000
MODEL_NAMES = {
    "zh": "vosk-model-small-cn-0.22",
    "en": "vosk-model-small-en-us-0.15",
}
# Line-wrapping defaults: a 16-character line stays readable at the default subtitle size, and
# four seconds is about as long as a single cue should sit on screen.
DEFAULT_MAX_CHARS = 16
DEFAULT_MAX_SECONDS = 4.0
DEFAULT_GAP_SECONDS = 0.7


def model_dirs(extra: list[Path] | None = None) -> list[Path]:
    """Where models may live: env override, next to the frozen exe, then the data directory."""
    dirs: list[Path] = []
    env = os.environ.get("AGENTCUT_ASR_MODELS", "")
    for chunk in env.split(os.pathsep):
        if chunk.strip():
            dirs.append(Path(chunk))
    if extra:
        dirs.extend(extra)
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent / "asr")
    return dirs


def available_models(dirs: list[Path]) -> dict[str, str]:
    """Languages with a usable model on disk, mapped to the model folder path."""
    found: dict[str, str] = {}
    for language, name in MODEL_NAMES.items():
        for directory in dirs:
            candidate = directory / name
            if (candidate / "am").is_dir() and (candidate / "graph").is_dir():
                found[language] = str(candidate)
                break
    return found


def _short_path(path: Path) -> Path | None:
    """The 8.3 form of a Windows path, or None when it exists but stays non-ASCII."""
    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_unicode_buffer(1024)
    if not kernel32.GetShortPathNameW(str(path), buffer, 1024):
        return None
    short = Path(buffer.value)
    return short if str(short).isascii() else None


def _loadable(path: Path) -> Path:
    """A path libvosk's C runtime can actually open, copying the model if it cannot.

    Measured on this machine: `Model()` fails on every folder whose path carries non-ASCII
    characters (the C runtime opens files in the ANSI codepage), and the 8.3 short name does not
    help when the non-ASCII part is already short, like a Chinese directory name. So the fallback
    copies the model once into the ASCII-safe ProgramData location, which also serves later runs
    from the cache; if that is unwritable the error says what to set instead of failing obscurely.
    """
    if str(path).isascii():
        return path
    if os.name == "nt":
        short = _short_path(path)
        if short is not None:
            return short
    program_data = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData"))
    cache = program_data / "AgentCut" / "asr" / path.name
    if str(cache).isascii():
        if not (cache / "am").is_dir():
            cache.mkdir(parents=True, exist_ok=True)
            shutil.copytree(path, cache, dirs_exist_ok=True)
        return cache
    raise EditorError(
        "SUBTITLES_UNAVAILABLE",
        "the model folder path contains non-ASCII characters that the speech engine cannot open; "
        f"copy {path.name} to a plain-English folder and point AGENTCUT_ASR_MODELS at it",
        503,
    )


def _recognizer(language: str, dirs: list[Path]):
    try:
        from vosk import KaldiRecognizer, Model
    except ImportError as error:
        raise EditorError(
            "SUBTITLES_UNAVAILABLE",
            "the speech engine (vosk) is not installed in this deployment",
            503,
        ) from error
    models = available_models(dirs)
    path = models.get(language)
    if path is None:
        raise EditorError(
            "SUBTITLES_MODEL_MISSING",
            f"no local model for language {language!r}; put {MODEL_NAMES[language]} in one of the "
            "model directories (env AGENTCUT_ASR_MODELS or the asr folder beside the engine)",
            422,
            language=language,
            expected_model=MODEL_NAMES[language],
            searched_dirs=[str(item) for item in dirs],
            installed_languages=sorted(models),
        )
    usable = _loadable(Path(path))
    try:
        model = Model(str(usable))
    except Exception as error:  # vosk raises bare Exception on any unreadable model
        raise EditorError(
            "SUBTITLES_UNAVAILABLE",
            f"the speech model at {usable} could not be loaded: {error}",
            503,
        ) from error
    recognizer = KaldiRecognizer(model, RATE)
    recognizer.SetWords(True)  # word timestamps are the whole point; text alone cannot place cues
    return recognizer, usable.name


def _words(
    ffmpeg: Path,
    source: Path,
    start_seconds: float,
    duration_seconds: float,
    language: str,
    dirs: list[Path],
) -> tuple[list[dict], str]:
    """Decode the clip's source audio and return recognised words in source-relative seconds."""
    recognizer, model_name = _recognizer(language, dirs)
    process = subprocess.Popen(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-nostdin",
            "-ss",
            f"{max(0.0, start_seconds):.6f}",
            "-t",
            f"{duration_seconds:.6f}",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-f",
            "s16le",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    assert process.stdout is not None
    words: list[dict] = []
    spoken = 0.0
    try:
        while True:
            chunk = process.stdout.read(RATE * 2)  # one second of 16 kHz mono s16
            if not chunk:
                break
            if recognizer.AcceptWaveform(chunk):
                spoken += _collect(recognizer.Result(), words)
        spoken += _collect(recognizer.FinalResult(), words)
    finally:
        process.stdout.close()
        rest = process.stderr.read().decode(errors="replace") if process.stderr else ""
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=30)
    if process.returncode not in (0, None):
        raise EditorError(
            "SPEECH_FAILED", f"the media engine could not read this audio: {rest[-600:]}", 502
        )
    return words, model_name


def _collect(result_json: str, words: list[dict]) -> float:
    """Append one utterance's words; return how many seconds of speech it covered."""
    utterance = json.loads(result_json)
    span = 0.0
    for word in utterance.get("result", []):
        if word.get("word") and word.get("word") != "[unk]":
            words.append({"word": word["word"], "start": word["start"], "end": word["end"]})
            span += word["end"] - word["start"]
    return span


def _lines(
    words: list[dict], *, max_chars: int, max_seconds: float, gap_seconds: float, language: str
) -> list[dict]:
    """Group consecutive words into readable lines: length, duration and pauses close a line."""
    lines: list[dict] = []
    current: list[dict] = []

    def chars(group: list[dict]) -> int:
        joined = (
            "".join(w["word"] for w in group)
            if language == "zh"
            else " ".join(w["word"] for w in group)
        )
        return len(joined)

    def join(group: list[dict]) -> str:
        return (
            "".join(w["word"] for w in group)
            if language == "zh"
            else " ".join(w["word"] for w in group)
        )

    for word in words:
        if current:
            gap = word["start"] - current[-1]["end"]
            would_last = word["end"] - current[0]["start"]
            if (
                chars(current) + len(word["word"]) + (0 if language == "zh" else 1) > max_chars
                or would_last > max_seconds
                or gap > gap_seconds
            ):
                lines.append(
                    {"text": join(current), "start": current[0]["start"], "end": current[-1]["end"]}
                )
                current = []
        current.append(word)
    if current:
        lines.append(
            {"text": join(current), "start": current[0]["start"], "end": current[-1]["end"]}
        )
    return lines


def cues_from_clip(
    ffmpeg: Path,
    source: Path,
    clip,
    frame_ticks: int,
    *,
    language: str,
    dirs: list[Path],
    max_chars: int = DEFAULT_MAX_CHARS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    gap_seconds: float = DEFAULT_GAP_SECONDS,
) -> tuple[list[dict], str]:
    """Transcribe one clip; return its cues in timeline ticks plus the model folder name.

    Source seconds map linearly onto clip-local ticks (divided by the speed percent), then the clip
    position shifts them onto the timeline; the importer snaps both ends to the frame grid. Speed
    curves are refused upstream, where the linear map is checked.
    """
    if clip.speed_curve:
        raise EditorError(
            "INVALID_CAPTIONS_TARGET",
            "a clip with a speed curve cannot be transcribed yet: time is not linear there",
            422,
            clip_id=clip.id,
        )
    speed = clip.speed_percent / 100
    words, model_name = _words(
        ffmpeg,
        source,
        clip.source_in_ticks / TIMEBASE,
        clip.duration_ticks * speed / TIMEBASE,
        language,
        dirs,
    )
    lines = _lines(
        words,
        max_chars=max_chars,
        max_seconds=max_seconds,
        gap_seconds=gap_seconds,
        language=language,
    )
    cues = []
    for line in lines:
        start = clip.position_ticks + int(line["start"] * TIMEBASE / speed)
        end = clip.position_ticks + int(line["end"] * TIMEBASE / speed)
        if end <= start:
            end = start + frame_ticks
        cues.append({"from_ticks": start, "to_ticks": end, "text": line["text"]})
    return cues, model_name


def srt_body(cues: list[dict]) -> str:
    """Render timeline-tick cues as SubRip, matching the exporter's stamp format."""

    def stamp(ticks: int) -> str:
        total = (ticks * 1000 + TIMEBASE // 2) // TIMEBASE
        seconds, ms = divmod(total, 1000)
        minutes, s = divmod(seconds, 60)
        h, m = divmod(minutes, 60)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    return "\n\n".join(
        f"{i}\n{stamp(cue['from_ticks'])} --> {stamp(cue['to_ticks'])}\n{cue['text']}"
        for i, cue in enumerate(cues, 1)
    ) + ("\n" if cues else "")


def caption_command(cues: list[dict], *, scope: str) -> dict:
    """Mint the one `captions.import` command that lands these cues.

    The ids are a digest of the scope and the cues, not random and not the request id: the same
    speech over the same clip is always the same subtitle track, so a replay reaches the receipt
    dedup with an identical payload, and re-running with a new request_id is refused by the
    reducer's DUPLICATE_ID instead of stacking an identical track. Different content — another
    clip, another language, reworded lines — mints different ids and lands a second track, exactly
    like importing another SRT.
    """
    payload = json.dumps({"scope": scope, "cues": cues}, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    # No existence check here: a replay must reach the receipt lookup with the same payload, and a
    # genuine collision is the reducer's captions.import refusing with DUPLICATE_ID.
    return {
        "op": "captions.import",
        "track_id": f"subt-{digest[:20]}",
        "asset_id": f"suba-{digest[:20]}",
        "srt": srt_body(cues),
    }
