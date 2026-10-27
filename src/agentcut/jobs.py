"""Durable render jobs. Project state and job state live in the same SQLite file.

The heavy work runs in a separate FFmpeg process, so a render can never block an edit
transaction. Job status is persisted before and after every transition; an interrupted
render is reported as failed on restart instead of pretending it is still running.
"""

import hashlib
import json
import queue
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Row, connect
from uuid import uuid4

from .contracts import (
    TIMEBASE,
    EditorError,
    FrameRate,
    Project,
    RenderBatch,
    RenderJob,
    RenderRequest,
)
from .media import _NO_WINDOW
from .render import RenderPlan, compile_render_plan, marked_range, preset_by_id

STATUS_STEPS = ("queued", "running", "succeeded", "failed", "cancelled")
TERMINAL = ("succeeded", "failed", "cancelled")
MAX_LOG = 3000
# 1.319 的两个额度与一个槽数上限。槽数不按物理核数封顶——FFmpeg 自己会用满核，硬说「核数就等于
# 能同时渲几路」是假的保证；这里只挡住明显打不开的那个数。额度是「一个调用方最多压多少单」，
# 不是「引擎最多能干多少活」：前者是流水线互相保护，后者是这一档管不着的。
MAX_RENDER_SLOTS = 8
DEFAULT_MAX_PENDING = 64
DEFAULT_PENDING_PER_ACTOR = 16


def plan_for(
    project: Project,
    preset_id: str,
    *,
    sequence_id: str | None = None,
    fit: str = "contain",
    range_mode: str = "full",
    transparent: bool = False,
    timecode: str | None = None,
    output_frame_rate: FrameRate | None = None,
    colour_tag: str | None = None,
) -> RenderPlan:
    """One place that turns a request's `range` into the ticks the exporter trims to, so the
    render-plan preview, the queued job and the worker all read the same marks."""
    ticks = None
    if range_mode == "marks":
        ticks = marked_range(project)
        if ticks is None:
            raise EditorError(
                "INVALID_MARKS",
                "this sequence has no in/out marks, so there is no range to export",
                422,
            )
    return compile_render_plan(
        project,
        preset_id,
        sequence_id=sequence_id,
        fit=fit,
        range_ticks=ticks,
        transparent=transparent,
        timecode=timecode,
        output_frame_rate=output_frame_rate,
        colour_tag=colour_tag,
    )


# Windows reports a crashed child as its exception code, and FFmpeg dies that way without writing a
# single line to stderr. "退出码 3221225477：" with nothing after the colon is no use to a person or
# an Agent, so name what the code means and say out loud that nothing was reported.
WINDOWS_EXCEPTIONS = {
    0xC0000005: "访问越界（滤镜链里有滤镜收到了每帧都在变的画面尺寸）",
    0xC00000FD: "栈溢出（表达式嵌套过深）",
    0xC0000409: "运行时安全检查中止（同样是滤镜链越界）",
}


# 叫停一支在跑的 FFmpeg，最多等这一手这么久；等不到就换一种停法（见 `_kill`）。
KILL_TIMEOUT_SECONDS = 10


def describe_exit(return_code: int, stderr: str) -> str:
    tail = stderr.strip()[-MAX_LOG:]
    unsigned = return_code & 0xFFFFFFFF
    named = WINDOWS_EXCEPTIONS.get(unsigned)
    if named:
        head = f"FFmpeg 进程异常退出：退出码 {return_code}（0x{unsigned:08X}）{named}"
        return f"{head}；它没有留下任何错误输出" if not tail else f"{head}；最后输出：{tail}"
    if not tail:
        return f"FFmpeg 退出码 {return_code}，且没有留下任何错误输出"
    return f"FFmpeg 退出码 {return_code}：{tail}"


_FFMPEG_SUPPORT: dict[str, dict] = {}


def parse_ffmpeg_help(text: str) -> dict:
    """从 `-h full` 的自述里读出：这一份 ffmpeg 的版本号，以及它认不认长滤镜图的脚本形式。

    只数这一件事是本仓库的账，不是通用能力探测。`render.py` 在滤镜图越过 `GRAPH_SCRIPT_LIMIT`
    时把图写成文件、发 `-filter_complex_script`（Windows 的 `CreateProcess` 在 ~32 KB 上直接拒），
    而 FFmpeg 9 那一支已经没有这个选项——1.146 的装机复核就是被这句话绊住的：
    `Unrecognized option 'filter_complex_script'.`
    """
    head = next((line for line in text.splitlines() if line.startswith("ffmpeg version")), "")
    parts = head.removeprefix("ffmpeg version").split()
    return {
        "version": parts[0] if parts else "未知",
        "graph_script": "filter_complex_script" in text,
    }


