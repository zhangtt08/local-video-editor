"""Trusted media intake: path policy, ffprobe, content hash, thumbnails, waveform.

The reducer only ever sees server-issued probe records. A client can never point an
asset at a path this service has not resolved, opened and probed.
"""

import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .contracts import TIMEBASE, EditorError, FrameRate, MediaProbe, Project, VerifiedMedia

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".ts", ".mts"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".aif", ".aiff", ".m4b"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
ALLOWED_SUFFIXES = VIDEO_SUFFIXES | AUDIO_SUFFIXES | IMAGE_SUFFIXES
THUMB_COUNT = 8
WAVEFORM_BUCKETS = 1600
THUMB_WIDTH = 320
PROBE_TIMEOUT = 120
WAVEFORM_TIMEOUT = 120
PROXY_TIMEOUT = 900
PROXY_WIDTHS = (480, 640, 960, 1280)
DEFAULT_PROXY_CACHE_BYTES = 4 << 30
DEFAULT_CACHE_BYTES = 6 << 30


def proxy_cache_limit() -> int:
    """How much disk derived playback copies may occupy. Sources and projects never count."""
    raw = os.environ.get("AGENTCUT_PROXY_CACHE_BYTES", "")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_PROXY_CACHE_BYTES
    return value if value >= 0 else DEFAULT_PROXY_CACHE_BYTES


def cache_limit_bytes() -> int:
    """The whole derived cache — filmstrip tiles, waveform peaks and playback proxies together.

    The proxy limit alone leaves the rest unbounded: tiles and peaks accumulate per content hash
    forever, so a long-running editor slowly fills the disk with data that is rebuildable anyway.
    """
    raw = os.environ.get("AGENTCUT_CACHE_BYTES", "")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_CACHE_BYTES
    return value if value >= 0 else DEFAULT_CACHE_BYTES


_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def kind_for_suffix(suffix: str) -> str:
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    raise EditorError("MEDIA_TYPE_UNSUPPORTED", f"unsupported file type: {suffix or '(none)'}")


def to_ticks(seconds: float) -> int:
    if seconds is None or seconds != seconds or seconds < 0:
        return 0
    return min(int(round(seconds * TIMEBASE)), 2**53 - 1)


def run_binary(argv: list[str], timeout: int, data_dir: Path) -> subprocess.CompletedProcess:
    """Run a bundled binary without a shell. Never accepts caller-built command lines."""
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout,
            creationflags=_NO_WINDOW,
            cwd=str(data_dir),
            stdin=subprocess.DEVNULL,
            env={**os.environ, "FFMPEG_LOGLEVEL": "error", "OMP_NUM_THREADS": "1"},
        )
    except subprocess.TimeoutExpired:
        raise EditorError("MEDIA_PROBE_TIMEOUT", "media tool timed out", 502) from None
    except FileNotFoundError:
        raise EditorError(
            "MEDIA_TOOL_MISSING", "ffmpeg/ffprobe binary is not available", 503
        ) from None


