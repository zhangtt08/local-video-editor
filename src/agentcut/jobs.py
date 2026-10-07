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

from .contracts import TIMEBASE, EditorError, Project, RenderBatch, RenderJob, RenderRequest
from .media import _NO_WINDOW
from .render import RenderPlan, compile_render_plan, marked_range

STATUS_STEPS = ("queued", "running", "succeeded", "failed", "cancelled")
TERMINAL = ("succeeded", "failed", "cancelled")
MAX_LOG = 3000


def plan_for(
    project: Project,
    preset_id: str,
    *,
    sequence_id: str | None = None,
    fit: str = "contain",
    range_mode: str = "full",
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
    )


# Windows reports a crashed child as its exception code, and FFmpeg dies that way without writing a
# single line to stderr. "退出码 3221225477：" with nothing after the colon is no use to a person or
# an Agent, so name what the code means and say out loud that nothing was reported.
WINDOWS_EXCEPTIONS = {
    0xC0000005: "访问越界（滤镜链里有滤镜收到了每帧都在变的画面尺寸）",
    0xC00000FD: "栈溢出（表达式嵌套过深）",
    0xC0000409: "运行时安全检查中止（同样是滤镜链越界）",
}


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


class JobRuntime:
    def __init__(
        self, db_path: Path, ffmpeg: Path | None, output_dir: Path, output_roots: list[Path]
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
        self.worker: threading.Thread | None = None
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
        self._recover()

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

    def _recover(self):
        with self.connection(write=True) as db:
            rows = db.execute(
                "SELECT id,document FROM jobs WHERE status IN ('queued','running')"
            ).fetchall()
            for row in rows:
                job = RenderJob.model_validate_json(row["document"])
                stale = job.model_copy(
                    update={
                        "status": "failed",
                        "error_code": "INTERRUPTED",
                        "message": "服务重启时该渲染任务被中断，请重新提交渲染",
                    }
                )
                db.execute(
                    "UPDATE jobs SET document=?, status='failed' WHERE id=?",
                    (stale.model_dump_json(), job.id),
                )

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
        if not name.lower().endswith(".mp4"):
            raise EditorError("OUTPUT_NAME_INVALID", "output file name must end with .mp4")
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

    def submit(self, project: Project, request: RenderRequest) -> tuple[RenderJob, dict]:
        # One lock for check-then-insert: two concurrent submits can never pick the
        # same target name or double-queue the same request.
        with self.submit_lock:
            return self._submit_locked(project, request)

    def _submit_locked(self, project: Project, request: RenderRequest) -> tuple[RenderJob, dict]:
        if not self.ffmpeg:
            raise EditorError("MEDIA_TOOL_MISSING", "ffmpeg is not configured, cannot render", 503)
        canonical = json.dumps(
            [project.id, request.preset_id, request.filename, request.folder, request.fit]
            # Only a non-default range joins the fingerprint, so a receipt written before this field
            # existed still replays as itself instead of turning into a conflict.
            + ([request.range] if request.range != "full" else [])
            + ([request.sequence_id] if request.sequence_id is not None else []),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
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
        self.ensure_worker()
        return job, plan.as_dict()

    def submit_batch(self, project: Project, batch: RenderBatch) -> list[tuple[RenderJob, dict]]:
        """Queue several deliverables from one read of the timeline, all or nothing.

        Every item is compiled before anything is enqueued, so an unknown preset or a filename the
        output root refuses fails the whole batch instead of leaving half a delivery queued. Each
        item still gets its own receipt, keyed `<request_id>-<index>`, so replaying the batch
        returns the same jobs and changing one item is a conflict rather than a silent extra file.
        """
        with self.submit_lock:
            for item in batch.items:
                plan_for(
                    project,
                    item.preset_id,
                    sequence_id=item.sequence_id,
                    fit=item.fit,
                    range_mode=item.range,
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
                                filename=item.filename,
                                status="queued",
                            ),
                            plan_for(
                                project,
                                item.preset_id,
                                sequence_id=item.sequence_id,
                                fit=item.fit,
                                range_mode=item.range,
                            ).as_dict(),
                        )
                    )
                    continue
                results.append(self._submit_locked(project, request))
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

    def ensure_worker(self):
        with self.lock:
            if self.worker and self.worker.is_alive():
                return
            self.worker = threading.Thread(target=self._loop, name="agentcut-render", daemon=True)
        self.worker.start()

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
                self.queue.task_done()

    @staticmethod
    def _kill(process: subprocess.Popen):
        try:
            if _NO_WINDOW:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    creationflags=_NO_WINDOW,
                )
            else:
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
        )
        target = Path(job.output_path or (self.output_dir / job.filename))
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".part.mp4")
        argv = plan.ffmpeg_argv(str(self.ffmpeg), str(temp))
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
                    ticks = min(plan.duration_ticks, int(seconds * TIMEBASE))
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
            if temp.exists():
                temp.unlink(missing_ok=True)
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
        if not temp.exists() or temp.stat().st_size <= 0:
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
        temp.replace(target)  # atomic publish: only finished files carry the final name
        self._save(
            job.model_copy(
                update={
                    "status": "succeeded",
                    "rendered_ticks": plan.duration_ticks,
                    "message": f"已输出 {target.name}",
                    "output_path": str(target),
                    "output_size_bytes": target.stat().st_size,
                    "elapsed_seconds": round(time.time() - started, 2),
                    "error_code": None,
                }
            )
        )