def ffmpeg_support(ffmpeg: Path | None) -> dict:
    """量一次，记下来：这份 ffmpeg 是自己说的，不是我猜的。"""
    key = str(ffmpeg)
    if key not in _FFMPEG_SUPPORT:
        if ffmpeg is None:
            said = {"version": "未知", "graph_script": False, "path": ""}
        else:
            try:
                answer = subprocess.run(  # noqa: S603
                    [str(ffmpeg), "-h", "full"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                    creationflags=_NO_WINDOW,
                )
                said = parse_ffmpeg_help(f"{answer.stdout or ''}\n{answer.stderr or ''}")
            except (OSError, subprocess.SubprocessError):
                said = {"version": "跑不起来", "graph_script": False}
            said["path"] = str(ffmpeg)
        _FFMPEG_SUPPORT[key] = said
    return _FFMPEG_SUPPORT[key]


def ffprobe_beside(ffmpeg: Path | None) -> Path | None:
    """The inspector that ships next to the FFmpeg which encoded this job, or None.

    A probe found on PATH could be another build with another demuxer, so measuring our container
    with it would say nothing about what this encoder actually wrote. With no sibling the job
    reports the file as unverified instead of claiming a check it never ran.
    """
    if ffmpeg is None:
        return None
    for name in ("ffprobe.exe", "ffprobe"):
        sibling = ffmpeg.with_name(name)
        if sibling.is_file():
            return sibling
    return None


TAIL_WINDOW = 0.5


def _sequence_frames(pattern: Path) -> list[Path]:
    """这一串序列里已经落盘的帧，按编号从小到大排。

    只认 `%06d` 展开成的那一种名字（前缀、六位数字、扩展名三样都对）。同一目录里别人的文件
    不会被当成帧——把数点多了比少点更难查。
    """
    prefix, _, suffix = pattern.name.partition("%06d")
    directory = pattern.parent
    if "%06d" not in pattern.name or not directory.is_dir():
        return []
    frames: list[tuple[int, Path]] = []
    for path in directory.iterdir():
        head = path.name
        if not (
            head.startswith(prefix)
            and head.endswith(suffix)
            and len(head) > len(prefix) + len(suffix)
        ):
            continue
        middle = head[len(prefix) : len(head) - len(suffix)]
        if len(middle) == 6 and middle.isdigit():
            frames.append((int(middle), path))
    return [frame for _, frame in sorted(frames)]


def _discard_staging(pattern: Path, sequence: bool) -> None:
    """删掉这一次渲染的临时产物。序列只删自己那一串编号的文件，目录真空了才删目录。"""
    if not sequence:
        pattern.unlink(missing_ok=True)
        return
    for frame in _sequence_frames(pattern):
        frame.unlink(missing_ok=True)
    try:
        pattern.parent.rmdir()
    except OSError:
        # 里面还有别人的东西就留着：宁可剩一个空壳目录，也不动不属于这次渲染的文件。
        pass


def verify_sequence(ffmpeg: Path, ffprobe: Path, pattern: Path, plan: RenderPlan) -> str:
    """图像序列的复检数的是**文件**：一帧一个、编号连续、首尾都解得开。

    FFmpeg 写坏序列的方式不是「退出码非零」，而是少写几帧、中间断一号、最后一帧只写了个头。
    这三种都只有按期望帧数点过、并且真解过首尾才会露出来。
    """
    frames = _sequence_frames(pattern)
    prefix = pattern.name.split("%06d")[0]
    numerator, _, denominator = plan.summary["frame_rate"].partition("/")
    rate = int(numerator) / int(denominator or 1)
    expected = int(plan.duration_ticks / TIMEBASE * rate + 0.5)
    if not frames:
        raise EditorError(
            "OUTPUT_INVALID",
            f"序列目录 {pattern.parent.name}/ 里一帧都没有，FFmpeg 却说自己正常结束了",
            500,
            directory=str(pattern.parent),
        )
    if len(frames) != expected:
        raise EditorError(
            "OUTPUT_INVALID",
            f"序列该有 {expected} 帧（{plan.duration_ticks / TIMEBASE:.3f} 秒 × "
            f"{rate:g} fps），实际落盘 {len(frames)} 个文件",
            500,
            expected=expected,
            found=len(frames),
            directory=str(pattern.parent),
        )
    numbers = [int(frame.name[len(prefix) : len(prefix) + 6]) for frame in frames]
    if numbers != list(range(numbers[0], numbers[0] + expected)):
        raise EditorError(
            "OUTPUT_INVALID",
            f"序列的帧号不连续：从 {numbers[0]} 到 {numbers[-1]}，{expected} 个里缺了号",
            500,
            first=numbers[0],
            last=numbers[-1],
            directory=str(pattern.parent),
        )
    reading = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(frames[0]),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_NO_WINDOW,
        timeout=60,
    )
    if reading.returncode != 0 or '"video"' not in reading.stdout:
        raise EditorError(
            "OUTPUT_INVALID",
            f"序列第一帧 {frames[0].name} 里读不出画面流（ffprobe 退出码 {reading.returncode}）"
            + (f"：{reading.stderr.strip()[-160:]}" if reading.stderr.strip() else ""),
            500,
            file=frames[0].name,
        )
    # ffprobe 只读头，看不出「最后一帧只写了一半」；这一遍真解码，坏帧会让 ffmpeg 非零退出。
    for frame in (frames[0], frames[-1]):
        decoded = subprocess.run(
            [str(ffmpeg), "-v", "error", "-i", str(frame), "-f", "null", "-"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
            timeout=60,
        )
        if decoded.returncode != 0:
            raise EditorError(
                "OUTPUT_INVALID",
                f"序列的 {frame.name} 这一帧解不开（ffmpeg 退出码 {decoded.returncode}）"
                + (f"：{decoded.stderr.strip()[-160:]}" if decoded.stderr.strip() else ""),
                500,
                file=frame.name,
            )
    return (
        f"共 {len(frames)} 帧，从 {prefix}{numbers[0]:06d} 起连续编号，"
        f"首尾两帧（{frames[0].name}、{frames[-1].name}）都解得开"
    )


def verify_output(ffmpeg: Path, ffprobe: Path, path: Path, plan: RenderPlan) -> str:
    """Re-open the candidate file and hold it against the plan before it gets the final name.

    FFmpeg returning 0 only proves the process stopped without an error. It does not prove the
    container matches the preset, that the streams the filtergraph was built for came out, or that
    the length survived — and those three are exactly how a mistuned ``output_args`` shows up. Then
    the last half second is decoded, because a truncated write keeps a complete header: measured on
    a real MP4 cut to 30 % of its bytes, the inspector still reported both streams and 3.000000 s
    while the decoder answered ``partial file`` and ``Invalid NAL unit size``.
    Returns a measurement sentence for the job log; raises so the caller destroys the candidate.
    """
    reading = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name:format=format_name,duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_NO_WINDOW,
        timeout=60,
    )
    try:
        document = json.loads(reading.stdout)
    except ValueError:
        document = {}
    streams = document.get("streams") if isinstance(document, dict) else None
    complaint = reading.stderr.strip()[-200:]
    if reading.returncode != 0 or not isinstance(streams, list) or not streams:
        raise EditorError(
            "OUTPUT_INVALID",
            f"FFmpeg 结束了，但产出的文件读不出任何流（ffprobe 退出码 {reading.returncode}）"
            + (f"：{complaint}" if complaint else ""),
            500,
        )
    kinds = {stream.get("codec_type") for stream in streams}
    if plan.video_label and "video" not in kinds:
        raise EditorError(
            "OUTPUT_INVALID", f"计划要求画面，但文件里只有 {'/'.join(sorted(map(str, kinds)))}", 500
        )
    if not plan.video_label and "video" in kinds:
        raise EditorError(
            "OUTPUT_INVALID",
            f"纯音频预设不该出画面，但文件里带着视频流（{'/'.join(sorted(map(str, kinds)))}）",
            500,
        )
    if "audio" not in kinds:
        raise EditorError(
            "OUTPUT_INVALID",
            f"文件里没有声音流，而渲染计划带着混音输出 {plan.audio_label}，这一路本该写进去",
            500,
        )
    container = str(plan.summary.get("container") or "")
    reported = str((document.get("format") or {}).get("format_name") or "")
    demuxers = [name for name in reported.split(",") if name]
    if container and container not in demuxers:
        raise EditorError(
            "OUTPUT_INVALID",
            f"预设要求 {container} 容器，文件实际是 {reported or '未知'}",
            500,
        )
    expected = plan.duration_ticks / TIMEBASE
    # Two frames of rounding, plus a floor for the encoder delay a container may write ahead of
    # the first sample. A shorter file than this is a truncated write, not a rounding artefact.
    tolerance = max(0.15, frame_seconds(plan) * 2)
    raw = (document.get("format") or {}).get("duration")
    try:
        measured = float(raw)
    except (TypeError, ValueError):
        raise EditorError(
            "OUTPUT_INVALID",
            f"文件读不出时长（容器 {reported}），无法确认它装完了整条时间线",
            500,
        ) from None
    if abs(measured - expected) > tolerance:
        raise EditorError(
            "OUTPUT_INVALID",
            f"文件时长 {measured:.3f} 秒，与计划的 {expected:.3f} 秒相差超过 {tolerance:.3f} 秒",
            500,
        )
    # Decode the tail with the encoder that wrote it. `-v error` prints nothing unless something is
    # actually wrong, so any text at all here means the last frames or samples are not in the file.
    tail = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-ss",
            f"{max(0.0, measured - TAIL_WINDOW):.3f}",
            "-i",
            str(path),
            "-map",
            "0",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_NO_WINDOW,
        timeout=120,
    )
    damage = tail.stderr.strip()
    if damage:
        raise EditorError(
            "OUTPUT_INVALID",
            f"文件的最后 {TAIL_WINDOW} 秒解不出画面或声音，写入在中途被截断：{damage[-240:]}",
            500,
        )
    names = "/".join(str(stream.get("codec_name")) for stream in streams)
    return f"{measured:.3f} 秒 / {len(streams)} 路流（{names}）/ {container}，尾部可解码"