class MediaService:
    def __init__(
        self,
        db_path: Path,
        roots: list[Path],
        cache_dir: Path,
        ffmpeg: Path | None,
        ffprobe: Path | None,
        asr_dirs: list[Path] | None = None,
    ):
        self.db_path = db_path
        self.roots = [root.resolve() for root in roots if str(root)]
        self.cache_dir = cache_dir
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.asr_dirs = asr_dirs or []
        self.enabled = bool(ffmpeg and ffprobe and self.roots)
        # ponytail: serialize cache builds; use per-digest locks if intake throughput needs it.
        self._cache_lock = threading.Lock()
        cache_dir.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS media_probes(
                    id TEXT PRIMARY KEY, path TEXT NOT NULL, document TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    @property
    def media_root(self) -> Path:
        return self.roots[0]

    def asr_ready(self) -> bool:
        """True when the vosk wheel is importable and at least one model folder is on disk.

        Checked lazily and remembered, because loading the wheel is not free and the model folders
        do not appear mid-session by themselves. Any import failure means unavailable — never an
        error response: vosk's module init can raise OSError from DLL loading (measured in the
        frozen build before --collect-all), and a broken speech stack must degrade the capability,
        not take /v1/info down with it.
        """
        if getattr(self, "_asr_ready", None) is not None:
            return self._asr_ready
        try:
            import vosk  # noqa: F401
        except Exception:
            self._asr_ready = False
            return False
        from . import asr as asr_module

        self._asr_ready = bool(asr_module.available_models(self.asr_dirs))
        return self._asr_ready

    def asr_models(self) -> dict[str, str]:
        from . import asr as asr_module

        return asr_module.available_models(self.asr_dirs)

    def describe_roots(self) -> list[str]:
        return [str(root) for root in self.roots]

    @contextmanager
    def connection(self, write: bool = False):
        db = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    # ---------- path policy ----------

    def resolve_path(self, raw: str) -> tuple[Path, str]:
        if not isinstance(raw, str) or not raw.strip() or "\x00" in raw or len(raw) > 2048:
            raise EditorError("MEDIA_PATH_INVALID", "media path must be a plain absolute path")
        candidate = Path(raw.strip().strip('"'))
        if not candidate.is_absolute():
            raise EditorError(
                "MEDIA_PATH_INVALID",
                "import requires an absolute path inside one of the configured media roots",
                media_roots=self.describe_roots(),
            )
        suffix = candidate.suffix.lower()
        kind = kind_for_suffix(suffix)
        if not self.enabled:
            raise EditorError(
                "MEDIA_UNAVAILABLE",
                "media engine disabled: configure AGENTCUT_MEDIA_ROOT and ffmpeg",
                503,
            )
        try:
            real = candidate.resolve()
        except OSError:
            raise EditorError("MEDIA_PATH_INVALID", "path could not be resolved") from None
        if not real.is_file():
            raise EditorError("MEDIA_NOT_FOUND", f"no file at {real}", 404)
        inside = any(real == root or root in real.parents for root in self.roots)
        if not inside:
            raise EditorError(
                "MEDIA_NOT_ALLOWED",
                "file is outside the allowed media roots",
                403,
                path=str(real),
                media_roots=self.describe_roots(),
            )
        if real.stat().st_size <= 0:
            raise EditorError("MEDIA_EMPTY", f"file is empty: {real}", 422)
        return real, kind

    # ---------- probing ----------

    def content_hash(self, path: Path) -> tuple[str, int]:
        # ponytail: head+tail sampled hash (field name is contract); full-file hashing
        # only if identity collisions ever matter in practice.
        size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            head = handle.read(4 << 20)
            digest.update(head)
            if size > 8 << 20:
                handle.seek(max(0, size - (4 << 20)))
                digest.update(handle.read(4 << 20))
            else:
                digest.update(handle.read())
        return digest.hexdigest(), size

    def probe_stream(self, path: Path) -> dict:
        argv = [
            str(self.ffprobe),
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-show_format",
            "-show_streams",
            "-print_format",
            "json",
            str(path),
        ]
        result = run_binary(argv, PROBE_TIMEOUT, self.cache_dir)
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace")[-400:]
            raise EditorError(
                "MEDIA_PROBE_FAILED", f"ffprobe could not read this file: {detail}", 422
            )
        try:
            return json.loads(result.stdout.decode(errors="replace") or "{}")
        except ValueError:
            raise EditorError(
                "MEDIA_PROBE_FAILED", "ffprobe returned unreadable output", 502
            ) from None

    @staticmethod
    def _parse_rate(text: str) -> FrameRate | None:
        match = re.fullmatch(r"(\d+)/(\d+)", text or "")
        if not match:
            return None
        num, den = int(match.group(1)), int(match.group(2))
        if num == 0 or den == 0:
            return None
        return FrameRate(numerator=num, denominator=den)

    def _seconds(self, info: dict, stream: dict | None = None) -> float:
        for source in ((stream or {}).get("duration"), info.get("format", {}).get("duration")):
            try:
                value = float(source)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return 0.0

    def summarize(self, path: Path, kind: str) -> VerifiedMedia:
        info = self.probe_stream(path)
        video_stream = None
        audio_stream = None
        for stream in info.get("streams", []):
            codec_type = stream.get("codec_type")
            if codec_type == "video" and video_stream is None:
                video_stream = stream
            elif codec_type == "audio" and audio_stream is None:
                audio_stream = stream
        if kind == "video" and video_stream is None:
            raise EditorError("MEDIA_NO_VIDEO", "expected a video stream but found none", 422)
        if kind == "audio" and audio_stream is None:
            raise EditorError("MEDIA_NO_AUDIO", "expected an audio stream but found none", 422)
        if kind == "image":
            if video_stream is None:
                raise EditorError("MEDIA_NO_IMAGE", "could not decode this image", 422)
            rate = None
        else:
            rate = (
                self._parse_rate(video_stream.get("avg_frame_rate") or "") if video_stream else None
            )
            if rate is None:
                rate = (
                    self._parse_rate(video_stream.get("r_frame_rate") or "")
                    if video_stream
                    else None
                )
        seconds = self._seconds(info, video_stream if kind != "audio" else audio_stream)
        if kind == "image":
            seconds = 0.0
        if seconds <= 0 and kind != "image":
            raise EditorError("MEDIA_ZERO_DURATION", "source reports zero duration", 422)
        digest, size = self.content_hash(path)
        verified = VerifiedMedia(
            probe_id="probe",
            path=str(path),
            kind=kind,
            label=path.name,
            size_bytes=size,
            content_sha256=digest,
            duration_ticks=to_ticks(seconds),
            width=int(video_stream.get("width") or 0) or None if video_stream else None,
            height=int(video_stream.get("height") or 0) or None if video_stream else None,
            frame_rate=rate,
            has_audio=audio_stream is not None,
            audio_sample_rate=int(audio_stream.get("sample_rate") or 0) or None
            if audio_stream
            else None,
            audio_channels=int(audio_stream.get("channels") or 0) or None if audio_stream else None,
            video_codec=(video_stream or {}).get("codec_name"),
            audio_codec=(audio_stream or {}).get("codec_name"),
            mtime=int(path.stat().st_mtime),
            cached_at="",
        )
        return verified

    # ---------- cache: thumbnails + waveform ----------

    def cache_dir_for(self, digest: str) -> Path:
        return self.cache_dir / digest[:2] / digest

    def build_cache(self, verified: VerifiedMedia) -> dict:
        with self._cache_lock:
            return self._build_cache(verified)

    def _build_cache(self, verified: VerifiedMedia) -> dict:
        """Generate filmstrip tiles and waveform peaks once per content hash."""
        target = self.cache_dir_for(verified.content_sha256)
        target.mkdir(parents=True, exist_ok=True)
        manifest_path = target / "cache.json"
        if manifest_path.exists():
            try:
                cached = json.loads(manifest_path.read_text(encoding="utf-8"))
                if cached.get("kind") == verified.kind:
                    return cached
            except ValueError:
                pass
        cached = {"kind": verified.kind, "path": verified.path, "thumbnails": [], "waveform": []}
        if verified.kind in ("video", "image"):
            cached["thumbnails"] = self._thumbnails(verified, target)
        if verified.kind in ("video", "audio"):
            cached["waveform"] = self._waveform(verified, target)
        staging = target / "cache.json.part"
        staging.write_text(json.dumps(cached, separators=(",", ":")), encoding="utf-8")
        staging.replace(manifest_path)
        # The budget only means something if it holds without someone remembering to ask: bound the
        # cache right after growing it, protecting the entry that was just built.
        self._prune_cache_locked(cache_limit_bytes(), (verified.content_sha256,), False)
        return cached

    def _thumbnails(self, verified: VerifiedMedia, target: Path) -> list[str]:
        seconds = verified.duration_ticks / TIMEBASE
        names: list[str] = []
        count = 1 if verified.kind == "image" else THUMB_COUNT
        for index in range(count):
            name = f"tile-{index:02d}.jpg"
            out = target / name
            if not out.exists():
                seek = (
                    0.0
                    if count == 1
                    else min(seconds * (index + 0.5) / count, max(0.0, seconds - 0.04))
                )
                argv = [
                    str(self.ffmpeg),
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-ss",
                    f"{seek:.3f}",
                    "-i",
                    verified.path,
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={THUMB_WIDTH}:-2:force_original_aspect_ratio=decrease",
                    "-q:v",
                    "4",
                    str(out),
                ]
                result = run_binary(argv, 60, self.cache_dir)
                if result.returncode != 0 or not out.exists():
                    break
            names.append(name)
        return names

    def _waveform(self, verified: VerifiedMedia, target: Path) -> list[float]:
        path = target / "wave.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        seconds = verified.duration_ticks / TIMEBASE
        if seconds <= 0:
            return []
        argv = [
            str(self.ffmpeg),
            "-v",
            "error",
            "-nostdin",
            "-i",
            verified.path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ]
        try:
            process = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW
            )
        except FileNotFoundError:
            raise EditorError("MEDIA_TOOL_MISSING", "ffmpeg is not available", 503) from None
        peaks = [0.0] * WAVEFORM_BUCKETS
        total_samples = max(1, int(seconds * 8000))
        per_bucket = total_samples / WAVEFORM_BUCKETS
        seen = 0
        deadline = time.monotonic() + WAVEFORM_TIMEOUT
        try:
            while True:
                if time.monotonic() > deadline:
                    raise EditorError(
                        "MEDIA_PROBE_TIMEOUT", "waveform decoding timed out", 502
                    ) from None
                chunk = process.stdout.read(64 * 1024 - (64 * 1024) % 2)
                if not chunk:
                    break
                for offset in range(0, len(chunk), 2):
                    value = (
                        abs(int.from_bytes(chunk[offset : offset + 2], "little", signed=True))
                        / 32768
                    )
                    bucket = min(WAVEFORM_BUCKETS - 1, int(seen / per_bucket))
                    if value > peaks[bucket]:
                        peaks[bucket] = value
                    seen += 1
        finally:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if len(peaks) > 1:
            peak = max(peaks) or 1.0
            peaks = [math.pow(value / peak, 0.6) for value in peaks]
        path.write_text(json.dumps(peaks, separators=(",", ":")), encoding="utf-8")
        return peaks

    # ---------- playback proxies (derived from server-verified media only) ----------

    def proxy_paths(self, verified: VerifiedMedia, width: int) -> tuple[Path, Path]:
        folder = self.cache_dir_for(verified.content_sha256)
        return folder / f"proxy-{width}.mp4", folder / f"proxy-{width}.json"

    def proxy_state(self, verified: VerifiedMedia, width: int) -> dict:
        """What exists on disk for this content hash and width, judged by the recorded probe."""
        base = {
            "width": width,
            "source_width": verified.width or 0,
            "source_height": verified.height or 0,
            "source_sha256": verified.content_sha256,
        }
        if verified.kind != "video" or not verified.width or not verified.height:
            return {"state": "not_video", **base}
        if verified.width <= width:
            return {"state": "not_needed", **base}
        video, sidecar = self.proxy_paths(verified, width)
        if video.is_file() and sidecar.is_file():
            try:
                record = json.loads(sidecar.read_text(encoding="utf-8"))
            except ValueError:
                record = {}
            if (
                record.get("source_sha256") == verified.content_sha256
                and record.get("width") == width
                and video.stat().st_size > 0
            ):
                return {"state": "ready", **record}
            video.unlink(missing_ok=True)
            sidecar.unlink(missing_ok=True)
        return {"state": "absent", **base}

    def build_proxy(self, verified: VerifiedMedia, width: int) -> dict:
        """Transcode one verified file into a smaller always-playable copy for preview scrubbing.

        A proxy never feeds the export. It is keyed by the source content hash inside the media
        cache, so replacing the file can never serve an old proxy under a new record, and the
        recorded probe is what `proxy_state` trusts.
        """
        state = self.proxy_state(verified, width)
        if state["state"] != "absent":
            return state
        if not self.ffmpeg:
            raise EditorError("MEDIA_UNAVAILABLE", "ffmpeg is not configured", 503)
        video, sidecar = self.proxy_paths(verified, width)
        video.parent.mkdir(parents=True, exist_ok=True)
        rate = verified.frame_rate or FrameRate()
        gop = max(2, round(rate.numerator / max(1, rate.denominator) * 2))
        staging = video.with_name(f"{video.stem}.part.mp4")
        argv = [
            str(self.ffmpeg),
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            verified.path,
            "-vf",
            f"scale={width}:{verified.height}:force_original_aspect_ratio=decrease",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "27",
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(gop),
            "-sc_threshold",
            "0",
            "-r",
            f"{rate.numerator}/{rate.denominator}",
            *(("-c:a", "aac", "-b:a", "128k") if verified.has_audio else ("-an",)),
            "-sn",
            "-movflags",
            "+faststart",
            str(staging),
        ]
        with self._cache_lock:
            try:
                result = run_binary(argv, PROXY_TIMEOUT, self.cache_dir)
                if result.returncode != 0 or not staging.is_file():
                    detail = result.stderr.decode(errors="replace")[-400:]
                    raise EditorError(
                        "PROXY_FAILED", f"proxy transcode failed: {detail or 'no output'}", 502
                    )
                info = self.probe_stream(staging)
                streams = {stream.get("codec_type"): stream for stream in info.get("streams", [])}
                picture = streams.get("video") or {}
                seconds = self._seconds(info)
                frame = TIMEBASE * max(1, rate.denominator) // max(1, rate.numerator)
                if not picture or abs(to_ticks(seconds) - verified.duration_ticks) > 2 * frame:
                    raise EditorError(
                        "PROXY_FAILED",
                        "the proxy does not cover the source duration",
                        502,
                    )
                staging.replace(video)
                digest, size = self.content_hash(video)
                record = {
                    "width": width,
                    "height": int(picture["height"]),
                    "display_width": int(picture["width"]),
                    "display_height": int(picture["height"]),
                    "size_bytes": size,
                    "content_sha256": digest,
                    "source_sha256": verified.content_sha256,
                    "duration_ticks": to_ticks(seconds),
                    "frame_rate": rate.model_dump(),
                    "has_audio": "audio" in streams,
                    "video_codec": picture.get("codec_name", ""),
                    "path": str(video),
                }
                sidecar.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
                self._prune_proxies_locked(proxy_cache_limit(), protect=str(video))
            finally:
                staging.unlink(missing_ok=True)
        return {"state": "ready", **record}

    # ---------- proxy cache quota ----------

    def scan_proxies(self) -> list[dict]:
        """Every proxy on disk, most recently used first. Orphan sidecars are dropped."""
        entries: list[dict] = []
        for sidecar in sorted(self.cache_dir.rglob("proxy-*.json")):
            video = sidecar.with_name(f"{sidecar.name[:-5]}.mp4")
            if not video.is_file():
                sidecar.unlink(missing_ok=True)
                continue
            try:
                record = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                record = {}
            stat = video.stat()
            entries.append(
                {
                    "source_sha256": str(record.get("source_sha256", "")),
                    "width": int(record.get("width", 0)),
                    "size_bytes": stat.st_size,
                    "used_at": max(stat.st_atime, stat.st_mtime),
                    "path": str(video),
                }
            )
        entries.sort(key=lambda item: item["used_at"], reverse=True)
        return entries

    def proxy_inventory(self) -> dict:
        entries = self.scan_proxies()
        return {
            "limit_bytes": proxy_cache_limit(),
            "used_bytes": sum(entry["size_bytes"] for entry in entries),
            "proxies": entries,
        }

    def touch_proxy(self, verified: VerifiedMedia, width: int) -> None:
        """Mark a proxy as just used, so eviction drops the least recently served one first.

        Nanoseconds keep the modification time exactly: float seconds would perturb it, and the
        cache-hit check compares it.
        """
        video, _ = self.proxy_paths(verified, width)
        try:
            stat = video.stat()
            os.utime(video, ns=(time.time_ns(), stat.st_mtime_ns))
        except OSError:
            pass

    def _prune_proxies_locked(self, keep_bytes: int, protect: str = "") -> dict:
        """Delete the least recently used proxies until the cache fits. Never touches the source,
        thumbnails or waveforms — only derived playback copies that can be rebuilt."""
        entries = self.scan_proxies()
        used = sum(entry["size_bytes"] for entry in entries)
        removed: list[dict] = []
        for entry in reversed(entries):
            if used <= keep_bytes:
                break
            if entry["path"] == protect:
                continue
            video = Path(entry["path"])
            sidecar = video.with_suffix(".json")
            video.unlink(missing_ok=True)
            sidecar.unlink(missing_ok=True)
            used -= entry["size_bytes"]
            removed.append(
                {
                    "source_sha256": entry["source_sha256"],
                    "width": entry["width"],
                    "size_bytes": entry["size_bytes"],
                }
            )
        return {
            "limit_bytes": keep_bytes,
            "used_bytes": used,
            "removed": removed,
            "freed_bytes": sum(item["size_bytes"] for item in removed),
        }

    def prune_proxies(self, keep_bytes: int | None = None) -> dict:
        with self._cache_lock:
            return self._prune_proxies_locked(
                proxy_cache_limit() if keep_bytes is None else keep_bytes
            )

    # ---------- derived cache quota: tiles + peaks + proxies together ----------

    def scan_cache(self) -> list[dict]:
        """One entry per content hash. The digest directory is the unit because it is the unit that
        can be rebuilt: `build_cache` regenerates tiles, peaks and the manifest in one go, so a
        half-deleted directory would leave a manifest listing files that are gone."""
        entries: list[dict] = []
        for parent in sorted(self.cache_dir.glob("*")):
            if not parent.is_dir():
                continue
            for folder in sorted(parent.glob("*")):
                if not folder.is_dir():
                    continue
                files = [item for item in folder.rglob("*") if item.is_file()]
                if not files:
                    shutil.rmtree(folder, ignore_errors=True)
                    continue
                stats = [item.stat() for item in files]
                entries.append(
                    {
                        "digest": folder.name,
                        "path": str(folder),
                        "size_bytes": sum(item.st_size for item in stats),
                        "files": len(files),
                        "used_at": max(item.st_mtime for item in stats),
                        "has_proxy": any(
                            item.name.startswith("proxy-") and item.suffix == ".mp4"
                            for item in files
                        ),
                    }
                )
        entries.sort(key=lambda item: item["used_at"], reverse=True)
        return entries

    def cache_inventory(self) -> dict:
        entries = self.scan_cache()
        return {
            "limit_bytes": cache_limit_bytes(),
            "used_bytes": sum(item["size_bytes"] for item in entries),
            "entries": entries,
        }

    def _is_media_root(self, folder: Path) -> bool:
        """A registered media root is never cache, however the directories happen to be nested."""
        resolved = folder.resolve()
        return any(resolved == root or root in resolved.parents for root in self.roots)

    def prune_cache(
        self,
        max_bytes: int | None = None,
        keep: tuple[str, ...] = (),
        dry_run: bool = False,
    ) -> dict:
        budget = cache_limit_bytes() if max_bytes is None else max_bytes
        with self._cache_lock:
            return self._prune_cache_locked(budget, keep, dry_run)

    def _prune_cache_locked(
        self,
        budget: int,
        keep: tuple[str, ...] = (),
        dry_run: bool = False,
    ) -> dict:
        """Delete the least recently used derived entries until the cache fits the budget.

        Sources and project files live outside this directory and are never candidates; neither is
        anything inside a registered media root. A deleted entry comes back on the next request
        that needs it, because `cache_path` rebuilds what the manifest lost. The caller holds
        `self._cache_lock`; `prune_cache` is the public entry point.
        """
        entries = self.scan_cache()
        before = sum(item["size_bytes"] for item in entries)
        used = before
        removed: list[dict] = []
        for item in reversed(entries):
            if used <= budget:
                break
            if item["digest"] in keep or self._is_media_root(Path(item["path"])):
                continue
            removed.append(
                {
                    "digest": item["digest"],
                    "size_bytes": item["size_bytes"],
                    "files": item["files"],
                    "has_proxy": item["has_proxy"],
                }
            )
            used -= item["size_bytes"]
            if not dry_run:
                shutil.rmtree(Path(item["path"]), ignore_errors=True)
        return {
            "limit_bytes": budget,
            "dry_run": dry_run,
            "used_bytes_before": before,
            "used_bytes_after": used,
            "freed_bytes": sum(item["size_bytes"] for item in removed),
            "removed": removed,
            "kept": len(entries) - len(removed),
        }

    # ---------- probe registry (server-issued handles) ----------

    def import_file(self, raw_path: str, *, persist: bool = True) -> MediaProbe:
        started = time.time()
        path, kind = self.resolve_path(raw_path)
        verified = self.summarize(path, kind)
        cached = self.build_cache(verified)
        probe_id = uuid4().hex[:16]
        verified = verified.model_copy(
            update={"probe_id": probe_id, "cached_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        )
        document = MediaProbe(
            id=probe_id,
            verified=verified,
            thumbnails=cached["thumbnails"],
            waveform=cached["waveform"],
            cache_dir=str(self.cache_dir_for(verified.content_sha256)),
            latency_ms=int((time.time() - started) * 1000),
        )
        if persist:
            with self.connection(write=True) as db:
                db.execute(
                    "INSERT INTO media_probes(id,path,document) VALUES(?,?,?)",
                    (probe_id, verified.path, document.model_dump_json()),
                )
        return document

    def get_probe(self, probe_id: str) -> MediaProbe:
        with self.connection() as db:
            row = db.execute("SELECT document FROM media_probes WHERE id=?", (probe_id,)).fetchone()
        if row is None:
            raise EditorError("PROBE_NOT_FOUND", "unknown probe_id; import the file again", 404)
        probe = MediaProbe.model_validate_json(row["document"])
        # A probe is only trustworthy while the bytes it hashed are still there.
        path = Path(probe.verified.path)
        if not path.is_file():
            raise EditorError("MEDIA_MISSING", f"source file no longer exists: {path}", 410)
        if path.stat().st_size != probe.verified.size_bytes:
            raise EditorError(
                "MEDIA_STALE",
                "the file changed since it was imported; import it again",
                410,
                path=str(path),
            )
        return probe

    def list_probes(self) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,path,created_at FROM media_probes ORDER BY created_at DESC LIMIT 500"
            )
            return [dict(row) for row in rows]

    def render_frame(
        self, project: Project, at_ticks: int, sequence_id: str | None = None
    ) -> tuple[bytes, int]:
        from .render import compile_render_plan

        at = at_ticks // project.settings.frame_ticks * project.settings.frame_ticks
        largest = max(project.settings.width, project.settings.height)
        size = tuple(
            max(2, round(value * 128 / largest) * 2)
            for value in (project.settings.width, project.settings.height)
        )
        plan = compile_render_plan(
            project, "h264-source-quality", preview_size=size, sequence_id=sequence_id
        )
        with tempfile.TemporaryDirectory(prefix="frame-", dir=self.cache_dir) as work:
            folder = Path(work)
            for name, body in plan.text_files.items():
                (folder / name).write_text(body, encoding="utf-8")
            for name, body in plan.binary_files.items():
                (folder / name).write_bytes(body)
            if at >= plan.duration_ticks:
                argv = [
                    str(self.ffmpeg),
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=black:s={size[0]}x{size[1]}",
                    "-frames:v",
                    "1",
                    "-c:v",
                    "png",
                    "-threads",
                    "1",
                    "-f",
                    "image2pipe",
                    "pipe:1",
                ]
            else:
                # ponytail: reuse the export graph; long-timeline output seeks can be slow.
                # Add input-seek/window compilation only after profiling a real large project.
                argv = plan.frame_argv(str(self.ffmpeg), at)
            result = run_binary(argv, 15, folder)
            if result.returncode or not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
                raise EditorError(
                    "FRAME_UNAVAILABLE",
                    "could not compute the composite frame",
                    502,
                    detail=result.stderr.decode(errors="replace")[-1000:],
                )
            return result.stdout, at

    def cache_path(self, probe: MediaProbe, name: str) -> Path:
        safe = Path(name).name
        if safe not in set(probe.thumbnails) | {"wave.json", "cache.json"} or "/" in name:
            raise EditorError("MEDIA_CACHE_ENTRY_MISSING", "unknown cache entry", 404)
        path = Path(probe.cache_dir) / safe
        if not path.is_file():
            # The derived cache is allowed to be gone — pruned to fit the disk budget, or cleared by
            # the user. Rebuilding it here is what makes "rebuildable" a promise instead of a claim.
            self.build_cache(probe.verified)
        if not path.is_file():
            raise EditorError("MEDIA_CACHE_ENTRY_MISSING", "cache entry is missing", 404)
        return path