def frame_seconds(plan: RenderPlan) -> float:
    """The plan's frame rate as seconds per frame, tolerant of the ``num/den`` string it carries."""
    text = str(plan.summary.get("frame_rate") or "")
    numerator, _, denominator = text.partition("/")
    try:
        return float(denominator or 1) / float(numerator or 1)
    except (TypeError, ValueError):
        return 0.0


def request_fingerprint(project_id: str, request: RenderRequest) -> str:
    """The digest a render receipt is stored under: one delivery request, one fingerprint."""
    canonical = json.dumps(
        [project_id, request.preset_id, request.filename, request.folder, request.fit]
        # Only fields whose value is *not* the default join the array, so a receipt written before
        # the field existed replays as itself instead of turning the retry into a conflict — that
        # is how `range`, `transparent`, `timecode`, `colour_tag` and `output_frame_rate` arrived.
        + ([request.range] if request.range != "full" else [])
        + ([request.sequence_id] if request.sequence_id is not None else [])
        + ([request.transparent] if request.transparent else [])
        + ([request.timecode] if request.timecode else [])
        + ([request.colour_tag] if request.colour_tag else [])
        + (
            [request.output_frame_rate.numerator, request.output_frame_rate.denominator]
            if request.output_frame_rate is not None
            else []
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class JobRuntime:
    def __init__(
        self,
        db_path: Path,
        ffmpeg: Path | None,
        output_dir: Path,
        output_roots: list[Path],
        slots: int = 1,
        max_pending: int = DEFAULT_MAX_PENDING,
        pending_per_actor: int = DEFAULT_PENDING_PER_ACTOR,
    ):
        self.db_path = db_path
        self.ffmpeg = ffmpeg.resolve() if ffmpeg else None
        self.output_dir = output_dir
        self.output_roots = [root.resolve() for root in output_roots]
        self.queue: queue.Queue[str] = queue.Queue()
        self.cancelled: set[str] = set()
        self.processes: dict[str, subprocess.Popen] = {}
        self.lock = threading.Lock()
        self.submit_lock = threading.Lock()
        self.slots = max(1, min(int(slots), MAX_RENDER_SLOTS))
        self.workers: list[threading.Thread] = []
        self.max_pending = max(1, int(max_pending))
        self.pending_per_actor = max(1, int(pending_per_actor))
        self.job_actor: dict[str, str] = {}
        output_dir.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs("
                "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, document TEXT NOT NULL,"
                "status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS render_receipts("
                "request_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS output_roots("
                "path TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            for row in db.execute("SELECT path FROM output_roots").fetchall():
                root = Path(row["path"])
                if root.is_dir() and root not in self.output_roots:
                    self.output_roots.append(root)
        self.requeued = self._recover()
        for job_id in self.requeued:
            self.queue.put(job_id)
        if self.requeued:
            # 找回来的那几单不该等下一次投单才有人拉：重启的意义就是「把没干完的接着干完」。
            self.ensure_worker()

    @contextmanager
    def connection(self, write: bool = False):
        db = connect(self.db_path, timeout=5, isolation_level=None)
        db.row_factory = Row
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

    # ---------- persistence ----------

    def _save(self, job: RenderJob):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        job = job.model_copy(update={"updated_at": now})
        with self.connection(write=True) as db:
            db.execute(
                "INSERT INTO jobs(id,project_id,document,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET document=excluded.document, status=excluded.status,"
                " updated_at=excluded.updated_at",
                (
                    job.id,
                    job.project_id,
                    job.model_dump_json(),
                    job.status,
                    job.created_at or now,
                    now,
                ),
            )
        return job

    def _load(self, job_id: str) -> RenderJob:
        with self.connection() as db:
            row = db.execute("SELECT document FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise EditorError("NOT_FOUND", "no such job", 404, job_id=job_id)
        return RenderJob.model_validate_json(row["document"])

    def _recover(self) -> list[str]:
        """重启之后：没开始过的接着排，渲到一半的那一单才是真被打断。

        1.319 之前这两件事合成了一句「都标 failed/INTERRUPTED」，后果是自动流水线一次重启就永久
        卡住：那条 `request_id` 的收据还钉着那个死作业，重投只拿回同一句失败，一个文件也渲不出来
        （现场读数由 `tests/ops_check.py` 钉着）。所以「running」除了标中断还要把收据一起删掉——
        幂等在这里的说法是「同一个请求最多渲一次」，不是「那个失败的作业永远代表这个请求」。
        `queued` 的那几单根本没动过手，重新入队就行：文件名在提交那一刻已经占下了，不会与别人抢。
        """
        requeued: list[str] = []
        with self.connection(write=True) as db:
            rows = db.execute(
                "SELECT id,document FROM jobs WHERE status IN ('queued','running')"
            ).fetchall()
            for row in rows:
                job = RenderJob.model_validate_json(row["document"])
                if job.status == "queued":
                    requeued.append(job.id)
                    continue
                stale = job.model_copy(
                    update={
                        "status": "failed",
                        "error_code": "INTERRUPTED",
                        "message": "服务重启时该渲染任务被中断，请按同一个 request_id 重新提交",
                    }
                )
                db.execute(
                    "UPDATE jobs SET document=?, status='failed' WHERE id=?",
                    (stale.model_dump_json(), job.id),
                )
                db.execute("DELETE FROM render_receipts WHERE job_id=?", (job.id,))
        return requeued

    def list_for_project(self, project_id: str, limit: int = 50) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT document FROM jobs WHERE project_id=?"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        return [json.loads(row["document"]) for row in rows]

    def list_all(self, limit: int = 100) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT document FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row["document"]) for row in rows]

    # ---------- output policy ----------

    def add_output_root(self, raw: str) -> list[str]:
        path = Path(raw)
        if not path.is_absolute() or "\x00" in raw:
            raise EditorError("OUTPUT_ROOT_INVALID", "output root must be an absolute path")
        resolved = path.resolve()
        if resolved.is_file():
            raise EditorError(
                "OUTPUT_ROOT_INVALID", "output root must be a folder", 422, folder=str(resolved)
            )
        resolved.mkdir(parents=True, exist_ok=True)
        if resolved not in self.output_roots:
            self.output_roots.append(resolved)
            with self.connection(write=True) as db:
                db.execute(
                    "INSERT INTO output_roots(path) VALUES(?) ON CONFLICT(path) DO NOTHING",
                    (str(resolved),),
                )
        return [str(root) for root in self.output_roots]

    def describe_output_roots(self) -> list[str]:
        return [str(root) for root in self.output_roots]

    def _target_path(self, request: RenderRequest) -> Path:
        name = Path(request.filename).name
        # The extension is the container the preset will actually write, so a delivered file cannot
        # be a stream the wrapper cannot hold (an hvc1 track named .webm would never play back).
        preset = preset_by_id(request.preset_id)
        container = preset["container"]
        if not name.lower().endswith(f".{container}"):
            raise EditorError("OUTPUT_NAME_INVALID", f"output file name must end with .{container}")
        base = Path(request.folder) if request.folder else self.output_dir
        if not base.is_absolute() or "\x00" in (request.folder or ""):
            raise EditorError("OUTPUT_ROOT_INVALID", "output folder must be absolute")
        base = base.resolve()
        if not any(base == root or root in base.parents for root in self.output_roots):
            raise EditorError(
                "OUTPUT_NOT_ALLOWED",
                "output folder is not a registered output root",
                403,
                folder=str(base),
                output_roots=self.describe_output_roots(),
            )
        if preset["sequence"]:
            # 序列交付的不止一个文件，而是一串：目录名 = 文件名去掉扩展名，
            # 里面是 `名字.000001.exr`。目录此刻就占下来（这一步在提交锁里做），
            # 名字被占就往后让——覆盖上一次交付不可逆。
            stem = Path(name).stem
            folder = base / stem
            index = 1
            while folder.exists():
                index += 1
                folder = base / f"{stem}-{index}"
            if index >= 1000:
                raise EditorError(
                    "OUTPUT_NAME_INVALID",
                    f"{base} 里 {stem} 这个名字让不开了，换个文件名再导",
                    422,
                    filename=request.filename,
                )
            folder.mkdir()
            return folder / f"{folder.name}.%06d.{container}"
        target = base / name
        if target.exists():
            stem, suffix = target.stem, target.suffix
            for index in range(2, 1000):
                candidate = base / f"{stem}-{index}{suffix}"
                if not candidate.exists():
                    target = candidate
                    break
            else:
                raise EditorError(
                    "OUTPUT_NAME_INVALID",
                    "too many files with this name; pick a different file name",
                    422,
                    filename=request.filename,
                )
        return target

    # ---------- lifecycle ----------

    def _receipt_job_id(self, request_id: str) -> str | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT job_id FROM render_receipts WHERE request_id=?", (request_id,)
            ).fetchone()
        return row["job_id"] if row else None

    def submit(
        self, project: Project, request: RenderRequest, actor: str | None = None
    ) -> tuple[RenderJob, dict]:
        # One lock for check-then-insert: two concurrent submits can never pick the
        # same target name or double-queue the same request.
        with self.submit_lock:
            # 重放不计额度：一次重试被队列挡回，调用方只会以为自己的交付丢了。
            if self._receipt_job_id(request.request_id) is None:
                self._guard_pending(1, actor)
            return self._submit_locked(project, request, actor)

    def _submit_locked(
        self, project: Project, request: RenderRequest, actor: str | None = None
    ) -> tuple[RenderJob, dict]:
        if not self.ffmpeg:
            raise EditorError("MEDIA_TOOL_MISSING", "ffmpeg is not configured, cannot render", 503)
        fingerprint = request_fingerprint(project.id, request)
        with self.connection() as db:
            row = db.execute(
                "SELECT job_id,fingerprint FROM render_receipts WHERE request_id=?",
                (request.request_id,),
            ).fetchone()
        if row is not None:
            # Replay first, conflict later: a retry must get the original job back
            # even if the timeline moved on since.
            if row["fingerprint"] != fingerprint:
                raise EditorError(
                    "IDEMPOTENCY_CONFLICT",
                    "request_id was used with a different render payload",
                    409,
                    request_id=request.request_id,
                )
            try:
                plan = plan_for(
                    project,
                    request.preset_id,
                    sequence_id=request.sequence_id,
                    fit=request.fit,
                    range_mode=request.range,
                    transparent=request.transparent,
                    timecode=request.timecode,
                    output_frame_rate=request.output_frame_rate,
                    colour_tag=request.colour_tag,
                ).as_dict()
            except EditorError:
                plan = {}
            return self._load(row["job_id"]), plan
        if project.revision != request.expected_revision:
            raise EditorError(
                "REVISION_CONFLICT",
                "read the latest project before rendering",
                409,
                expected_revision=request.expected_revision,
                actual_revision=project.revision,
            )
        plan = plan_for(
            project,
            request.preset_id,
            sequence_id=request.sequence_id,
            fit=request.fit,
            range_mode=request.range,
            transparent=request.transparent,
            timecode=request.timecode,
            output_frame_rate=request.output_frame_rate,
            colour_tag=request.colour_tag,
        )
        target = self._target_path(request)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        job = RenderJob(
            id=uuid4().hex[:16],
            project_id=project.id,
            revision=project.revision,
            sequence_id=request.sequence_id,
            preset_id=request.preset_id,
            fit=request.fit,
            range=request.range,
            transparent=request.transparent,
            timecode=request.timecode,
            output_frame_rate=request.output_frame_rate,
            colour_tag=request.colour_tag,
            filename=target.name,
            status="queued",
            total_ticks=plan.duration_ticks,
            message="排队等待渲染",
            created_at=now,
            updated_at=now,
            output_path=str(target),
        )
        job = self._save(job)
        with self.connection(write=True) as db:
            db.execute(
                "INSERT INTO render_receipts(request_id,job_id,fingerprint) VALUES(?,?,?)",
                (request.request_id, job.id, fingerprint),
            )
        self.queue.put(job.id)
        if actor:
            with self.lock:
                self.job_actor[job.id] = actor
        self.ensure_worker()
        return job, plan.as_dict()

    def submit_batch(
        self, project: Project, batch: RenderBatch, actor: str | None = None
    ) -> list[tuple[RenderJob, dict]]:
        """Queue several deliverables from one read of the timeline, all or nothing.

        Every item is compiled before anything is enqueued, so an unknown preset or a filename the
        output root refuses fails the whole batch instead of leaving half a delivery queued. Each
        item still gets its own receipt, keyed `<request_id>-<index>`, so replaying the batch
        returns the same jobs and changing one item is a conflict rather than a silent extra file.
        """
        with self.submit_lock:
            if not batch.dry_run:
                # 整批按「这一趟真会新增几单」计一次额度，而不是逐条扣——半批排上、半批被拒就是
                # 这一档反对的那种「留下半截交付」。重放的那几条不占额度。
                fresh = sum(
                    1
                    for index in range(len(batch.items))
                    if self._receipt_job_id(f"{batch.request_id}-{index}") is None
                )
                if fresh:
                    self._guard_pending(fresh, actor)
            for item in batch.items:
                plan_for(
                    project,
                    item.preset_id,
                    sequence_id=item.sequence_id,
                    fit=item.fit,
                    range_mode=item.range,
                    transparent=item.transparent,
                    timecode=item.timecode,
                    output_frame_rate=item.output_frame_rate,
                    colour_tag=item.colour_tag,
                )
            results: list[tuple[RenderJob, dict]] = []
            for index, item in enumerate(batch.items):
                request = RenderRequest(
                    request_id=f"{batch.request_id}-{index}",
                    expected_revision=batch.expected_revision,
                    preset_id=item.preset_id,
                    filename=item.filename,
                    folder=item.folder,
                    sequence_id=item.sequence_id,
                    fit=item.fit,
                    range=item.range,
                    transparent=item.transparent,
                    timecode=item.timecode,
                    output_frame_rate=item.output_frame_rate,
                    colour_tag=item.colour_tag,
                )
                if batch.dry_run:
                    results.append(
                        (
                            RenderJob(
                                id="dry-run",
                                project_id=project.id,
                                revision=project.revision,
                                preset_id=item.preset_id,
                                fit=item.fit,
                                range=item.range,
                                transparent=item.transparent,
                                timecode=item.timecode,
                                output_frame_rate=item.output_frame_rate,
                                colour_tag=item.colour_tag,
                                filename=item.filename,
                                status="queued",
                            ),
                            plan_for(
                                project,
                                item.preset_id,
                                sequence_id=item.sequence_id,
                                fit=item.fit,
                                range_mode=item.range,
                                transparent=item.transparent,
                                timecode=item.timecode,
                                output_frame_rate=item.output_frame_rate,
                                colour_tag=item.colour_tag,
                            ).as_dict(),
                        )
                    )
                    continue
                results.append(self._submit_locked(project, request, actor))
            return results

    def get(self, job_id: str) -> RenderJob:
        return self._load(job_id)

    def cancel(self, job_id: str) -> RenderJob:
        job = self._load(job_id)
        if job.status in TERMINAL:
            raise EditorError("JOB_ALREADY_DONE", f"job already {job.status}", 409, job_id=job_id)
        with self.lock:
            self.cancelled.add(job_id)
            process = self.processes.get(job_id)
        if process and process.poll() is None:
            self._kill(process)
            job = job.model_copy(update={"status": "cancelled", "message": "已取消渲染"})
            return self._save(job)
        return job.model_copy(update={"status": "cancelled", "message": "已取消排队中的渲染"})

    def ensure_worker(self) -> None:
        """把渲染槽补到 `self.slots` 条。

        多出来的那几条不是「并发保证」，只是「允许同时开几支 FFmpeg」：一支 FFmpeg 自己会用满核，
        所以两槽能不能真的快一倍是量出来的，不是推出来的（`ops_check` 那一条按墙钟读数说话）。
        """
        with self.lock:
            self.workers = [thread for thread in self.workers if thread.is_alive()]
            missing = self.slots - len(self.workers)
            fresh = [
                threading.Thread(
                    target=self._loop,
                    name=f"agentcut-render-{len(self.workers) + index + 1}",
                    daemon=True,
                )
                for index in range(missing)
            ]
            self.workers.extend(fresh)
        for thread in fresh:
            thread.start()

    def live_slots(self) -> int:
        with self.lock:
            return sum(1 for thread in self.workers if thread.is_alive())

    def pending_count(self) -> int:
        return self.queue.unfinished_tasks

    def _loop(self):
        while True:
            job_id = self.queue.get()
            try:
                self._run_one(job_id)
            except Exception as error:  # a broken render must never kill the supervisor
                try:
                    job = self._load(job_id)
                    if job.status not in TERMINAL:
                        self._save(
                            job.model_copy(
                                update={
                                    "status": "failed",
                                    "error_code": "RENDER_CRASHED",
                                    "message": str(error)[:MAX_LOG],
                                }
                            )
                        )
                except EditorError:
                    pass
            finally:
                self._settle(job_id)
                self.queue.task_done()

    def _settle(self, job_id: str) -> None:
        """一单走到终态就从「某只令牌名下压了几单」那本账里划掉。

        划不掉的话额度会只涨不落：流水线跑一天之后，谁都被自己以前投的单挡住了。
        """
        with self.lock:
            self.job_actor.pop(job_id, None)

    def _guard_pending(self, incoming: int, actor: str | None) -> None:
        """排队前先看额度，而不是等 FFmpeg 起来才说不行——拒得要早，说得要具体。"""
        pending = self.queue.unfinished_tasks
        if pending + incoming > self.max_pending:
            raise EditorError(
                "QUEUE_FULL",
                f"待渲队列最多排 {self.max_pending} 单，现在已排 {pending} 单，这一趟还要排 "
                f"{incoming} 单——等前面的交付落了地再投，或者把 --max-queue 调大",
                429,
                pending=pending,
                limit=self.max_pending,
                incoming=incoming,
            )
        if actor:
            with self.lock:
                mine = sum(1 for owner in self.job_actor.values() if owner == actor)
            if mine + incoming > self.pending_per_actor:
                raise EditorError(
                    "QUOTA_EXCEEDED",
                    f"令牌 {actor} 名下已排 {mine} 单，每只令牌最多 {self.pending_per_actor} 单，"
                    f"这一趟还要排 {incoming} 单",
                    429,
                    actor=actor,
                    pending=mine,
                    limit=self.pending_per_actor,
                    incoming=incoming,
                )

    @staticmethod
    def _kill(process: subprocess.Popen):
        """停掉一支在跑的 FFmpeg。

        `taskkill` 这台机器上会不回来（1.219 实测到这一格的后果：取消一手钉在 `_kill` 里，
        渲染线程走不到 `finally`，其后的作业全停在「排队等待渲染」，而那半截 `.part` 也留在那儿）。
        所以这一手必须有截止时间；等不到就退回 `process.kill()`——要的是「它停了」，
        不是「哪一种停法」。
        """
        try:
            if _NO_WINDOW:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    creationflags=_NO_WINDOW,
                    timeout=KILL_TIMEOUT_SECONDS,
                )
                return
            process.kill()
        except subprocess.TimeoutExpired:
            pass
        except OSError:
            pass
        try:
            process.kill()
        except OSError:
            pass

    def _run_one(self, job_id: str):
        job = self._load(job_id)
        if job.id in self.cancelled or job.status in TERMINAL:
            self.cancelled.discard(job_id)
            return
        with self.connection() as db:
            row = db.execute(
                "SELECT document FROM history WHERE project_id=? AND revision=?",
                (job.project_id, job.revision),
            ).fetchone()
        if row is None:
            self._save(
                job.model_copy(
                    update={
                        "status": "failed",
                        "error_code": "PROJECT_NOT_FOUND",
                        "message": "渲染所需的历史快照已不存在",
                    }
                )
            )
            return
        project = Project.model_validate_json(row["document"])
        if project.revision != job.revision:
            self._save(
                job.model_copy(
                    update={
                        "status": "failed",
                        "error_code": "STALE_REVISION",
                        "message": (
                            f"项目已从 r{job.revision} 变为 r{project.revision}，"
                            "为避免渲染错版已停止"
                        ),
                    }
                )
            )
            return
        plan = plan_for(
            project,
            job.preset_id,
            sequence_id=job.sequence_id,
            fit=job.fit,
            range_mode=job.range,
            transparent=job.transparent,
            timecode=job.timecode,
            output_frame_rate=job.output_frame_rate,
            colour_tag=job.colour_tag,
        )
        target = Path(job.output_path or (self.output_dir / job.filename))
        sequence = bool(preset_by_id(job.preset_id)["sequence"])
        if sequence:
            # 序列没有「一个临时文件」可以躲：帧先落进兄弟目录 `名字.part/`，点过数、
            # 首尾都解得开，才逐帧搬进最终目录。写坏的序列不会顶着可用的名字。
            staging = target.parent.with_name(target.parent.name + ".part") / target.name
            staging.parent.mkdir(parents=True, exist_ok=True)
        else:
            staging = target.with_suffix(f".part.{preset_by_id(job.preset_id)['container']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        argv = plan.ffmpeg_argv(str(self.ffmpeg), str(staging))
        if "-filter_complex_script" in argv and not ffmpeg_support(self.ffmpeg)["graph_script"]:
            said = ffmpeg_support(self.ffmpeg)
            # 这不是「界面允许、导出会拒」那类口子：能触发这一条的唯一原因是操作者把引擎指到了
            # 自己机器上另一份 ffmpeg（`--ffmpeg` 或 `AGENTCUT_FFMPEG`）。所以话要说清是谁、哪一份、
            # 以及回去的那两个名字——而不是让 FFmpeg 的原始 stderr 当最后一句话。
            raise EditorError(
                "FFMPEG_NO_GRAPH_SCRIPT",
                "这条交付的滤镜图超过了内联的限度，只能写成脚本文件交给 `-filter_complex_script`；"
                f"你指的这份 ffmpeg（{said['version']}，{said['path']}）不认那个选项。"
                "随包的那一份认：把 `--ffmpeg` 与 `AGENTCUT_FFMPEG` 这两处去掉再导一次就行。",
                503,
                ffmpeg=said["path"],
                version=said["version"],
            )
        work = self.db_path.parent / "render-assets" / job_id
        work.mkdir(parents=True, exist_ok=True)
        for name, body in plan.text_files.items():
            (work / name).write_text(body, encoding="utf-8")
        for name, body in plan.binary_files.items():
            (work / name).write_bytes(body)
        started = time.time()
        job = self._save(
            job.model_copy(update={"status": "running", "message": "正在渲染", "rendered_ticks": 0})
        )
        process = subprocess.Popen(
            argv,
            cwd=work,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_NO_WINDOW,
        )
        # stderr must be drained while ffmpeg runs; a full pipe buffer would block it.
        stderr_tail: list[str] = []

        def drain_stderr():
            try:
                assert process.stderr is not None
                for line in process.stderr:
                    stderr_tail.append(line)
                    del stderr_tail[:-MAX_LOG]
            except (ValueError, OSError):
                pass

        stderr_thread = threading.Thread(
            target=drain_stderr, name="agentcut-ffmpeg-stderr", daemon=True
        )
        stderr_thread.start()
        with self.lock:
            self.processes[job_id] = process
        last_write = 0.0
        total_seconds = max(0.001, plan.duration_ticks / TIMEBASE)
        try:
            assert process.stdout is not None
            for line in process.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us":
                    try:
                        seconds = int(value) / 1_000_000
                    except ValueError:
                        continue
                    # A progress line is telemetry, not a fact about the timeline. WebM with Opus
                    # really does report a negative `out_time_us` on its first packets (measured
                    # -6500 us, i.e. -458640 ticks): the codec's encoder delay puts the audio track
                    # before zero, and `RenderJob` rightly refuses a negative tick count. So the
                    # reading is clamped here instead of being stored raw and crashing the job.
                    ticks = max(0, min(plan.duration_ticks, int(seconds * TIMEBASE)))
                    seconds = max(0.0, seconds)
                    now = time.time()
                    if now - last_write > 0.2 or ticks >= plan.duration_ticks:
                        last_write = now
                        current = self._load(job_id)
                        if current.id in self.cancelled:
                            self._kill(process)
                            break
                        self._save(
                            current.model_copy(
                                update={
                                    "rendered_ticks": ticks,
                                    "message": (f"正在渲染 {seconds:.1f} / {total_seconds:.1f}s"),
                                }
                            )
                        )
            return_code = process.wait()
        finally:
            if process.poll() is None:
                # An exception mid-render (e.g. a busy database) must not leak a
                # running ffmpeg that keeps writing the temp file.
                self._kill(process)
            with self.lock:
                self.processes.pop(job_id, None)
        cancelled = job_id in self.cancelled
        self.cancelled.discard(job_id)
        stderr_thread.join(timeout=5)
        stderr = "".join(stderr_tail)
        if cancelled or return_code not in (0, None):
            _discard_staging(staging, sequence)
            if cancelled:
                self._save(
                    job.model_copy(
                        update={"status": "cancelled", "message": "已取消渲染", "error_code": None}
                    )
                )
            else:
                self._save(
                    job.model_copy(
                        update={
                            "status": "failed",
                            "error_code": "FFMPEG_FAILED",
                            "message": describe_exit(return_code, stderr),
                            "elapsed_seconds": round(time.time() - started, 2),
                        }
                    )
                )
            return
        frames = _sequence_frames(staging) if sequence else []
        if (sequence and not frames) or (
            not sequence and (not staging.exists() or staging.stat().st_size <= 0)
        ):
            if sequence:
                _discard_staging(staging, True)
            self._save(
                job.model_copy(
                    update={
                        "status": "failed",
                        "error_code": "NO_OUTPUT",
                        "message": "FFmpeg 正常结束但没有产出文件",
                    }
                )
            )
            return
        probe = ffprobe_beside(self.ffmpeg)
        measurement = None
        if probe is not None:
            try:
                measurement = (
                    verify_sequence(self.ffmpeg, probe, staging, plan)
                    if sequence
                    else verify_output(self.ffmpeg, probe, staging, plan)
                )
            except EditorError as failure:
                # The candidate is destroyed instead of published: a file that cannot be measured
                # is not a deliverable, and leaving it under the final name would let a person or
                # an Agent hand it to a client.
                _discard_staging(staging, sequence)
                self._save(
                    job.model_copy(
                        update={
                            "status": "failed",
                            "error_code": failure.code,
                            "message": failure.message,
                            "output_path": None,
                            "output_size_bytes": None,
                            "output_checked": False,
                            "elapsed_seconds": round(time.time() - started, 2),
                        }
                    )
                )
                return
        if sequence:
            for frame in frames:
                # 同名换目录：同一分区里就是一次 rename，逐帧原子。
                frame.replace(target.parent / frame.name)
            _discard_staging(staging, True)
            delivered = f"{target.parent.name}/"
            size = sum(path.stat().st_size for path in _sequence_frames(target))
        else:
            staging.replace(target)  # atomic publish: only finished files carry the final name
            delivered = target.name
            size = target.stat().st_size
        self._save(
            job.model_copy(
                update={
                    "status": "succeeded",
                    "rendered_ticks": plan.duration_ticks,
                    # Says what was measured, or says nothing was measured. A silent success would
                    # read the same either way, which is exactly how an unchecked file gets trusted.
                    "message": f"已输出 {delivered}"
                    + (
                        f"（复检：{measurement}）"
                        if measurement
                        else f"（未经复检：{self.ffmpeg.parent.name} 目录里没有 ffprobe）"
                    ),
                    "output_path": str(target),
                    "output_size_bytes": size,
                    "output_checked": measurement is not None,
                    "elapsed_seconds": round(time.time() - started, 2),
                    "error_code": None,
                }
            )
        )
