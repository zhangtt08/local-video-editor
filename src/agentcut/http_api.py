"""HTTP boundary: authentication, typed contracts, media access, render jobs, error mapping.

Only loopback is served. Everything that writes project state goes through ProjectStore so
the desktop client and an external Agent share exactly one command semantic.
"""

import asyncio
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import (
    agent_contract,
    deliverable,
    duck,
    interchange,
    overview,
    recipe_run,
    scenes,
    serving,
    silence,
    stability,
    transcript,
)
from . import asr as asr_module
from . import autograde as autograde_module
from . import beats as beats_module
from . import fourpoint as fourpoint_module
from . import markers as marker_plan
from . import reframe as reframe_plan
from . import stabilize as stabilize_module
from . import sync as sync_module
from .animation import (
    extra_box_at,
    graph_curve,
    layer_graph,
    layer_nodes,
    preview_manifest,
    sample_values,
)
from .attributes import attribute_plan
from .bundles import MAX_BUNDLE_BYTES, export_bundle, import_bundle
from .colortags import detect_space
from .contracts import (
    APP_VERSION,
    BEAT_MARK_LIMIT,
    CLIP_SUBSET_LIMIT,
    COLOR_SPACES,
    MASK_EXTRA_KEY_LIMIT,
    MASK_ROTATION_LIMIT,
    SYNC_MIN_SCORE,
    TIMEBASE,
    TRACK_FRAMES_MIN,
    AttributePlanRequest,
    AutoGradeRequest,
    BeatRequest,
    BundleImport,
    CachePrune,
    Clip,
    ClipColorSpaceRead,
    ClipStabilizeRequest,
    CreateProject,
    DuckRequest,
    EditBatch,
    EditorError,
    ExtraMaskTrackRequest,
    FadeAdoptTrackRequest,
    FourPointRequest,
    FrameStabilityRequest,
    GradeApplyTrackRequest,
    Identifier,
    ImportRequest,
    InterchangeImportRequest,
    LayerProperty,
    LoudnessRequest,
    LutParse,
    MarkerSplitRequest,
    MaskTrackRequest,
    MaskTrackTarget,
    MasterLoudnessRequest,
    MediaProbe,
    MutationResult,
    OtioImportRequest,
    Project,
    ProjectUpdate,
    Property,
    ProxyPrune,
    ProxyRequest,
    RecipeRun,
    ReframeRequest,
    RenderBatch,
    RenderFit,
    RenderRange,
    RenderRequest,
    RestoreProject,
    Revision,
    RoughCutRequest,
    SceneRequest,
    SequenceRef,
    ShapeMask,
    SilenceRequest,
    SpeechCaptionsRequest,
    SyncRequest,
    Ticks,
    TranscriptCutRequest,
    audio_scan_problem,
    capabilities,
    parse_frame_rate,
    picture_scan_problem,
    render_presets,
)
from .grade import parse_cube
from .jobs import TERMINAL, JobRuntime, plan_for
from .loudness import master_plan, normalize_gain, probe_mix, volume_problem
from .loudness import measure as measure_loudness
from .masks import mask_image
from .media import ALLOWED_SUFFIXES, PROXY_WIDTHS, MediaService
from .projects import ProjectStore
from .render import text_fonts_available
from .speed import consumed_source_ticks
from .subtitles import export_srt
from .timeline import (
    CLIP_KEYFRAME_LIMIT,
    MASK_TRACK_CURVES,
    MASK_TRACK_SIZED_CURVES,
    fade_adopt_track_plan,
    grade_apply_track_plan,
    grade_capacity,
    mask_track_capacity,
    sequence_view,
    validate_timeline,
)
from .tracking import analyse_window, follow_window, simplify_path

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".json": "application/json",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".m4v": "video/mp4",
    ".ts": "video/mp2t",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
}


def signature(token: str, resource: str) -> str:
    return hmac.new(token.encode(), resource.encode(), hashlib.sha256).hexdigest()[:32]


def _meter_clip(engine: MediaService, project, clip, request) -> tuple[dict, dict]:
    """Measure one clip's window and plan its gain, naming the clip if the meter refuses.

    A silent or unmeasurable window is a property of this clip, so the refusal has to say which
    clip it means -- the meter itself only ever sees a file path.
    """
    source = Path(project.assets[clip.asset_id].verified.path)
    try:
        measured = measure_loudness(
            engine.ffmpeg,
            source,
            clip.source_in_ticks / TIMEBASE,
            clip.duration_ticks * (clip.speed_percent / 100) / TIMEBASE,
        )
        plan = normalize_gain(
            measured, target_lufs=request.target_lufs, ceiling_dbtp=request.ceiling_dbtp
        )
    except EditorError as failure:
        details = dict(failure.details)
        details.update(clip_id=clip.id, asset_id=clip.asset_id, asset_label=source.name)
        raise EditorError(failure.code, failure.message, failure.status, **details) from None
    return measured, plan


class AuditLedger:
    """One line per call that changed something, or was refused — with the caller's own id.

    A desktop polls reads constantly, so a ledger of GETs buries the one thing an enterprise asks
    for: who asked for this clip to change. A refusal is an event — that is the line a security
    review reads first.

    Written as a plain ASGI layer on purpose: it *tees* the receive channel instead of consuming
    it, so the route still gets every byte of the body it wants to parse, and the `request_id`
    from that body still lands in the ledger. Reading the body from a `BaseHTTPMiddleware` instead
    would starve the endpoint below — the bug this shape exists to avoid.
    """

    def __init__(self, app, audit: "serving.AuditLog") -> None:
        self.app = app
        self.audit = audit

    def _record(self, scope, method: str, started: float, status: int, seen: list[bytes]) -> None:
        refused = status in (401, 403)
        if method in ("GET", "HEAD", "OPTIONS") and not refused:
            return
        request_id = None
        try:
            parsed = json.loads(b"".join(seen).decode("utf-8", errors="replace") or "{}")
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            request_id = parsed.get("request_id")
        parts = str(scope.get("path", "")).split("/")
        project_id = parts[3] if len(parts) > 3 and parts[2] == "projects" else None
        state = scope.get("state") or {}
        self.audit.write(
            actor=state.get("actor"),
            method=method,
            path=scope.get("path"),
            status=status,
            duration_ms=round((time.monotonic() - started) * 1000),
            project_id=project_id,
            request_id=request_id,
        )

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/v1/"):
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method", ""))
        seen: list[bytes] = []
        status = {"code": 0}

        async def tee() -> dict:
            message = await receive()
            if message.get("type") == "http.request" and len(b"".join(seen)) <= 65536:
                seen.append(message.get("body", b"") or b"")
            return message

        async def watch(event: dict, *args) -> None:
            if event.get("type") == "http.response.start":
                status["code"] = int(event.get("status") or 0)
            await send(event, *args)

        started = time.monotonic()
        try:
            await self.app(scope, tee, watch)
        except Exception:
            self._record(scope, method, started, status["code"] or 500, seen)
            raise
        self._record(scope, method, started, status["code"], seen)


def create_app(
    db_path: Path,
    token: str,
    media: MediaService | None = None,
    jobs: JobRuntime | None = None,
    app_info: dict | None = None,
    tokens: serving.TokenTable | None = None,
    audit: serving.AuditLog | None = None,
    bind_host: str = "127.0.0.1",
    allow_origins: list[str] | None = None,
) -> FastAPI:
    if len(token) < 32:
        raise ValueError("AGENTCUT_TOKEN must contain at least 32 characters")
    bearer = HTTPBearer(auto_error=False)
    if tokens is not None:
        # 桌面端那枚共享令牌也进表，标 `local`：一条路同时管得住老用法与新发的具名令牌。
        tokens.grant_legacy(token)

    def authorize(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        secret = "" if credentials is None else credentials.credentials
        identity = None
        if tokens is not None:
            identity = tokens.resolve(secret)
        if identity is None and secrets.compare_digest(secret.encode(), token.encode()):
            identity = {"label": serving.LOCAL_LABEL, "scopes": list(serving.SCOPES)}
        if identity is None:
            raise EditorError("UNAUTHORIZED", "valid Bearer token required", 401)
        request.state.actor = identity["label"]
        if request.method not in ("GET", "HEAD", "OPTIONS") and "write" not in identity["scopes"]:
            raise EditorError(
                "SCOPE_DENIED",
                f"令牌 {identity['label']} 只有读的作用域，这一手要写",
                403,
                actor=identity["label"],
                method=request.method,
                scopes=identity["scopes"],
            )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.projects = ProjectStore(db_path, media)
        yield

    app = FastAPI(
        title="AgentCut API",
        version=APP_VERSION,
        lifespan=lifespan,
        description=(
            "本地剪辑引擎。所有时间使用整数 tick（70,560,000/秒）；写入需要 request_id，"
            "编辑需要 expected_revision；dry_run 不落地。"
        ),
    )
    hosts = ["127.0.0.1", "localhost"]
    if bind_host not in ("127.0.0.1", "localhost", "0.0.0.0"):
        hosts.append(bind_host)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=(
            r"^(agentcut://app|http://(127\.0\.0\.1|localhost)(:\d+)?)$"
            if not allow_origins
            else "^(" + "|".join(re.escape(origin) for origin in allow_origins) + ")$"
        ),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Range", "Range", "X-Requested-With"],
        allow_credentials=False,
        expose_headers=["X-Frame-Ticks", "X-Project-Revision", "Content-Disposition"],
        max_age=600,
    )

    def store(request: Request) -> ProjectStore:
        return request.app.state.projects

    Store = Annotated[ProjectStore, Depends(store)]
    auth = [Depends(authorize)]

    if audit is not None:
        app.add_middleware(AuditLedger, audit=audit)

    def require_media() -> MediaService:
        if media is None or not media.enabled:
            raise EditorError(
                "MEDIA_UNAVAILABLE",
                "media engine is disabled: configure a media root and ffmpeg/ffprobe",
                503,
            )
        return media

    def require_jobs() -> JobRuntime:
        if jobs is None:
            raise EditorError("RENDER_UNAVAILABLE", "render engine is not configured", 503)
        return jobs

    def urls_for(probe: MediaProbe) -> dict:
        base = (app_info or {}).get("base_url", "")

        def signed(path: str, resource: str) -> str:
            return f"{base}{path}?sig={signature(token, resource)}"

        return {
            "thumbnails": [
                signed(f"/v1/media/{probe.id}/file/{name}", f"media:{probe.id}:{name}")
                for name in probe.thumbnails
            ],
            "waveform": signed(
                f"/v1/media/{probe.id}/file/wave.json", f"media:{probe.id}:wave.json"
            ),
            "stream": signed(f"/v1/media/{probe.id}/stream", f"stream:{probe.id}"),
        }

    def probe_with_urls(probe: MediaProbe) -> dict:
        data = probe.model_dump()
        data["urls"] = urls_for(probe)
        return data

    @app.exception_handler(EditorError)
    async def editor_error(_request: Request, error: EditorError):
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else None
        return JSONResponse({"error": error.payload()}, status_code=error.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError):
        issues = [
            {"path": list(issue["loc"]), "message": issue["msg"], "type": issue["type"]}
            for issue in error.errors()
        ]
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "invalid request",
                    "details": {"issues": issues},
                }
            },
            status_code=422,
        )

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(_request: Request, _error: sqlite3.OperationalError):
        return JSONResponse(
            {
                "error": {
                    "code": "STORAGE_UNAVAILABLE",
                    "message": "storage unavailable; retry with the same request_id",
                    "details": {},
                }
            },
            status_code=503,
        )

    @app.get("/health")
    def health(projects: Store):
        projects.ping()
        return {
            "status": "ok",
            "instance": (app_info or {}).get("instance", ""),
            "media_ready": bool(media and media.enabled),
            "render_ready": bool(jobs and jobs.ffmpeg),
        }

    def speech_ready() -> bool:
        return bool(media and media.enabled and media.asr_ready())

    @app.get("/v1/info", dependencies=auth)
    def info():
        payload = dict(app_info or {})
        payload["media_ready"] = bool(media and media.enabled)
        payload["render_ready"] = bool(jobs and jobs.ffmpeg)
        payload["media_roots"] = media.describe_roots() if media else []
        payload["output_roots"] = jobs.describe_output_roots() if jobs else []
        # 1.319：槽数与队列额度是运行时的数，不是契约里的静态上限——自动流水线要能在投单之前
        # 问一句「你还放得下几单」，而不是撞上一次 429 才知道今天排到哪儿了。
        payload["queue"] = (
            {
                "slots": jobs.slots,
                "live_slots": jobs.live_slots(),
                "max_pending": jobs.max_pending,
                "pending_per_actor": jobs.pending_per_actor,
                "pending": jobs.pending_count(),
                "requeued": len(jobs.requeued),
            }
            if jobs
            else None
        )
        payload["capabilities"] = capabilities(
            bool(media and media.enabled), speech_ready(), text_fonts_available()
        )
        return payload

    @app.get("/v1/capabilities", dependencies=auth)
    def editor_capabilities():
        return capabilities(bool(media and media.enabled), speech_ready(), text_fonts_available())

    @app.get("/v1/contracts", dependencies=auth)
    def contracts():
        return {
            model.__name__: model.model_json_schema()
            for model in (
                Project,
                CreateProject,
                BundleImport,
                EditBatch,
                ProjectUpdate,
                RestoreProject,
                MutationResult,
                ImportRequest,
                LutParse,
                RecipeRun,
                RenderRequest,
            )
        }

    @app.get("/v1/agent/audit", dependencies=auth)
    def read_audit(
        limit: Annotated[int, Query(ge=1, le=serving.LEDGER_LIMIT)] = 50,
        actor: str | None = None,
        project_id: str | None = None,
    ):
        """The ledger of what this engine was asked to do — newest last.

        Actions and refusals only. `path` says where the file itself is, so an enterprise can
        ship it to whatever keeps logs.
        """
        if audit is None:
            raise EditorError("AUDIT_UNAVAILABLE", "这台引擎没开台账", 503)
        return {
            "events": audit.recent(limit=limit, actor=actor, project_id=project_id),
            "path": str(audit.path),
            "written": audit.seq,
        }

    @app.get("/v1/metrics", dependencies=auth)
    def read_metrics(recent: Annotated[int, Query(ge=1, le=500)] = 50):
        """How the queue and the recent jobs look, counted from the engine's own ledger.

        Nothing here is kept a second time: slots and pending depth come from the runtime,
        durations and failure codes from the same `jobs` rows the console reads.
        """
        runtime = require_jobs()
        return runtime.metrics(recent=recent)

    @app.get("/v1/callbacks", dependencies=auth)
    def read_callbacks(recent: Annotated[int, Query(ge=1, le=500)] = 50):
        """每一条终态回执欠没欠：投给了谁、试了几次、上一次为什么没成。

        调用方不必再轮询 `/v1/jobs/{id}` 才知道片渲完没有，但**得有一条路问「通知到了没有」**——
        出站这件事自己会失败（接收端挂了、网络断了、地址写错了），那种失败不能只留在日志里。
        """
        runtime = require_jobs()
        return {"callbacks": runtime.outbox.recent(recent), "config": runtime.outbox.summary()}

    @app.get("/v1/agent/manifest", dependencies=auth)
    async def agent_manifest(request: Request):
        """The whole agent contract in one read: routes, MCP tools, capabilities, recipes.

        One call answers "what can I call here, with which arguments, in what order" for either
        surface. The tool table is the live MCP registry and the endpoint table is this app's own
        route table, so neither list can drift from what actually answers.
        """
        # 只有这一条路要 MCP 那张名字表：纯 HTTP 的引擎不必为它加载适配器，所以到这儿才 import。
        from .mcp_server import create_mcp

        base = str(request.base_url).rstrip("/")
        server = create_mcp(base, token)
        return await agent_contract.manifest(
            app,
            server,
            base_url=base,
            live_capabilities=capabilities(
                bool(media and media.enabled), speech_ready(), text_fonts_available()
            ),
        )

    @app.post("/v1/agent/recipes/{recipe_id}/run", dependencies=auth)
    async def run_agent_recipe(recipe_id: Identifier, request: RecipeRun):
        """Run one whole delivery recipe inside the engine, through this same HTTP surface.

        The doors the recipe names are the doors this app answers: the steps go out over an
        in-process client with the same bearer token, so a one-call run cannot mean anything
        different from the same calls made by hand. It cannot skip the reducer, the revision
        check, the media-root authorization or the idempotency receipt on the way either.
        """
        # 只有这一条路要往回敲自己的门：纯 HTTP 的引擎平时不碰 httpx。
        import httpx

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
            timeout=180.0,
        ) as session:

            async def door(
                method: str, path: str, payload: dict | None = None
            ) -> tuple[int, dict]:
                reply = await session.request(method, path, json=payload)
                try:
                    body = reply.json()
                except ValueError:
                    body = {"error": {"code": "AGENT_RUN_FAILED", "message": reply.text[:200]}}
                return reply.status_code, body if isinstance(body, dict) else {"value": body}

            return await recipe_run.run(door, recipe_id, request)

    @app.get("/v1/render-presets", dependencies=auth)
    def presets():
        return {"presets": render_presets()}

    @app.post("/v1/ids", dependencies=auth)
    def request_ids(count: Annotated[int, Query(ge=1, le=200)] = 32):
        """Server-issued opaque ids so clients never invent colliding clip/track ids."""
        from uuid import uuid4

        return {"ids": [uuid4().hex[:16] for _ in range(count)]}

    # ---------- projects ----------

    @app.post("/v1/projects", dependencies=auth, response_model=MutationResult)
    def create_project(request: CreateProject, projects: Store):
        return projects.create(request)

    @app.get("/v1/projects", dependencies=auth)
    def list_projects(
        projects: Store,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        return {"projects": projects.list_projects(limit, offset)}

    @app.get("/v1/projects/{project_id}", dependencies=auth, response_model=Project)
    def get_project(project_id: Identifier, projects: Store, revision: Revision | None = None):
        return projects.get(project_id, revision)

    @app.get("/v1/projects/{project_id}/captions/{track_id}", dependencies=auth)
    def get_captions(
        project_id: Identifier,
        track_id: Identifier,
        projects: Store,
        revision: Revision | None = None,
        sequence_id: SequenceRef | None = None,
    ):
        project = sequence_view(projects.get(project_id, revision), sequence_id)
        return {"revision": project.revision, "srt": export_srt(project, track_id)}

    @app.get("/v1/projects/{project_id}/history", dependencies=auth)
    def project_history(
        project_id: Identifier,
        projects: Store,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        return {"history": projects.history(project_id, limit, offset)}

    @app.post("/v1/projects/{project_id}/edits", dependencies=auth, response_model=None)
    def edit_project(
        project_id: Identifier,
        request: EditBatch,
        projects: Store,
        receipt: str = Query(default="full"),
    ):
        """Apply one batch. `receipt=slim` answers with numbers instead of the whole project.

        `full` is the default and is exactly what the desktop sends: a person's compositor state IS
        the engine's answer, so the UI must not have to fetch it a second time. `slim` is for a
        caller that already knows what it wrote and only needs the revision to keep its own
        `expected_revision` chain going — on a project with tens of thousands of clips the echoed
        project is the whole cost of the call.
        """
        if receipt not in {"full", "slim"}:
            raise EditorError(
                "INVALID_REQUEST",
                "receipt is either 'full' (the project itself) or 'slim' (just the numbers)",
                422,
                receipt=receipt,
            )
        result = projects.mutate(project_id, request)
        if receipt == "full":
            return result
        return {
            "receipt": "slim",
            "project_id": result.project.id,
            "revision": result.project.revision,
            "base_revision": result.base_revision,
            "committed": result.committed,
            "replayed": result.replayed,
        }

    @app.post("/v1/projects/{project_id}/restore", dependencies=auth, response_model=MutationResult)
    def restore_project(project_id: Identifier, request: RestoreProject, projects: Store):
        return projects.mutate(project_id, request)

    @app.post("/v1/projects/{project_id}", dependencies=auth, response_model=MutationResult)
    def update_project(project_id: Identifier, request: ProjectUpdate, projects: Store):
        return projects.update_project(project_id, request)

    # ---------- media ----------

    @app.get("/v1/media/config", dependencies=auth)
    def media_config():
        engine = require_media()
        return {
            "media_roots": engine.describe_roots(),
            "cache_dir": str(engine.cache_dir),
            "ffmpeg": str(engine.ffmpeg or ""),
            "ffprobe": str(engine.ffprobe or ""),
            "allowed_suffixes": sorted(ALLOWED_SUFFIXES),
        }

    @app.post("/v1/media/import", dependencies=auth)
    def media_import(request: ImportRequest):
        engine = require_media()
        return probe_with_urls(engine.import_file(request.path))

    @app.get("/v1/media/probes", dependencies=auth)
    def media_probes():
        engine = require_media()
        return {"probes": engine.list_probes()}

    # Declared before /v1/media/{probe_id} so the literal path wins the route match.
    @app.get("/v1/media/proxies", dependencies=auth)
    def proxy_inventory():
        engine = require_media()
        inventory = engine.proxy_inventory()
        return {
            "limit_bytes": inventory["limit_bytes"],
            "used_bytes": inventory["used_bytes"],
            "proxies": [
                {key: entry[key] for key in ("source_sha256", "width", "size_bytes", "used_at")}
                for entry in inventory["proxies"]
            ],
        }

    @app.post("/v1/media/proxies/prune", dependencies=auth)
    def proxy_prune(request: ProxyPrune):
        engine = require_media()
        return engine.prune_proxies(request.max_bytes)

    @app.get("/v1/media/cache", dependencies=auth)
    def cache_inventory_route():
        engine = require_media()
        inventory = engine.cache_inventory()
        return {
            "limit_bytes": inventory["limit_bytes"],
            "used_bytes": inventory["used_bytes"],
            "entries": [
                {
                    key: entry[key]
                    for key in ("digest", "size_bytes", "files", "used_at", "has_proxy")
                }
                for entry in inventory["entries"]
            ],
        }

    @app.post("/v1/media/cache/prune", dependencies=auth)
    def cache_prune(request: CachePrune):
        engine = require_media()
        return engine.prune_cache(request.max_bytes, tuple(request.keep), request.dry_run)

    @app.get("/v1/media/{probe_id}", dependencies=auth)
    def media_probe(probe_id: Identifier):
        engine = require_media()
        return probe_with_urls(engine.get_probe(probe_id))

    def check_media_sig(probe_id: str, name: str, sig: str):
        engine = require_media()
        probe = engine.get_probe(probe_id)
        expected = signature(token, f"media:{probe_id}:{name}")
        if not secrets.compare_digest(expected.encode(), (sig or "").encode()):
            raise EditorError("UNAUTHORIZED", "invalid media signature", 401)
        return engine, probe

    def check_stream_sig(probe_id: str, sig: str):
        engine = require_media()
        probe = engine.get_probe(probe_id)
        expected = signature(token, f"stream:{probe_id}")
        if not secrets.compare_digest(expected.encode(), (sig or "").encode()):
            raise EditorError("UNAUTHORIZED", "invalid media signature", 401)
        return engine, probe

    @app.get("/v1/media/{probe_id}/file/{name}")
    def media_file(probe_id: Identifier, name: str, sig: str = ""):
        engine, probe = check_media_sig(probe_id, name, sig)
        path = engine.cache_path(probe, name)
        media_type = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(
            path, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"}
        )

    @app.get("/v1/media/{probe_id}/stream")
    def media_stream(probe_id: Identifier, sig: str = ""):
        engine, probe = check_stream_sig(probe_id, sig)
        path = Path(probe.verified.path)
        media_type = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})

    @app.get("/v1/assets/{asset_id}/stream")
    def asset_stream(
        project_id: Identifier, asset_id: Identifier, sig: str = "", projects: Store = None
    ):
        expected = signature(token, f"asset:{project_id}:{asset_id}")
        if not secrets.compare_digest(expected.encode(), (sig or "").encode()):
            raise EditorError("UNAUTHORIZED", "invalid media signature", 401)
        project = projects.get(project_id)
        asset = project.assets.get(asset_id)
        if asset is None:
            raise EditorError("NOT_FOUND", "asset is not in this project", 404, asset_id=asset_id)
        if asset.verified is None:
            raise EditorError("UNVERIFIED_ASSET", "asset has no verified media", 422)
        path = Path(asset.verified.path)
        if not path.is_file():
            raise EditorError("MEDIA_MISSING", "source file is gone", 410)
        return FileResponse(
            path,
            media_type=MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
            headers={"Accept-Ranges": "bytes"},
        )

    @app.get("/v1/projects/{project_id}/asset-urls", dependencies=auth)
    def asset_urls(project_id: Identifier, projects: Store):
        project = projects.get(project_id)
        return {
            "assets": {
                asset_id: {
                    "stream": (
                        f"{(app_info or {}).get('base_url', '')}/v1/assets/{asset_id}/stream"
                        f"?project_id={project_id}"
                        f"&sig={signature(token, f'asset:{project_id}:{asset_id}')}"
                    )
                }
                for asset_id, asset in project.assets.items()
                if asset.kind != "text"
            }
        }

    # ---------- playback proxies ----------

    def proxy_asset(projects: Store, project_id: str, asset_id: str):
        project = projects.get(project_id)
        asset = project.assets.get(asset_id)
        if asset is None:
            raise EditorError("NOT_FOUND", "asset is not in this project", 404, asset_id=asset_id)
        if asset.verified is None:
            raise EditorError("UNVERIFIED_ASSET", "asset has no verified media", 422)
        return asset

    def checked_width(width: int) -> int:
        if width not in PROXY_WIDTHS:
            raise EditorError(
                "INVALID_REQUEST",
                f"proxy width must be one of {', '.join(str(w) for w in PROXY_WIDTHS)}",
                422,
                width=width,
            )
        return width

    def proxy_payload(project_id: str, asset_id: str, state: dict) -> dict:
        ready = state.get("state") == "ready"
        width = state.get("width", 0)
        return {
            "project_id": project_id,
            "asset_id": asset_id,
            **state,
            "stream": (
                f"{(app_info or {}).get('base_url', '')}/v1/assets/{asset_id}/proxy/stream"
                f"?project_id={project_id}&width={width}"
                f"&sig={signature(token, f'proxy:{project_id}:{asset_id}:{width}')}"
                if ready
                else None
            ),
        }

    @app.get("/v1/projects/{project_id}/assets/{asset_id}/proxy", dependencies=auth)
    def proxy_state(project_id: Identifier, asset_id: Identifier, width: int, projects: Store):
        engine = require_media()
        asset = proxy_asset(projects, project_id, asset_id)
        return proxy_payload(
            project_id,
            asset_id,
            engine.proxy_state(asset.verified, checked_width(width)),
        )

    @app.post("/v1/projects/{project_id}/assets/{asset_id}/proxy", dependencies=auth)
    def proxy_build(
        project_id: Identifier, asset_id: Identifier, request: ProxyRequest, projects: Store
    ):
        engine = require_media()
        asset = proxy_asset(projects, project_id, asset_id)
        return proxy_payload(
            project_id, asset_id, engine.build_proxy(asset.verified, request.width)
        )

    @app.get("/v1/assets/{asset_id}/proxy/stream")
    def asset_proxy_stream(
        project_id: Identifier,
        asset_id: Identifier,
        width: int,
        sig: str = "",
        projects: Store = None,
    ):
        expected = signature(token, f"proxy:{project_id}:{asset_id}:{checked_width(width)}")
        if not secrets.compare_digest(expected.encode(), (sig or "").encode()):
            raise EditorError("UNAUTHORIZED", "invalid media signature", 401)
        engine = require_media()
        asset = proxy_asset(projects, project_id, asset_id)
        state = engine.proxy_state(asset.verified, width)
        if state["state"] != "ready":
            raise EditorError(
                "PROXY_UNAVAILABLE", "no proxy is built for this asset at that width", 409
            )
        path = Path(state["path"])
        if not path.is_file():
            raise EditorError("PROXY_UNAVAILABLE", "the proxy file is gone", 410)
        engine.touch_proxy(asset.verified, width)
        return FileResponse(
            path,
            media_type="video/mp4",
            headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"},
        )

    @app.post("/v1/projects/{project_id}/clips/{clip_id}/stabilize", dependencies=auth)
    def clip_stabilize(
        project_id: Identifier, clip_id: Identifier, request: ClipStabilizeRequest, projects: Store
    ):
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        clip = project.clips.get(clip_id)
        if clip is None:
            raise EditorError("NOT_FOUND", "clip is not in this project", 404, clip_id=clip_id)
        asset = project.assets.get(clip.asset_id)
        if asset is None or asset.kind != "video" or asset.verified is None:
            raise EditorError(
                "STABILIZE_INVALID", "only verified video clips can be stabilised", 422
            )
        track = next((item for item in project.tracks if item.id == clip.track_id), None)
        if track is None or track.kind != "video":
            # A video asset parked on an audio track renders no picture, so there is nothing to hold
            # still — and saying so beats writing keyframes the renderer never shows.
            raise EditorError(
                "STABILIZE_INVALID",
                "the clip is not on a picture track, so it renders no frame to stabilise",
                422,
                clip_id=clip_id,
                track_id=clip.track_id,
            )
        source = Path(asset.verified.path)
        if not source.is_file():
            raise EditorError(
                "MEDIA_MISSING",
                "source file is gone",
                410,
                clip_id=clip.id,
                asset_id=clip.asset_id,
                asset_label=source.name,
            )
        settings = project.settings
        motion = stabilize_module.measure(
            engine.ffmpeg,
            source,
            asset.verified.width or settings.width,
            asset.verified.height or settings.height,
            asset.verified.frame_rate or settings.frame_rate,
            clip.source_in_ticks,
            clip.duration_ticks,
            settings.frame_ticks,
            clip.speed_percent,
        )
        commands, notes = stabilize_module.plan(
            project,
            motion,
            clip_id=clip_id,
            strength=request.strength,
            max_crop=request.max_crop,
        )
        # Say which frames were measured: a clip that plays at 200 % was sampled at half the
        # sequence rate on purpose, and the reply is where a person can check that.
        notes = {**notes, "sample_rate": motion["sample_rate"], "speed_percent": clip.speed_percent}
        if not commands:
            # Nothing to write (strength 0). Report the measurement without burning a revision.
            return {
                "project": root.model_dump(mode="json"),
                "replayed": False,
                "stabilization": notes,
            }
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "stabilization": notes}

    @app.post("/v1/projects/{project_id}/clips/{clip_id}/auto-grade", dependencies=auth)
    def clip_auto_grade(
        project_id: Identifier, clip_id: Identifier, request: AutoGradeRequest, projects: Store
    ):
        """Measure one clip's own picture and write the levels node that stretches it to full range.

        The frames are decoded by the media engine from the server-verified file, inside the clip's
        own source window, and the bounds are percentiles of what is actually there. What comes back
        is an ordinary `clip.grade`, so the reducer stays the only writer of state, `dry_run`
        writes nothing, a repeated request_id replays, and a picture that already spans the measured
        range gets its numbers back without burning a revision. Like stabilise, pressing again
        re-computes the same correction instead of stacking a second copy — unless it would have to
        overwrite a node nobody measured, which is refused by position.
        """
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        clip = project.clips.get(clip_id)
        if clip is None:
            raise EditorError("NOT_FOUND", "clip is not in this project", 404, clip_id=clip_id)
        asset = project.assets.get(clip.asset_id)
        if asset is None or asset.verified is None or asset.kind not in ("video", "image"):
            raise EditorError(
                "AUTO_GRADE_INVALID",
                "there is no picture here to measure: auto levels reads the frames of a verified "
                "video or image, and an audio or text clip has none",
                422,
                clip_id=clip_id,
                asset_id=clip.asset_id,
                asset_kind=asset.kind if asset is not None else None,
            )
        track = next((item for item in project.tracks if item.id == clip.track_id), None)
        if track is None or track.kind != "video":
            raise EditorError(
                "AUTO_GRADE_INVALID",
                "the clip is not on a picture track, so it renders no frame to measure",
                422,
                clip_id=clip_id,
                track_id=clip.track_id,
            )
        source = Path(asset.verified.path)
        if not source.is_file():
            raise EditorError(
                "MEDIA_MISSING",
                "source file is gone",
                410,
                clip_id=clip.id,
                asset_id=clip.asset_id,
                asset_label=source.name,
            )
        settings = project.settings
        # The window is what this clip actually *plays*: a 200 % clip reads half as much source, so
        # measuring the timeline length would grade frames nobody ever sees. `consumed_source_ticks`
        # is the renderer's own authority for that span, and it covers speed curves too.
        source_ticks = consumed_source_ticks(clip, settings.frame_ticks)
        measurement = autograde_module.measure(
            engine.ffmpeg,
            source,
            asset.verified.width or settings.width,
            asset.verified.height or settings.height,
            asset.verified.frame_rate or settings.frame_rate,
            clip.source_in_ticks,
            source_ticks,
            samples=request.samples,
            percentile=request.percentile,
        )
        commands, notes = autograde_module.plan(
            project, clip_id, measurement, mode=request.mode, replace=request.replace
        )
        body = {"auto_grade": notes, "commands": commands}
        if not commands:
            # The picture already spans the range this mode measures. Report the numbers and write
            # nothing, rather than spending a revision on a node that cannot move a pixel.
            return {"project": root.model_dump(mode="json"), "replayed": False, **body}
        if not request.apply:
            return {"committed": False, "project": root.model_dump(mode="json"), **body}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, **body}

    def plan_mask_track(
        root: Project, target: MaskTrackTarget, position: int, sequence_id: str | None
    ) -> dict:
        """Validate one tracking target and say how far its own run can go.

        Every refusal names the clip and the target's place in the group, so a group that cannot be
        analysed does not have to be bisected to find out which one blocked it. The clip's curve
        budget is the second ceiling after the request's own: one sized sighting costs four curves,
        so the window is shortened to whatever that clip can still hold before anything is decoded.
        """
        project = sequence_view(root, sequence_id)
        clip = project.clips.get(target.clip_id)
        if clip is None:
            raise EditorError(
                "NOT_FOUND",
                "clip is not in this project",
                404,
                clip_id=target.clip_id,
                target_position=position,
            )
        asset = project.assets.get(clip.asset_id)
        if asset is None or asset.kind != "video" or asset.verified is None:
            raise EditorError(
                "INVALID_TRACK_TARGET",
                "only verified video clips can be tracked",
                422,
                clip_id=clip.id,
                target_position=position,
            )
        # A free-form outline can be followed by position, but its drawn size is fixed for the
        # clip, so the scale estimator is switched off rather than silently resized away.
        follows_shape = clip.mask is not None and clip.mask.shape == "path"
        problem = clip.mask_animation_problem() or (
            None
            if clip.mask is not None and not clip.mask.inverted
            else "a mask is required before tracking"
        )
        if problem:
            raise EditorError("INVALID_MASK", problem, clip_id=clip.id, target_position=position)
        if clip.speed_curve:
            raise EditorError(
                "INVALID_MASK",
                "a tracked mask path cannot follow a speed curve yet",
                clip_id=clip.id,
                target_position=position,
            )
        if target.from_ticks >= clip.duration_ticks:
            raise EditorError(
                "INVALID_TRACK_TARGET",
                "tracking starts outside the clip",
                422,
                clip_id=clip.id,
                target_position=position,
            )
        source = Path(asset.verified.path)
        if not source.is_file():
            raise EditorError(
                "MEDIA_MISSING",
                "source file is gone",
                410,
                clip_id=clip.id,
                asset_id=clip.asset_id,
                asset_label=source.name,
                target_position=position,
            )
        frame_ticks = project.settings.frame_ticks
        speed = clip.speed_percent / 100
        start = clip.source_in_ticks + int(target.from_ticks * speed)
        estimate_scale = target.estimate_scale and not follows_shape
        estimate_rotation = target.estimate_rotation and not follows_shape
        produced = MASK_TRACK_SIZED_CURVES if estimate_scale else MASK_TRACK_CURVES
        if estimate_rotation:
            produced = (*produced, "mask_rotation")
        curves = len(produced)
        capacity = mask_track_capacity(clip, produced, target.merge, target.from_ticks, frame_ticks)
        frames = min(target.frames, capacity)
        if frames < TRACK_FRAMES_MIN:
            raise EditorError(
                "MASK_TRACK_BUDGET",
                "this clip has no room left for another tracked frame",
                422,
                clip_id=clip.id,
                target_position=position,
                frames_requested=target.frames,
                capacity_frames=capacity,
                curves_per_point=curves,
                keyframe_limit=CLIP_KEYFRAME_LIMIT,
                curves_used=len(clip.keyframes),
            )
        consumed = int(frames * frame_ticks * speed)
        if start + consumed > asset.verified.duration_ticks:
            raise EditorError(
                "SOURCE_OUT_OF_BOUNDS",
                "tracking runs past the end of the source media",
                422,
                clip_id=clip.id,
                target_position=position,
                frames=frames,
            )
        return {
            "clip": clip,
            "target": target,
            "position": position,
            "source": source,
            "source_width": asset.verified.width or project.settings.width,
            "source_height": asset.verified.height or project.settings.height,
            "rate": project.settings.frame_rate,
            "frame_ticks": frame_ticks,
            "speed_percent": clip.speed_percent,
            "start": start,
            "frames": frames,
            "capacity": capacity,
            "curves": curves,
            "estimate_scale": estimate_scale,
            "rotation": estimate_rotation,
            "box": (clip.mask.center_x, clip.mask.center_y, clip.mask.width, clip.mask.height),
            # Everything the decoder actually sees. Two stacked copies of the same shot, asked for
            # the same window at the same rate, land on one key and so on one decode.
            "window_key": (
                str(source),
                start,
                frames,
                frame_ticks,
                clip.speed_percent,
                asset.verified.width,
                asset.verified.height,
                project.settings.frame_rate.numerator,
                project.settings.frame_rate.denominator,
            ),
        }

    @app.post("/v1/projects/{project_id}/mask-track", dependencies=auth)
    def mask_track(project_id: Identifier, request: MaskTrackRequest, projects: Store):
        """Analyse a group of box masks and write every path in one batch.

        The group is compiled before it is measured: targets are validated one by one, and only
        once every window and budget is settled does the media get decoded. Two targets that read
        the same window of the same file share that decode.
        """
        engine = require_media()
        root = projects.get(project_id)
        listed = [target.clip_id for target in request.targets]
        repeats = sorted({clip_id for clip_id in listed if listed.count(clip_id) > 1})
        if repeats:
            raise EditorError(
                "MASK_TRACK_DUPLICATE",
                "one clip carries one mask path, so the same clip cannot be tracked twice in one "
                "run; track it once, then move the mask onto the other subject and press "
                "「接着跟」",
                422,
                clip_ids=repeats,
                target_count=len(listed),
            )
        plans = [
            plan_mask_track(root, target, position, request.sequence_id)
            for position, target in enumerate(request.targets, start=1)
        ]
        windows: dict[tuple, tuple[int, list[bytes]]] = {}
        for plan in plans:
            if plan["window_key"] not in windows:
                windows[plan["window_key"]] = analyse_window(
                    engine.ffmpeg,
                    plan["source"],
                    plan["source_width"],
                    plan["source_height"],
                    plan["rate"],
                    plan["start"],
                    plan["frame_ticks"],
                    plan["frames"],
                    plan["speed_percent"],
                )
        commands: list[dict] = []
        receipts: list[dict] = []
        measured: set[tuple] = set()
        for plan in plans:
            target = plan["target"]
            clip = plan["clip"]
            shared = plan["window_key"] in measured
            measured.add(plan["window_key"])
            width, decoded = windows[plan["window_key"]]
            result = follow_window(
                decoded,
                width,
                plan["box"],
                target.search_radius,
                plan["rate"],
                plan["frame_ticks"],
                scale=plan["estimate_scale"],
                max_gap=target.max_gap_frames,
                reacquire=target.reacquire,
                speed_percent=plan["speed_percent"],
                rotate=plan["rotation"],
            )
            points = [
                {
                    "at_ticks": target.from_ticks + point["at_ticks"],
                    "center_x": point["mask_x"],
                    "center_y": point["mask_y"],
                    **(
                        {"width": point["width"], "height": point["height"]}
                        if plan["estimate_scale"]
                        else {}
                    ),
                    **({"rotation": point["rotation"]} if plan["rotation"] else {}),
                }
                for point in result["points"]
            ]
            if len(points) < 2:
                raise EditorError(
                    "TRACK_FAILED",
                    "too few frames matched to track",
                    422,
                    clip_id=clip.id,
                    target_position=plan["position"],
                    matched=len(points),
                    frames=target.frames,
                )
            commands.append(
                {
                    "op": "clip.mask_track",
                    "clip_id": clip.id,
                    "points": points,
                    "merge": target.merge,
                }
            )
            receipts.append(
                {
                    "clip_id": clip.id,
                    "target_position": plan["position"],
                    "shared_decode": shared,
                    "analysis_width": result["analysis_width"],
                    "analysis_height": result["analysis_height"],
                    "sampled_frames": result["sampled_frames"],
                    "tracked_frames": len(points),
                    "predicted_frames": result["predicted_frames"],
                    "reacquire": result["reacquire"],
                    "reacquired_frames": result["reacquired_frames"],
                    "reacquired_at_ticks": [
                        target.from_ticks + at for at in result["reacquired_at"]
                    ],
                    "gap_closure": result["gap_closure"],
                    "scale_estimated": result["scale"],
                    "rotation_estimated": result["rotation_estimated"],
                    "speed_percent": result["speed_percent"],
                    "sample_rate": result["sample_rate"],
                    "gaps": [
                        {
                            "from_ticks": target.from_ticks + gap["from_ticks"],
                            "to_ticks": target.from_ticks + gap["to_ticks"],
                        }
                        for gap in result["gaps"]
                    ],
                    "merged": target.merge,
                    **(
                        {} if plan["frames"] == target.frames else {"budget_frames": plan["frames"]}
                    ),
                    **({} if not target.merge else track_seam(clip, points)),
                    "first_at_ticks": points[0]["at_ticks"],
                    "last_at_ticks": points[-1]["at_ticks"],
                    "lost_at_ticks": (
                        None
                        if result["lost_at_ticks"] is None
                        else target.from_ticks + result["lost_at_ticks"]
                    ),
                    "angle_limit_at_ticks": (
                        None
                        if result["angle_limit_at_ticks"] is None
                        else target.from_ticks + result["angle_limit_at_ticks"]
                    ),
                    "points": points,
                }
            )
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {
            **mutation,
            "tracking": {
                "target_count": len(receipts),
                "decoded_passes": len(windows),
                "frames_decoded": sum(len(pair[1]) for pair in windows.values()),
                "targets": receipts,
            },
        }

    @app.post(
        "/v1/projects/{project_id}/clips/{clip_id}/mask-stack/{index}/track", dependencies=auth
    )
    def extra_mask_track(
        project_id: Identifier,
        clip_id: Identifier,
        index: int,
        request: ExtraMaskTrackRequest,
        projects: Store,
    ):
        """Follow one extra mask block and write its own box keys.

        This is the per-box half of multi-target tracking: the clip's main mask keeps its own path,
        each extra block gets one here, and the blocks nobody named stay byte-for-byte as they
        were. The path is decimated to the block's key ceiling by keeping only the samples a
        straight line cannot replace; `coarse` says whether the ceiling ran out first.
        """
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        clip = project.clips.get(clip_id)
        if clip is None:
            raise EditorError("NOT_FOUND", "clip is not in this project", 404, clip_id=clip_id)
        asset = project.assets.get(clip.asset_id)
        if asset is None or asset.kind != "video" or asset.verified is None:
            raise EditorError(
                "INVALID_TRACK_TARGET",
                "only verified video clips can be tracked",
                422,
                clip_id=clip.id,
            )
        stack = list(clip.extra_masks)
        if not 0 <= index < len(stack):
            raise EditorError(
                "INVALID_TRACK_TARGET",
                "this clip has no extra mask at that position",
                422,
                clip_id=clip.id,
                index=index,
                stack_size=len(stack),
            )
        speed_blocked = clip.speed_curve
        if speed_blocked:
            raise EditorError(
                "INVALID_MASK",
                "a tracked mask path cannot follow a speed curve yet",
                clip_id=clip.id,
                index=index,
            )
        if request.from_ticks >= clip.duration_ticks:
            raise EditorError(
                "INVALID_TRACK_TARGET",
                "tracking starts outside the clip",
                422,
                clip_id=clip.id,
                index=index,
            )
        source = Path(asset.verified.path)
        if not source.is_file():
            raise EditorError(
                "MEDIA_MISSING",
                "source file is gone",
                410,
                clip_id=clip.id,
                asset_id=clip.asset_id,
                asset_label=source.name,
            )
        extra = stack[index]
        sampled = extra_box_at(extra, request.from_ticks)
        box = (sampled[0], sampled[1], sampled[2], sampled[3])
        scale = request.estimate_scale and extra.shape != "path"
        rotation = request.estimate_rotation and extra.shape != "path"
        speed = clip.speed_percent / 100
        frame_ticks = project.settings.frame_ticks
        start = clip.source_in_ticks + int(request.from_ticks * speed)
        frames = request.frames
        step = max(1, int(frame_ticks * speed))
        if start + int(frames * frame_ticks * speed) > asset.verified.duration_ticks:
            frames = (asset.verified.duration_ticks - start) // step
        if frames < TRACK_FRAMES_MIN:
            raise EditorError(
                "SOURCE_OUT_OF_BOUNDS",
                "tracking runs past the end of the source media",
                422,
                clip_id=clip.id,
                index=index,
                frames=frames,
            )
        width, decoded = analyse_window(
            engine.ffmpeg,
            source,
            asset.verified.width or project.settings.width,
            asset.verified.height or project.settings.height,
            project.settings.frame_rate,
            start,
            frame_ticks,
            frames,
            clip.speed_percent,
        )
        result = follow_window(
            decoded,
            width,
            box,
            request.search_radius,
            project.settings.frame_rate,
            frame_ticks,
            scale=scale,
            max_gap=request.max_gap_frames,
            reacquire=request.reacquire,
            speed_percent=clip.speed_percent,
            rotate=rotation,
        )
        if len(result["points"]) < 2:
            raise EditorError(
                "TRACK_FAILED",
                "too few frames matched to track",
                422,
                clip_id=clip.id,
                index=index,
                matched=len(result["points"]),
            )
        kept, coarse = simplify_path(result["points"], MASK_EXTRA_KEY_LIMIT)
        feather_animated = any(key.feather is not None for key in extra.keys)
        keys: list[dict] = []
        for point in kept:
            at = request.from_ticks + point["at_ticks"]
            sample = extra_box_at(extra, at)
            key = {
                "at_ticks": at,
                "center_x": point["mask_x"],
                "center_y": point["mask_y"],
                "width": point["width"] if scale else sample[2],
                "height": point["height"] if scale else sample[3],
                "rotation": max(
                    -MASK_ROTATION_LIMIT,
                    min(MASK_ROTATION_LIMIT, sample[4] + (point.get("rotation") or 0.0)),
                ),
                "interpolation": "linear",
            }
            if feather_animated:
                key["feather"] = sample[5]
            keys.append(key)
        masks = [item.model_dump(mode="json") for item in stack]
        masks[index] = {**masks[index], "keys": keys}
        command = {"op": "clip.mask_stack", "clip_id": clip.id, "masks": masks}
        receipt = {
            "clip_id": clip.id,
            "index": index,
            "from_ticks": request.from_ticks,
            "frame_ticks": frame_ticks,
            "sampled_frames": result["sampled_frames"],
            "tracked_frames": len(result["points"]),
            "written_keys": len(keys),
            "coarse": coarse,
            "predicted_frames": result["predicted_frames"],
            "reacquired_frames": result["reacquired_frames"],
            "reacquire": result["reacquire"],
            "analysis_width": result["analysis_width"],
            "analysis_height": result["analysis_height"],
            "scale_estimated": result["scale"],
            "rotation_estimated": result["rotation_estimated"],
            "speed_percent": result["speed_percent"],
            "sample_rate": result["sample_rate"],
            "lost_at_ticks": (
                None
                if result["lost_at_ticks"] is None
                else request.from_ticks + result["lost_at_ticks"]
            ),
            "angle_limit_at_ticks": (
                None
                if result["angle_limit_at_ticks"] is None
                else request.from_ticks + result["angle_limit_at_ticks"]
            ),
            "commands": [command],
        }
        plan_only = request.dry_run
        if plan_only:
            return {
                "committed": False,
                "project": root.model_dump(mode="json"),
                "commands": [command],
                "track": receipt,
            }
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=[command],  # type: ignore[list-item]
            dry_run=False,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "commands": [command], "track": receipt}

    def track_seam(clip, points: list[dict]) -> dict:
        """What a continued track joins onto: how much survives, and how far the seam jumps.

        The new window's points are clip-local while the clip's curves live on the animation
        clock, so the comparison shifts the window by `animation_offset_ticks`. A seam of zero
        means the two runs meet at the same tick; anything else is a discontinuity the editor
        should see rather than have smoothed over silently.
        """
        offset = clip.animation_offset_ticks
        start = offset + points[0]["at_ticks"]
        stop = offset + points[-1]["at_ticks"]
        before = [key for key in clip.keyframes if key.property in {"mask_x", "mask_y"}]
        kept = [key for key in before if key.at_ticks < start]
        # Counted in frames, not in curves: a sized path carries two or four curves per sighting,
        # and "the first 20 frames survived" is the sentence the editor and the interface need.
        seam: dict[str, object] = {
            "kept_frames": len({key.at_ticks for key in kept}),
            "replaced_frames": len(
                {key.at_ticks for key in before if start <= key.at_ticks <= stop}
            ),
        }
        ticks = {key.at_ticks for key in kept}
        if len(ticks) == 0:
            return seam
        at = max(ticks)
        last = {key.property: key.value for key in kept if key.at_ticks == at}
        first = points[0]
        dx = first["center_x"] - last.get("mask_x", first["center_x"])
        dy = first["center_y"] - last.get("mask_y", first["center_y"])
        seam["seam_ticks"] = start - at
        seam["seam_jump"] = round(math.hypot(dx, dy), 6)
        return seam

    @app.post("/v1/projects/{project_id}/clips/{clip_id}/silence", dependencies=auth)
    def silence_scan(
        project_id: Identifier, clip_id: Identifier, request: SilenceRequest, projects: Store
    ):
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        clip = project.clips.get(clip_id)
        if clip is None:
            raise EditorError("NOT_FOUND", "clip is not in this project", 404, clip_id=clip_id)
        problem = audio_scan_problem(project, clip)
        if problem:
            raise EditorError("INVALID_SILENCE_TARGET", problem, 422, clip_id=clip_id)
        asset = project.assets[clip.asset_id]
        source = Path(asset.verified.path)
        if not source.is_file():
            raise EditorError(
                "MEDIA_MISSING",
                "source file is gone",
                410,
                clip_id=clip.id,
                asset_id=clip.asset_id,
                asset_label=source.name,
            )
        result = silence.analyse(
            engine.ffmpeg,
            source,
            clip,
            project.settings.frame_ticks,
            threshold_db=request.threshold_db,
            min_silence_ms=request.min_silence_ms,
            from_ticks=request.from_ticks,
            to_ticks=request.to_ticks,
        )
        commands = silence.cut_plan(clip, result["gaps"], edges=request.trim_edges)
        if request.apply and not commands:
            raise EditorError(
                "INVALID_SILENCE_TARGET",
                "no quiet stretch is long enough to cut with these settings",
                422,
                clip_id=clip_id,
            )
        if not request.apply:
            return {
                "committed": False,
                "project": root.model_dump(),
                "silence": {**result, "commands": commands},
            }
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "silence": {**result, "commands": commands}}

    @app.post("/v1/projects/{project_id}/clips/{clip_id}/scenes", dependencies=auth)
    def scene_scan(
        project_id: Identifier, clip_id: Identifier, request: SceneRequest, projects: Store
    ):
        """Find the shot changes in one clip's picture and hand back the split commands.

        The detector reads colour, not luma: pure red to pure green scores 0.0 on FFmpeg's
        `scene` score but 0.50 here, and graphics/slides are exactly where that matters. The
        plan is ordinary `clip.split` commands applied right to left, so the reducer remains the
        only place that decides what a cut does to the source clock, keyframes and links.
        """
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        clip = project.clips.get(clip_id)
        if clip is None:
            raise EditorError("NOT_FOUND", "clip is not in this project", 404, clip_id=clip_id)
        problem = picture_scan_problem(project, clip)
        if problem:
            raise EditorError("INVALID_SCENE_TARGET", problem, 422, clip_id=clip_id)
        asset = project.assets[clip.asset_id]
        source = Path(asset.verified.path)
        if not source.is_file():
            raise EditorError(
                "MEDIA_MISSING",
                "source file is gone",
                410,
                clip_id=clip.id,
                asset_id=clip.asset_id,
                asset_label=source.name,
            )
        result = scenes.analyse(
            engine.ffmpeg,
            source,
            clip,
            project.settings.frame_ticks,
            threshold=request.threshold,
            min_scene_ms=request.min_scene_ms,
            from_ticks=request.from_ticks,
            to_ticks=request.to_ticks,
        )
        commands = scenes.cut_plan(clip, result["cuts"])
        if request.apply and not commands:
            raise EditorError(
                "SCENE_NONE",
                "no shot change stands out at this threshold; the picture is one continuous take",
                422,
                clip_id=clip_id,
            )
        if not request.apply:
            return {
                "committed": False,
                "project": root.model_dump(),
                "scenes": {**result, "commands": commands},
            }
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "scenes": {**result, "commands": commands}}

    @app.post("/v1/projects/{project_id}/clips/{clip_id}/rough-cut", dependencies=auth)
    def rough_cut(
        project_id: Identifier, clip_id: Identifier, request: RoughCutRequest, projects: Store
    ):
        """Keep the head of every shot in one clip and pack those heads together.

        Same colour-change detector as 按镜头切分 (a luma-only score misses red-to-green), but the
        plan also trims each long shot down to `keep_ms` and lets the following shots ripple left.
        Every command is an ordinary `clip.split` / `clip.trim`, so the reducer stays the only
        place that decides what a cut does; `apply` submits the whole plan as one revision.
        """
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        clip = project.clips.get(clip_id)
        if clip is None:
            raise EditorError("NOT_FOUND", "clip is not in this project", 404, clip_id=clip_id)
        problem = picture_scan_problem(project, clip)
        if problem:
            raise EditorError("INVALID_ROUGH_TARGET", problem, 422, clip_id=clip_id)
        if clip.link_id is not None:
            raise EditorError(
                "INVALID_ROUGH_TARGET",
                "this clip is linked to another one; rough-cutting one side would desync them. "
                "Unlink first, or cut each clip separately.",
                422,
                clip_id=clip_id,
            )
        if clip.transition_in is not None:
            raise EditorError(
                "INVALID_ROUGH_TARGET",
                "a clip with an incoming transition cannot be rough-cut yet: dropping its head "
                "would move the seam the transition belongs to. Remove the transition first.",
                422,
                clip_id=clip_id,
            )
        asset = project.assets[clip.asset_id]
        source = Path(asset.verified.path)
        if not source.is_file():
            raise EditorError(
                "MEDIA_MISSING",
                "source file is gone",
                410,
                clip_id=clip.id,
                asset_id=clip.asset_id,
                asset_label=source.name,
            )
        result = scenes.analyse(
            engine.ffmpeg,
            source,
            clip,
            project.settings.frame_ticks,
            threshold=request.threshold,
            min_scene_ms=request.min_scene_ms,
            profile=True,
        )
        keep_ticks = scenes.keep_ticks_for(project.settings.frame_ticks, request.keep_ms)
        seam_ticks = (
            scenes.keep_ticks_for(project.settings.frame_ticks, request.transition_ms)
            if request.transition_ms
            else 0
        )
        commands = scenes.rough_cut_plan(
            clip,
            result["shots"],
            project.settings.frame_ticks,
            keep_ticks,
            place=request.place,
            transition_ticks=seam_ticks,
        )
        body = {
            **result,
            "keep_ms": request.keep_ms,
            "keep_ticks": keep_ticks,
            "place": request.place,
            "transition_ms": request.transition_ms,
        }
        if request.apply and not commands:
            raise EditorError(
                "ROUGH_NONE",
                "every shot is already shorter than the keep, so there is nothing to cut",
                422,
                clip_id=clip_id,
                keep_ms=request.keep_ms,
            )
        if not request.apply:
            return {
                "committed": False,
                "project": root.model_dump(),
                "rough": {**body, "commands": commands},
            }
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "rough": {**body, "commands": commands}}

    @app.post("/v1/projects/{project_id}/tracks/{track_id}/rough-cut", dependencies=auth)
    def rough_cut_track(
        project_id: Identifier, track_id: Identifier, request: RoughCutRequest, projects: Store
    ):
        """Keep the head of every shot on one track and pack each clip's heads together.

        Clips are planned right to left, so a clip's own coordinates are untouched by edits that
        only move what is to its right. Only this track moves; clips that cannot be scanned are
        skipped with the reason, the same judgement the single-clip route makes. Ordinary
        `clip.split` / `clip.trim` commands only, one batch and one revision.
        """
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        if next((track for track in project.tracks if track.id == track_id), None) is None:
            raise EditorError("NOT_FOUND", "track is not in this project", 404, track_id=track_id)
        if not any(item.track_id == track_id for item in project.clips.values()):
            raise EditorError("NOT_FOUND", "this track holds no clips", 404, track_id=track_id)
        frame_ticks = project.settings.frame_ticks
        keep_ticks = scenes.keep_ticks_for(frame_ticks, request.keep_ms)
        seam_ticks = (
            scenes.keep_ticks_for(frame_ticks, request.transition_ms)
            if request.transition_ms
            else 0
        )
        commands: list[dict] = []
        scanned: list[dict] = []
        for clip in sorted(
            (item for item in project.clips.values() if item.track_id == track_id),
            key=lambda item: -item.position_ticks,
        ):
            problem = picture_scan_problem(project, clip)
            if problem:
                scanned.append({"clip_id": clip.id, "skipped": problem})
                continue
            if clip.link_id is not None:
                scanned.append(
                    {
                        "clip_id": clip.id,
                        "skipped": "linked to another clip; unlink it first or cut it separately",
                    }
                )
                continue
            if clip.transition_in is not None:
                scanned.append(
                    {
                        "clip_id": clip.id,
                        "skipped": "an incoming transition would move its seam; remove it first",
                    }
                )
                continue
            source = Path(project.assets[clip.asset_id].verified.path)
            if not source.is_file():
                raise EditorError(
                    "MEDIA_MISSING",
                    "source file is gone",
                    410,
                    clip_id=clip.id,
                    asset_id=clip.asset_id,
                    asset_label=source.name,
                )
            result = scenes.analyse(
                engine.ffmpeg,
                source,
                clip,
                frame_ticks,
                threshold=request.threshold,
                min_scene_ms=request.min_scene_ms,
                profile=True,
            )
            plan = scenes.rough_cut_plan(
                clip,
                result["shots"],
                frame_ticks,
                keep_ticks,
                place=request.place,
                transition_ticks=seam_ticks,
            )
            commands.extend(plan)
            scanned.append(
                {
                    "clip_id": clip.id,
                    "cuts": result["cuts"],
                    "keep_ticks": keep_ticks,
                    "commands": plan,
                }
            )
        body = {
            "clips": scanned,
            "keep_ms": request.keep_ms,
            "keep_ticks": keep_ticks,
            "place": request.place,
            "transition_ms": request.transition_ms,
            "commands": commands,
        }
        if request.apply and not commands:
            raise EditorError(
                "ROUGH_NONE",
                "every shot on this track is already shorter than the keep",
                422,
                track_id=track_id,
                keep_ms=request.keep_ms,
            )
        if not request.apply:
            return {"committed": False, "project": root.model_dump(), "rough": body}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "rough": body}

    @app.post("/v1/projects/{project_id}/sync", dependencies=auth)
    def clips_sync(project_id: Identifier, request: SyncRequest, projects: Store):
        """Line several clips up by the sound they share and hand back ordinary move commands.

        The reference is one of the named clips (the first by default). Every other clip is
        correlated on a coarse envelope; a clip that cannot be heard, two angles on one track, a
        weak peak and a move that would land before zero are each refused by name. `apply` submits
        the moves as one batch; the reducer still owns what moving a clip does to links and groups.
        """
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        clips = []
        for clip_id in request.clip_ids:
            clip = project.clips.get(clip_id)
            if clip is None:
                raise EditorError("NOT_FOUND", "clip is not in this project", 404, clip_id=clip_id)
            problem = audio_scan_problem(project, clip)
            if problem:
                raise EditorError("INVALID_SYNC_TARGET", problem, 422, clip_id=clip_id)
            if clip.speed_percent != 100:
                raise EditorError(
                    "INVALID_SYNC_TARGET",
                    "a sped-up angle does not share one clock with the others; set its speed back "
                    "to 100 % before lining it up",
                    422,
                    clip_id=clip_id,
                    speed_percent=clip.speed_percent,
                )
            clips.append(clip)
        if len({clip.track_id for clip in clips}) != len(clips):
            raise EditorError(
                "INVALID_SYNC_TARGET",
                "two of these clips sit on one track; multicam angles need a track each so moving "
                "one cannot land on another",
                422,
                clips=[{"clip_id": clip.id, "track_id": clip.track_id} for clip in clips],
            )
        reference = next(
            (clip for clip in clips if clip.id == (request.reference_id or request.clip_ids[0])),
            None,
        )
        if reference is None:
            raise EditorError(
                "INVALID_SYNC_TARGET",
                "the reference has to be one of the named clips",
                422,
                reference_id=request.reference_id,
            )
        result = sync_module.analyse(
            engine.ffmpeg, project, clips, reference, max_offset_ms=request.max_offset_ms
        )
        if result["weakest_score"] < SYNC_MIN_SCORE:
            raise EditorError(
                "SYNC_WEAK",
                "the sound these clips share is too weak to line up: at least one angle has no "
                "clear common moment. Try a range where the same event is audible in both.",
                422,
                **result,
            )
        commands, refused = sync_module.move_plan(clips, reference, result["clips"])
        body = {**result, "commands": commands}
        if refused:
            raise EditorError(
                "SYNC_OUT_OF_RANGE",
                "lining these angles up would move one before zero; slide the reference later on "
                "the ruler first",
                422,
                **body,
                refused=refused,
            )
        if request.apply and not commands:
            raise EditorError(
                "SYNC_ALIGNED",
                "these angles already share one clock; nothing to move",
                422,
                **body,
            )
        if not request.apply:
            return {"committed": False, "project": root.model_dump(), "sync": body}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "sync": body}

    @app.get("/v1/projects/{project_id}/edl", dependencies=auth)
    def project_edl(
        project_id: Identifier,
        track_id: Identifier,
        projects: Store,
        sequence_id: SequenceRef | None = None,
    ):
        """One picture track as a CMX3600 edit list: straight cuts, 100 % speed, whole frame rates.

        Read-only: the answer is text for another editor, not a change to this project. Edits a
        CMX3600 cannot say (a transition, a speed change, a non-picture clip) are refused together
        with the clips that cause it rather than silently dropped from the list.
        """
        root = projects.get(project_id)
        project = sequence_view(root, sequence_id)
        listed = interchange.build_edl(project, track_id)
        return {**listed, "project_id": project_id, "revision": root.revision}

    @app.get("/v1/projects/{project_id}/otio", dependencies=auth)
    def project_otio(
        project_id: Identifier,
        projects: Store,
        sequence_id: SequenceRef | None = None,
    ):
        """The whole timeline as OpenTimelineIO JSON (read-only).

        Gaps are real children, so record times survive a round trip; each clip also carries
        its own AgentCut record under metadata, so colour, masks and keyframes are not lost.
        """
        root = projects.get(project_id)
        project = sequence_view(root, sequence_id)
        return {
            "project_id": project_id,
            "revision": root.revision,
            "otio": interchange.build_otio(project),
        }

    @app.get("/v1/projects/{project_id}/fcpxml", dependencies=auth)
    def project_fcpxml(
        project_id: Identifier,
        projects: Store,
        sequence_id: SequenceRef | None = None,
    ):
        """Final Cut Pro XML 1.9 for the whole timeline (read-only).

        Edits this exporter cannot say are listed in ``omitted`` with their clip ids; the
        ``complete`` flag says whether the spine is the whole cut.
        """
        root = projects.get(project_id)
        project = sequence_view(root, sequence_id)
        listed = interchange.build_fcpxml(project)
        return {**listed, "project_id": project_id, "revision": root.revision}

    @app.get("/v1/projects/{project_id}/jianying", dependencies=auth)
    def project_jianying(
        project_id: Identifier,
        projects: Store,
        sequence_id: SequenceRef | None = None,
    ):
        """剪映 / CapCut 明文 ``draft_content.json`` for this sequence (read-only).

        The draft this writes is the shape this engine's own reader understands (microsecond
        ranges, ``material_id`` -> ``materials``); everything a draft cannot carry is listed in
        ``omitted`` with its clip id, and ``complete`` says whether the draft is the whole cut.
        """
        root = projects.get(project_id)
        project = sequence_view(root, sequence_id)
        listed = interchange.build_jianying(project)
        return {**listed, "project_id": project_id, "revision": root.revision}

    @app.get("/v1/projects/{project_id}/xmeml", dependencies=auth)
    def project_xmeml(
        project_id: Identifier,
        projects: Store,
        sequence_id: SequenceRef | None = None,
    ):
        """FCP7 / Premiere «Export XML» (xmeml) for this sequence (read-only).

        Frame integers, one ``<track>`` per track, ``<file>`` carrying a ``pathurl``. A text
        layer or a speed change is left out and named in ``omitted``; ``complete`` says
        whether the XML is the whole cut. A fractional frame rate is refused rather than
        rounded to a whole one that this timeline is not.
        """
        root = projects.get(project_id)
        project = sequence_view(root, sequence_id)
        listed = interchange.build_xmeml(project)
        return {**listed, "project_id": project_id, "revision": root.revision}

    @app.post("/v1/projects/{project_id}/otio/import", dependencies=auth)
    def project_otio_import(
        project_id: Identifier,
        request: OtioImportRequest,
        projects: Store,
    ):
        """Plan an OTIO timeline as ordinary commands; apply writes one atomic revision.

        Media is matched by file name against assets this engine already verified. A name
        that matches nothing, or two different assets, is refused by name before anything
        is planned. ``apply`` needs a request_id and expected_revision, exactly like /edits.
        """
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        plan = interchange.otio_import_plan(project, request.document)
        if not request.apply:
            return {
                "committed": False,
                "project_id": project_id,
                "revision": root.revision,
                **plan,
            }
        reference = request.sequence_id
        known = reference in root.sequences if reference is not None else False
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=reference if known else None,
            sequence_name=reference if reference is not None and not known else None,
            commands=plan["commands"],  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, **plan}

    @app.post("/v1/projects/{project_id}/import", dependencies=auth)
    def project_interchange_import(
        project_id: Identifier,
        request: InterchangeImportRequest,
        projects: Store,
    ):
        """Read any supported project format into ordinary commands, naming what it cannot carry.

        OTIO, FCPXML, FCP7/Premiere XML, CMX3600 EDL and plaintext 剪映 drafts all come in through
        here; ``format`` may be left out because the document says what it is. The reply always
        echoes ``format`` plus ``omitted`` / ``complete``, so a caller can see what was not moved
        instead of trusting that a timeline arrived intact. ``apply`` writes one revision.

        Only the document text is accepted — this route never opens a path, so it cannot become a
        second, less-audited way to read files next to the media importer's own roots.
        """
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        if request.document is None:
            raise EditorError("INTERCHANGE_NO_DOCUMENT",
                              "pass document: the interchange text (or JSON for OTIO / a draft)",
                              422)
        plan = interchange.read_interchange(project, request.document, request.format)
        if not request.apply:
            return {
                "committed": False,
                "project_id": project_id,
                "revision": root.revision,
                **plan,
            }
        reference = request.sequence_id
        known = reference in root.sequences if reference is not None else False
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=reference if known else None,
            sequence_name=reference if reference is not None and not known else None,
            commands=plan["commands"],  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, **plan}

    @app.get("/v1/projects/{project_id}/transcript", dependencies=auth)
    def project_transcript(
        project_id: Identifier,
        projects: Store,
        sequence_id: SequenceRef | None = None,
        merge_gap_ms: float = 350.0,
        silence_ms: float = 600.0,
    ):
        """Read the spoken shape of this timeline: phrases in order, and the holes between them.

        This is the view an agent should read instead of frames: the caption clips already in the
        project, merged into phrases a conversation would call one breath, plus the silences
        between them as cut candidates. Nothing is decoded and nothing is written.
        """
        root = projects.get(project_id)
        project = sequence_view(root, sequence_id)
        return transcript.phrase_view(
            project,
            merge_gap_ms=merge_gap_ms,
            silence_ms=silence_ms,
        )

    @app.post("/v1/projects/{project_id}/transcript/cut", dependencies=auth)
    def project_transcript_cut(
        project_id: Identifier,
        request: TranscriptCutRequest,
        projects: Store,
    ):
        """Delete the chosen lines from every track they touch, as ordinary commands.

        Deleting a sentence is the same algebra as deleting a silence, so this reuses that planner:
        clips are cut right to left at the same boundaries on picture, voice, music and
        captions, and
        a caption fully inside a span is removed rather than split to nothing. Locked tracks and
        clips with a speed curve are skipped with the reason; a plan that cannot cut anything is
        refused by name. ``apply`` writes one revision through the normal ``/edits`` path.
        """
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        plan = transcript.cut_plan(
            project, [span.model_dump() for span in request.spans]
        )
        if not request.apply:
            return {
                "committed": False,
                "project_id": project_id,
                "revision": root.revision,
                **plan,
            }
        reference = request.sequence_id
        known = reference in root.sequences if reference is not None else False
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=reference if known else None,
            sequence_name=reference if reference is not None and not known else None,
            commands=plan["commands"],  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, **plan}

    @app.post("/v1/projects/{project_id}/frame-stability", dependencies=auth)
    def project_frame_stability(
        project_id: Identifier,
        request: FrameStabilityRequest,
        projects: Store,
    ):
        """Re-render these ticks three times in different orders and say whether the picture moved.

        The project has many gates proving the export and the preview agree; this is the one that
        asks whether *one* end is stable with itself. A derived-cache key that drops a dimension
        shows up here and nowhere else: either the same instant redraws differently, or two
        instants come back identical. The answer reports both, and `stable` only claims the first.
        """
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        media = require_media()
        return stability.probe(
            lambda at: media.render_frame(project, at, request.sequence_id),
            times=request.at_ticks,
            revision=root.revision,
        )

    @app.get("/v1/projects/{project_id}/overview", dependencies=auth)
    def project_overview(
        project_id: Identifier,
        projects: Store,
        count: int = 6,
        from_ticks: Ticks | None = None,
        to_ticks: Ticks | None = None,
        sequence_id: SequenceRef | None = None,
    ):
        """One contact sheet of the whole cut: N frames tiled into a single PNG.

        `preview_frame` answers "what does this instant look like"; this answers "does the cut
        look right" in one round trip. Every cell is the same byte-for-byte frame the frame route
        would return, and the header `X-Overview-Cells` lists the tick of each cell in reading
        order (left to right, then down), so nobody has to guess the layout.
        """
        root = projects.get(project_id)
        project = sequence_view(root, sequence_id)
        times = overview.pick_times(
            project, count, from_ticks=from_ticks, to_ticks=to_ticks
        )
        media = require_media()
        sheet = overview.render_overview(
            media.ffmpeg,
            lambda at: media.render_frame(project, at, sequence_id)[0],
            times,
            (project.settings.width, project.settings.height),
        )
        columns, rows = overview.grid(len(times))
        return Response(
            sheet,
            media_type="image/png",
            headers={
                "X-Overview-Grid": f"{columns}x{rows}",
                "X-Overview-Cells": ",".join(str(at) for at in times),
                "X-Project-Revision": str(project.revision),
                "Cache-Control": "no-store",
            },
        )

    @app.post("/v1/projects/{project_id}/audio/beats", dependencies=auth)
    def audio_beats(project_id: Identifier, request: BeatRequest, projects: Store):
        """Listen to one asset or clip and return where its beats fall, in timeline ticks.

        Read-only by construction: no request_id, no revision check, no write. The positions are
        ordinary ticks a person or an Agent turns into `marker.set`; making cuts out of them stays
        the existing `marker.split` plan. A clip is analysed in the source window it really plays
        and mapped back through its speed, so 200 % audio marks every quarter second of timeline.
        """
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        frame_ticks = project.settings.frame_ticks
        if request.asset_id is not None:
            asset = project.assets.get(request.asset_id)
            if asset is None:
                raise EditorError(
                    "NOT_FOUND", "asset is not in this project", 404, asset_id=request.asset_id
                )
            verified = asset.verified
            if verified is None or asset.kind not in ("audio", "video") or not verified.has_audio:
                raise EditorError(
                    "INVALID_BEAT_TARGET",
                    "this asset carries no audio to listen to: import a video or audio file, or "
                    "pick a different asset",
                    422,
                    asset_id=asset.id,
                    asset_kind=asset.kind,
                )
            source = Path(verified.path)
            if not source.is_file():
                raise EditorError(
                    "MEDIA_MISSING",
                    "source file is gone",
                    410,
                    asset_id=asset.id,
                    asset_label=source.name,
                )
            window_ticks = asset.duration_ticks or verified.duration_ticks
            start_seconds = 0.0
            position_ticks, source_in_ticks, speed = 0, 0, 1.0
            clip_id = None
        else:
            clip = project.clips.get(request.clip_id)
            if clip is None:
                raise EditorError(
                    "NOT_FOUND", "clip is not in this project", 404, clip_id=request.clip_id
                )
            # One shared answer for silence, loudness and beats: an audio-less clip, a detached
            # video and a speed curve are refused by name here instead of three times.
            problem = audio_scan_problem(project, clip)
            if problem:
                raise EditorError("INVALID_BEAT_TARGET", problem, 422, clip_id=clip.id)
            asset = project.assets[clip.asset_id]
            source = Path(asset.verified.path)
            if not source.is_file():
                raise EditorError(
                    "MEDIA_MISSING",
                    "source file is gone",
                    410,
                    clip_id=clip.id,
                    asset_id=asset.id,
                    asset_label=source.name,
                )
            speed = clip.speed_percent / 100
            position_ticks, source_in_ticks = clip.position_ticks, clip.source_in_ticks
            window_ticks = max(1, int(clip.duration_ticks * speed))
            start_seconds = source_in_ticks / TIMEBASE
            clip_id = clip.id
        result = beats_module.analyse(
            engine.ffmpeg,
            source,
            start_seconds,
            window_ticks / TIMEBASE,
            min_gap_ms=request.min_gap_ms,
            sensitivity=request.sensitivity,
        )
        marks: list[int] = []
        for seconds in result["seconds"][:BEAT_MARK_LIMIT]:
            local = beats_module.ticks_for(seconds / speed, frame_ticks)
            marks.append(beats_module.ticks_for((position_ticks + local) / TIMEBASE, frame_ticks))
        return {
            "asset_id": asset.id,
            "clip_id": clip_id,
            "beats": marks,
            "bpm": result["bpm"],
            "frame_ticks": frame_ticks,
            "analysed_ticks": window_ticks,
            "truncated": len(result["seconds"]) > BEAT_MARK_LIMIT,
            "min_gap_ms": request.min_gap_ms,
            "sensitivity": request.sensitivity,
            "revision": project.revision,
        }

    @app.post("/v1/projects/{project_id}/clips/{clip_id}/color-space", dependencies=auth)
    def clip_color_space(
        project_id: Identifier,
        clip_id: Identifier,
        request: ClipColorSpaceRead,
        projects: Store,
    ):
        """Say which tone curve this clip's file claims, without writing anything.

        `auto_source` on `clip.color_manage` is the writer; this is the read the interface and an
        Agent consult before committing. Both go through `colortags.detect_space`, so a space
        reported here is the space the reducer would have used, and a `null` here names the reason
        (`no_color_tags`, `no_transfer_tag`, `unmatched_transfer_tag`) with the tags as read.
        """
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        clip = project.clips.get(clip_id)
        if clip is None:
            raise EditorError("NOT_FOUND", "clip is not in this project", 404, clip_id=clip_id)
        asset = project.assets[clip.asset_id]
        if asset.kind == "audio":
            raise EditorError(
                "INVALID_COLOR",
                "an audio clip has no picture, so no transfer characteristic applies",
                422,
                clip_id=clip_id,
                asset_id=asset.id,
            )
        space, report = detect_space(asset.verified)
        return {
            "clip_id": clip.id,
            "asset_id": asset.id,
            "asset_label": asset.label,
            "space": space,
            "auto_source_would_work": space is not None,
            "color_spaces": list(COLOR_SPACES),
            **report,
        }

    @app.post("/v1/projects/{project_id}/clips/{clip_id}/loudness", dependencies=auth)
    def loudness_scan(
        project_id: Identifier, clip_id: Identifier, request: LoudnessRequest, projects: Store
    ):
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        clip = project.clips.get(clip_id)
        if clip is None:
            raise EditorError("NOT_FOUND", "clip is not in this project", 404, clip_id=clip_id)
        problem = audio_scan_problem(project, clip) or volume_problem(clip)
        if problem:
            raise EditorError("INVALID_LOUDNESS_TARGET", problem, 422, clip_id=clip_id)
        source = Path(project.assets[clip.asset_id].verified.path)
        if not source.is_file():
            raise EditorError(
                "MEDIA_MISSING",
                "source file is gone",
                410,
                clip_id=clip.id,
                asset_id=clip.asset_id,
                asset_label=source.name,
            )
        measured, plan = _meter_clip(engine, project, clip, request)
        read = {
            **measured,
            **plan,
            "target_lufs": request.target_lufs,
            "ceiling_dbtp": request.ceiling_dbtp,
        }
        if not request.apply:
            return {"committed": False, "project": root.model_dump(), "loudness": read}
        effects = clip.effects.model_copy(update={"gain": plan["gain"]})
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=[{"op": "clip.effects", "clip_id": clip_id, "effects": effects}],
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "loudness": read}

    @app.post("/v1/projects/{project_id}/tracks/{track_id}/loudness", dependencies=auth)
    def loudness_track(
        project_id: Identifier, track_id: Identifier, request: LoudnessRequest, projects: Store
    ):
        """Meter every clip on one track against a target and merge the gains into a single edit.

        A clip whose volume is already animated, or whose media cannot be metered, is reported as
        skipped with the reason rather than silently left at a different level.
        """
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        if next((track for track in project.tracks if track.id == track_id), None) is None:
            raise EditorError("NOT_FOUND", "track is not in this project", 404, track_id=track_id)
        if not any(item.track_id == track_id for item in project.clips.values()):
            raise EditorError("NOT_FOUND", "this track holds no clips", 404, track_id=track_id)
        commands: list[dict] = []
        clips: list[dict] = []
        for clip in sorted(
            (item for item in project.clips.values() if item.track_id == track_id),
            key=lambda item: item.position_ticks,
        ):
            problem = audio_scan_problem(project, clip) or volume_problem(clip)
            if problem:
                clips.append({"clip_id": clip.id, "skipped": problem})
                continue
            source = Path(project.assets[clip.asset_id].verified.path)
            if not source.is_file():
                raise EditorError(
                    "MEDIA_MISSING",
                    "source file is gone",
                    410,
                    clip_id=clip.id,
                    asset_id=clip.asset_id,
                    asset_label=source.name,
                )
            try:
                measured, plan = _meter_clip(engine, project, clip, request)
            except EditorError as failure:
                # One clip the meter cannot read must not stop the rest of the track from being
                # aligned: this is the whole-track button, and its promise is to report the reason.
                if failure.status != 422:
                    raise
                clips.append({"clip_id": clip.id, "skipped": failure.message})
                continue
            clips.append({"clip_id": clip.id, **measured, **plan})
            if abs(plan["gain"] - clip.effects.gain) > 0.01:
                effects = clip.effects.model_copy(update={"gain": plan["gain"]})
                commands.append(
                    {"op": "clip.effects", "clip_id": clip.id, "effects": effects.model_dump()}
                )
        metered = [item for item in clips if "skipped" not in item]
        body = {
            "clips": clips,
            "measured": len(metered),
            "changed": len(commands),
            "off_target": sum(1 for item in metered if not item["reaches_target"]),
            "target_lufs": request.target_lufs,
            "commands": commands,
        }
        if request.apply and not commands:
            raise EditorError(
                "INVALID_LOUDNESS_TARGET",
                "no clip on this track needs a new gain: it is already aligned",
                422,
                track_id=track_id,
            )
        if not request.apply:
            return {"committed": False, "project": root.model_dump(), "loudness": body}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "loudness": body}

    @app.get("/v1/projects/{project_id}/grade-capacity", dependencies=auth)
    def project_grade_capacity(project_id: Identifier, projects: Store):
        """How much of this project's inline lookup-table budget is used, and by which clips.

        Read-only, and the same numbers `clip.grade` is checked against: an Agent or the interface
        can see `room` before writing a LUT onto a track instead of discovering the ceiling by
        being refused. `sequence_id` is not needed — the budget belongs to the whole project.
        """
        return grade_capacity(projects.get(project_id))

    @app.post("/v1/projects/{project_id}/tracks/{track_id}/grade-apply", dependencies=auth)
    def grade_apply_track(
        project_id: Identifier,
        track_id: Identifier,
        request: GradeApplyTrackRequest,
        projects: Store,
    ):
        """Copy one clip's grade chain onto every other clip of that track.

        The plan asks the reducer's own rules per clip — the per-chain node cap, "an audio clip has
        no picture to grade", and the project's inline lookup-table budget from 1.104 — so the
        commands it returns are exactly ones the same reducer accepts, and a clip that cannot take
        the chain is reported with the numbers behind that. `apply=false` is the read-only plan an
        Agent submits through `timeline_edit`; `apply=true` writes them as one batch, so a whole
        track costs one revision and one history entry.
        """
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        if next((track for track in project.tracks if track.id == track_id), None) is None:
            raise EditorError("NOT_FOUND", "track is not in this project", 404, track_id=track_id)
        body = grade_apply_track_plan(project, request.clip_id, track_id, request.mode)
        if request.apply and not body["commands"]:
            raise EditorError(
                "GRADE_APPLY_EMPTY_TRACK",
                "no other clip on this track can take this grade chain",
                422,
                track_id=track_id,
                clip_id=request.clip_id,
                mode=request.mode,
                inspected=body["targets"],
                skipped=[
                    {"clip_id": item["clip_id"], "reason": item["skipped"]}
                    for item in body["clips"]
                    if "skipped" in item
                ],
            )
        if not request.apply:
            return {"committed": False, "project": root.model_dump(), "grade_application": body}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=body["commands"],  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "grade_application": body}

    @app.post("/v1/projects/{project_id}/clips/{clip_id}/attribute-plan", dependencies=auth)
    def clip_attribute_plan(
        project_id: Identifier,
        clip_id: Identifier,
        request: AttributePlanRequest,
        projects: Store,
    ):
        """Which aspects of one clip would become which other clips', as ordinary commands.

        剪映 calls it 粘贴属性，达芬奇 Paste Attributes，AE copies an effect stack: one promise that
        these aspects travel while nothing about where the clips sit moves. The categories are the
        ones `capabilities.attribute_categories` publishes, and what each one writes is decided by
        the reducer itself — `attributes.attribute_plan` (1.179) puts the whole candidate list
        through `apply_commands` in one pass, and only a refused pass falls back to asking target
        by target and category by category, so a clip that cannot take one category comes back with
        the reducer's own code and sentence while the categories that do land are still returned.
        Read-only: submit `commands` through
        `/edits` to write them as one batch at one revision. The reply is the plan alone:
        a read-only call must not hand back the whole project (12 MB at 20,000 clips).
        """
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        if request.source_clip_id != clip_id:
            # 路径与载荷各指一段时不知道该信谁——与 1.108 那条「clip 不在这条轨上」同一条规矩。
            raise EditorError(
                "NOT_FOUND",
                "path and body name different clips",
                404,
                clip_id=clip_id,
                source_clip_id=request.source_clip_id,
            )
        body = attribute_plan(
            project,
            request.source_clip_id,
            request.target_clip_ids,
            request.categories,
            request.sequence_id,
        )
        return {"committed": False, "attribute_plan": body}

    @app.post("/v1/projects/{project_id}/tracks/{track_id}/fade-adopt", dependencies=auth)
    def fade_adopt_track(
        project_id: Identifier,
        track_id: Identifier,
        request: FadeAdoptTrackRequest,
        projects: Store,
    ):
        """Move every pre-1.90 keyframe fade on one track into those clips' edge windows.

        The plan applies the reducer's own rule (`_fade_adoption`) per clip and property, so the
        commands it returns are exactly ones the same reducer accepts; a clip that cannot move
        is reported with the reason and the keyframes actually found on it. `apply=false` is the
        read-only plan an Agent submits through `timeline_edit`; `apply=true` writes them as one
        batch, so a whole track costs one revision and one history entry.
        """
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        if next((track for track in project.tracks if track.id == track_id), None) is None:
            raise EditorError("NOT_FOUND", "track is not in this project", 404, track_id=track_id)
        if not any(item.track_id == track_id for item in project.clips.values()):
            raise EditorError("NOT_FOUND", "this track holds no clips", 404, track_id=track_id)
        body = fade_adopt_track_plan(project, track_id)
        if request.apply and not body["commands"]:
            raise EditorError(
                "FADE_ADOPT_NONE",
                "no fade on this track is written as keyframes: there is nothing to move",
                422,
                track_id=track_id,
                inspected=body["adopted"] + body["skipped"],
                skipped=[
                    {
                        "clip_id": item["clip_id"],
                        "property": item["property"],
                        "reason": item["skipped"],
                    }
                    for item in body["clips"]
                    if "skipped" in item
                ],
            )
        if not request.apply:
            return {"committed": False, "project": root.model_dump(), "fade_adoption": body}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=body["commands"],  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "fade_adoption": body}

    @app.post("/v1/projects/{project_id}/markers/split", dependencies=auth)
    def marker_split(project_id: Identifier, request: MarkerSplitRequest, projects: Store):
        """Turn the markers on the ruler into the ordinary split commands that cut at them.

        A marker is how a human and an Agent say "here" about the same integer tick: a beat, a
        punch-in, a scene change. This endpoint only plans the splits, so the reducer stays the one
        place that decides what a split does to the source clock, keyframes, transitions and links.
        """
        project = projects.get(project_id)
        plan = marker_plan.split_plan(project, request.track_ids, request.at_ticks)
        if request.apply and not plan["commands"]:
            raise EditorError(
                "INVALID_MARKER_SPLIT",
                "no marker falls inside a clip far enough from its edges to split",
                422,
                markers=plan["markers"],
                track_ids=request.track_ids or [],
            )
        if not request.apply:
            return {"committed": False, "project": project.model_dump(), "markers": plan}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            commands=plan["commands"],  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "markers": plan}

    @app.post("/v1/projects/{project_id}/clips/{clip_id}/reframe", dependencies=auth)
    def reframe(
        project_id: Identifier, clip_id: Identifier, request: ReframeRequest, projects: Store
    ):
        """Follow the tracked subject: plan the pan-and-zoom that keeps it centred.

        The path comes from mask keyframes the tracker already wrote, so this endpoint adds no
        new editorial state — it converts one curve into another and hands back ordinary
        `keyframes.replace` commands. The reducer stays the only place that decides what a legal
        keyframe write is. `tolerance` trades keyframe count for how tightly the subject is held.
        """
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        commands, notes = reframe_plan.plan(
            project,
            clip_id=clip_id,
            max_scale=request.max_scale,
            tolerance=request.tolerance,
        )
        body = {"reframe": notes, "commands": commands}
        if not request.apply:
            return {"committed": False, "project": root.model_dump(), **body}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, **body}

    @app.post("/v1/projects/{project_id}/four-point", dependencies=auth)
    def four_point(project_id: Identifier, request: FourPointRequest, projects: Store):
        """Resolve two source points and two destination points into one placement.

        A shorter source than destination has to be re-timed, a longer one trimmed; both answers are
        reported back with the ticks that will actually be read, so nobody has to guess whether the
        engine silently dropped frames. What comes back is an ordinary `clip.insert` /
        `clip.overwrite`, so the reducer stays the only place that decides what a legal edit is and
        one apply is one revision.
        """
        project = projects.get(project_id)
        # The clip id must be a function of the request, not of the clock: a retry has to rebuild
        # the byte-identical batch, or its own receipt would come back as a conflict.
        digest = hashlib.sha1(request.request_id.encode()).hexdigest()[:12]
        commands, notes = fourpoint_module.plan(
            project,
            asset_id=request.asset_id,
            track_id=request.track_id,
            clip_id=f"c-{digest}",
            source_in_ticks=request.source_in_ticks,
            source_out_ticks=request.source_out_ticks,
            dest_in_ticks=request.dest_in_ticks,
            dest_out_ticks=request.dest_out_ticks,
            fit=request.fit,
            mode=request.mode,
            ripple_track_ids=request.ripple_track_ids,
        )
        body = {"four_point": notes, "commands": commands}
        if not request.apply:
            return {"committed": False, "project": project.model_dump(), **body}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, **body}

    @app.post("/v1/projects/{project_id}/tracks/{track_id}/silence", dependencies=auth)
    def silence_track(
        project_id: Identifier, track_id: Identifier, request: SilenceRequest, projects: Store
    ):
        """Scan every clip on one track and merge the cut plans, working right to left.

        Only this track moves: a leading hole closes by shifting what follows it on the same track,
        so other tracks keep their positions and stay aligned through groups or links.
        """
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        if next((track for track in project.tracks if track.id == track_id), None) is None:
            raise EditorError("NOT_FOUND", "track is not in this project", 404, track_id=track_id)
        if not any(item.track_id == track_id for item in project.clips.values()):
            raise EditorError("NOT_FOUND", "this track holds no clips", 404, track_id=track_id)
        frame_ticks = project.settings.frame_ticks
        commands: list[dict] = []
        scanned: list[dict] = []
        for clip in sorted(
            (item for item in project.clips.values() if item.track_id == track_id),
            key=lambda item: -item.position_ticks,
        ):
            problem = audio_scan_problem(project, clip)
            if problem:
                scanned.append({"clip_id": clip.id, "skipped": problem})
                continue
            source = Path(project.assets[clip.asset_id].verified.path)
            if not source.is_file():
                raise EditorError(
                    "MEDIA_MISSING",
                    "source file is gone",
                    410,
                    clip_id=clip.id,
                    asset_id=clip.asset_id,
                    asset_label=source.name,
                )
            result = silence.analyse(
                engine.ffmpeg,
                source,
                clip,
                frame_ticks,
                threshold_db=request.threshold_db,
                min_silence_ms=request.min_silence_ms,
                from_ticks=request.from_ticks,
                to_ticks=request.to_ticks,
            )
            spans = [*result["gaps"], *result["edges"]]
            plan = silence.cut_plan(clip, spans, edges=True)
            commands.extend(plan)
            scanned.append(
                {
                    "clip_id": clip.id,
                    "gaps": result["gaps"],
                    "edges": result["edges"],
                    "removed_ticks": sum(span["length_ticks"] for span in spans),
                    "commands": plan,
                }
            )
        body = {
            "clips": scanned,
            "removed_ticks": sum(item.get("removed_ticks", 0) for item in scanned),
            "commands": commands,
        }
        if request.apply and not commands:
            raise EditorError(
                "INVALID_SILENCE_TARGET",
                "no quiet stretch on this track is long enough to cut",
                422,
                track_id=track_id,
            )
        if not request.apply:
            return {"committed": False, "project": root.model_dump(), "silence": body}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "silence": body}

    @app.post("/v1/projects/{project_id}/speech-captions", dependencies=auth)
    def speech_captions(project_id: Identifier, request: SpeechCaptionsRequest, projects: Store):
        """Transcribe speech on one clip (or every clip on one track) into subtitle cues.

        The plan is the single ordinary `captions.import` command, so landing it is undoable as one
        step and a client that wants different wording can take the SRT and submit it itself. Clips
        that cannot carry audio are skipped with the reason, the same judgement the silence scan
        makes, so one answer cannot differ between the two buttons.
        """
        engine = require_media()
        if request.clip_id is None and request.track_id is None:
            raise EditorError(
                "INVALID_REQUEST",
                "name a clip_id or a track_id to transcribe",
                422,
                clip_id=None,
                track_id=None,
            )
        if request.clip_id is not None and request.track_id is not None:
            raise EditorError(
                "INVALID_REQUEST",
                "name either a clip_id or a track_id, not both",
                422,
                clip_id=request.clip_id,
                track_id=request.track_id,
            )
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        if request.clip_id is not None:
            chosen = project.clips.get(request.clip_id)
            if chosen is None:
                raise EditorError(
                    "NOT_FOUND", "clip is not in this project", 404, clip_id=request.clip_id
                )
            clips = [chosen]
        else:
            if (
                next((track for track in project.tracks if track.id == request.track_id), None)
                is None
            ):
                raise EditorError(
                    "NOT_FOUND", "track is not in this project", 404, track_id=request.track_id
                )
            clips = sorted(
                (c for c in project.clips.values() if c.track_id == request.track_id),
                key=lambda c: c.position_ticks,
            )
            if not clips:
                raise EditorError(
                    "NOT_FOUND", "this track holds no clips", 404, track_id=request.track_id
                )
        cues: list[dict] = []
        scanned: list[dict] = []
        model_name = ""
        for clip in clips:
            problem = audio_scan_problem(project, clip)
            if problem:
                # The clip the caller named is refused with its reason; on a track the unsuitable
                # ones are skipped so one bad clip cannot hide the captions the rest carry.
                if request.clip_id is not None:
                    raise EditorError("INVALID_CAPTIONS_TARGET", problem, 422, clip_id=clip.id)
                scanned.append({"clip_id": clip.id, "skipped": problem})
                continue
            source = Path(project.assets[clip.asset_id].verified.path)
            if not source.is_file():
                raise EditorError(
                    "MEDIA_MISSING",
                    "source file is gone",
                    410,
                    clip_id=clip.id,
                    asset_id=clip.asset_id,
                    asset_label=source.name,
                )
            clip_cues, model_name = asr_module.cues_from_clip(
                engine.ffmpeg,
                source,
                clip,
                project.settings.frame_ticks,
                language=request.language,
                dirs=engine.asr_dirs,
                max_chars=request.max_chars,
            )
            cues.extend(clip_cues)
            scanned.append({"clip_id": clip.id, "cues": clip_cues})
        if not cues:
            raise EditorError(
                "SPEECH_NOT_FOUND",
                "no speech was recognised in the selected material",
                422,
                track_id=request.track_id,
                clip_id=request.clip_id,
            )
        command = asr_module.caption_command(cues, scope=request.clip_id or request.track_id or "")
        commands: list[dict] = []
        if request.replace_track_id is not None:
            replaced = next((t for t in project.tracks if t.id == request.replace_track_id), None)
            if replaced is None:
                raise EditorError(
                    "NOT_FOUND",
                    "the track to replace does not exist in this project",
                    404,
                    track_id=request.replace_track_id,
                )
            replaced_clips = sorted(
                (c for c in project.clips.values() if c.track_id == replaced.id),
                key=lambda c: c.position_ticks,
            )
            for clip in replaced_clips:
                commands.append({"op": "clip.remove", "clip_id": clip.id})
            # The text asset goes too: the new import re-mints the same content-derived ids, so a
            # lingering asset would refuse the very import this batch ends with.
            for asset_id in sorted({c.asset_id for c in replaced_clips}):
                commands.append({"op": "asset.remove", "asset_id": asset_id})
            commands.append({"op": "track.remove", "track_id": replaced.id})
        commands.append(command)
        body = {
            "cues": cues,
            "srt": asr_module.srt_body(cues),
            "command": command,
            "commands": commands,
            "language": request.language,
            "model": model_name,
            "clips": scanned,
        }
        if not request.apply:
            return {"committed": False, "project": root.model_dump(), "speech": body}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "speech": body}

    @app.post("/v1/projects/{project_id}/tracks/{track_id}/duck", dependencies=auth)
    def duck_track(
        project_id: Identifier, track_id: Identifier, request: DuckRequest, projects: Store
    ):
        """Pull one track's gain down while the driver tracks are talking.

        The listening is the same scan the 去空白 button uses, so a duck boundary is the boundary a
        cut would land on. What comes back is ordinary `keyframes.replace` commands — one per clip —
        which the reducer applies in a single transaction, so a click is one revision and undo is
        the whole duck.
        """
        engine = require_media()
        root = projects.get(project_id)
        project = sequence_view(root, request.sequence_id)
        if next((track for track in project.tracks if track.id == track_id), None) is None:
            raise EditorError("NOT_FOUND", "track is not in this project", 404, track_id=track_id)
        if not any(item.track_id == track_id for item in project.clips.values()):
            raise EditorError("NOT_FOUND", "this track holds no clips", 404, track_id=track_id)
        frame_ticks = project.settings.frame_ticks
        driver_ids = request.driver_track_ids
        if driver_ids is None:
            driver_ids = [
                track.id
                for track in project.tracks
                if track.kind == "audio" and track.id != track_id
            ]
        speech: list[dict] = []
        skipped: list[dict] = []
        for driver_id in driver_ids:
            if driver_id == track_id:
                raise EditorError(
                    "INVALID_DUCK", "a track cannot duck itself", 422, track_id=track_id
                )
            if next((track for track in project.tracks if track.id == driver_id), None) is None:
                raise EditorError(
                    "NOT_FOUND", "driver track is not in this project", 404, track_id=driver_id
                )
            drivers = sorted(
                (clip for clip in project.clips.values() if clip.track_id == driver_id),
                key=lambda clip: clip.position_ticks,
            )
            for clip in drivers:
                problem = audio_scan_problem(project, clip)
                if problem:
                    skipped.append({"clip_id": clip.id, "skipped": problem})
                    continue
                source = Path(project.assets[clip.asset_id].verified.path)
                if not source.is_file():
                    raise EditorError(
                        "MEDIA_MISSING",
                        "source file is gone",
                        410,
                        clip_id=clip.id,
                        asset_id=clip.asset_id,
                        asset_label=source.name,
                    )
                result = silence.analyse(
                    engine.ffmpeg,
                    source,
                    clip,
                    frame_ticks,
                    threshold_db=request.threshold_db,
                    min_silence_ms=request.min_silence_ms,
                )
                spans = [*result["gaps"], *result["edges"]]
                for start, stop in duck.loud_spans(clip, spans):
                    speech.append(
                        {
                            "from_ticks": clip.position_ticks + start,
                            "to_ticks": clip.position_ticks + stop,
                        }
                    )
        low = duck.depth_gain(request.depth_db)
        attack = duck.ramp_ticks(request.attack_ms, frame_ticks)
        hold = duck.ramp_ticks(request.hold_ms, frame_ticks)
        release = duck.ramp_ticks(request.release_ms, frame_ticks)
        commands: list[dict] = []
        planned: list[dict] = []
        targets = sorted(
            (clip for clip in project.clips.values() if clip.track_id == track_id),
            key=lambda clip: clip.position_ticks,
        )
        for clip in targets:
            problem = audio_scan_problem(project, clip)
            if problem:
                planned.append({"clip_id": clip.id, "skipped": problem})
                continue
            spans = [
                (
                    max(0, item["from_ticks"] - clip.position_ticks),
                    min(clip.duration_ticks, item["to_ticks"] - clip.position_ticks),
                )
                for item in speech
            ]
            points = duck.envelope(
                [span for span in spans if span[1] > span[0]],
                clip.duration_ticks,
                frame_ticks,
                low=low,
                attack_ticks=attack,
                hold_ticks=hold,
                release_ticks=release,
            )
            made = duck.plan_clip(clip, points)
            existing = sum(1 for key in clip.keyframes if key.property == "gain")
            commands.extend(made)
            planned.append(
                {
                    "clip_id": clip.id,
                    "keyframes": len(points),
                    "replaced_gain_keyframes": existing if points else 0,
                    "ducked_ticks": duck.ducked_ticks(points),
                    "commands": made,
                }
            )
        if len(commands) > 90:
            raise EditorError(
                "DUCK_PLAN_TOO_LARGE",
                f"{len(commands)} clips need a duck at once; duck one stretch at a time with "
                "from/to on the driver scan, or group the bed into fewer clips",
                422,
                track_id=track_id,
            )
        body = {
            "speech": speech,
            "clips": planned,
            "skipped": skipped,
            "depth_db": request.depth_db,
            "gain": low,
            "attack_ticks": attack,
            "hold_ticks": hold,
            "release_ticks": release,
            "commands": commands,
        }
        if request.apply and not commands:
            raise EditorError(
                "INVALID_DUCK",
                "nothing on this track needs ducking: the drivers are quiet the whole time",
                422,
                track_id=track_id,
            )
        if not request.apply:
            return {"committed": False, "project": root.model_dump(), "duck": body}
        batch = EditBatch(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            sequence_id=request.sequence_id,
            commands=commands,  # type: ignore[arg-type]
            dry_run=request.dry_run,
        )
        mutation = projects.mutate(project_id, batch).model_dump()
        return {**mutation, "duck": body}

    # ---------- render jobs ----------

    @app.post("/v1/projects/{project_id}/renders", dependencies=auth)
    def create_render(
        project_id: Identifier, http_request: Request, request: RenderRequest, projects: Store
    ):
        runtime = require_jobs()
        project = projects.get(project_id)
        actor = getattr(http_request.state, "actor", None)
        job, plan = runtime.submit(project, request, actor=actor)
        return {"job": job.model_dump(), "plan": plan}

    @app.get("/v1/projects/{project_id}/bundle", dependencies=auth)
    def project_bundle(project_id: Identifier, projects: Store):
        project = projects.get(project_id)
        path = export_bundle(project)
        return FileResponse(
            path,
            media_type="application/zip",
            filename=f"{project.name}.agentcut.zip",
            background=BackgroundTask(path.unlink, missing_ok=True),
        )

    @app.post(
        "/v1/bundle",
        dependencies=auth,
        response_model=MutationResult,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    async def project_import_bundle(request: Request, request_id: Identifier, projects: Store):
        engine = require_media()
        digest = hashlib.sha256()
        received = 0
        try:
            with tempfile.TemporaryFile() as incoming:
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > MAX_BUNDLE_BYTES:
                        raise EditorError("BUNDLE_TOO_LARGE", "bundle exceeds 32 GiB", 413)
                    digest.update(chunk)
                    incoming.write(chunk)
                incoming.seek(0)
                return await run_in_threadpool(
                    import_bundle,
                    projects,
                    engine,
                    incoming,
                    BundleImport(request_id=request_id, content_sha256=digest.hexdigest()),
                )
        except OSError:
            raise EditorError(
                "STORAGE_UNAVAILABLE", "bundle upload failed; retry with the same request_id", 503
            ) from None

    @app.get("/v1/projects/{project_id}/clips", dependencies=auth)
    def read_clips(
        project_id: Identifier,
        projects: Store,
        clips: list[Identifier] | None = Query(default=None),
        revision: Revision | None = None,
        sequence_id: SequenceRef | None = None,
    ):
        """Read just the named clips' records, instead of the whole project document.

        `GET /v1/projects/{id}` ships the document (tens of megabytes on a large timeline), which is
        what the compositor needs and nothing else does. Every record here is the same object that
        document holds — this route adds no judgment, only a narrower read. `clips` is required:
        a caller that wants everything should use the project route, and saying so beats returning
        a 12 MB answer nobody asked for.
        """
        from .timeline import resolve_sequence, sequence_view

        root = projects.get(project_id, revision)
        resolved = resolve_sequence(root, sequence_id)
        project = sequence_view(root, resolved)
        if not clips:
            raise EditorError(
                "INVALID_REQUEST",
                f"clips is required: name the ids to read, or GET /v1/projects/{project_id}"
                " for the whole document",
                422,
                requested=len(clips or []),
            )
        if len(clips) > CLIP_SUBSET_LIMIT:
            raise EditorError(
                "INVALID_REQUEST",
                f"clips takes at most {CLIP_SUBSET_LIMIT} ids per request; got {len(clips)}."
                " Split the list, or read the whole project document",
                422,
                requested=len(clips),
                limit=CLIP_SUBSET_LIMIT,
            )
        wanted = list(dict.fromkeys(clips))
        missing = [clip_id for clip_id in wanted if clip_id not in project.clips]
        if missing:
            raise EditorError(
                "NOT_FOUND",
                "clip is not in this project",
                404,
                clip_ids=",".join(missing),
            )
        return {
            "project_id": project.id,
            "revision": project.revision,
            "sequence_id": resolved,
            "clips": {
                clip_id: project.clips[clip_id].model_dump(mode="json") for clip_id in wanted
            },
        }

    @app.get("/v1/projects/{project_id}/preview-manifest", dependencies=auth)
    def preview_plan(
        project_id: Identifier,
        projects: Store,
        revision: Revision | None = None,
        sequence_id: SequenceRef | None = None,
        clips: list[Identifier] | None = Query(default=None),
        no_clips: bool = Query(default=False),
    ):
        """Animation curves for the whole project, or only for the clips `clips` names.

        Omitting `clips` is the pre-1.183 request and stays byte-identical. A subset narrows only
        the `clips` key; an unknown id is refused by name instead of quietly dropping that clip,
        because a manifest missing one clip looks exactly like a clip with nothing animated.
        """
        project = projects.get(project_id, revision)
        if no_clips and clips:
            raise EditorError(
                "INVALID_REQUEST",
                "no_clips and clips are two different asks; name the ids, or send"
                " no_clips=1 for none, or send neither for the whole project",
                422,
                named=len(clips),
            )
        if no_clips:
            return preview_manifest(project, sequence_id, clip_ids=[])
        if clips is None:
            return preview_manifest(project, sequence_id)
        if len(clips) > CLIP_SUBSET_LIMIT:
            raise EditorError(
                "INVALID_REQUEST",
                f"clips takes at most {CLIP_SUBSET_LIMIT} ids per request;"
                f" got {len(clips)}. Split the list, or omit it for the whole project",
                422,
                requested=len(clips),
                limit=CLIP_SUBSET_LIMIT,
            )
        wanted = list(dict.fromkeys(clips))
        missing = [clip_id for clip_id in wanted if clip_id not in project.clips]
        if missing:
            raise EditorError(
                "NOT_FOUND",
                "clip is not in this project",
                404,
                clip_ids=",".join(missing),
            )
        return preview_manifest(project, sequence_id, clip_ids=wanted)

    @app.post("/v1/preview-manifest", dependencies=auth)
    def preview_candidate(project: Project, sequence_id: SequenceRef | None = None):
        """Compile a validated dry-run snapshot without opening media or writing state."""
        validate_timeline(project)
        return preview_manifest(project, sequence_id)

    @app.post("/v1/mask/preview", dependencies=auth)
    def mask_preview(
        mask: ShapeMask,
        frame_width: Annotated[int, Query(ge=16, le=16_384)] = 1920,
        frame_height: Annotated[int, Query(ge=16, le=16_384)] = 1080,
    ):
        return {"mask_image": mask_image(mask, frame_width, frame_height)}

    @app.post("/v1/lut/parse", dependencies=auth)
    def lut_parse(request: LutParse) -> dict:
        """Read a `.cube` file with the engine's one parser and return a ready grade node payload.

        The client uploads the text instead of interpreting it: there is exactly one meaning for a
        LUT here, so the interface and an Agent cannot disagree about a table's grid, domain or
        channel order. The file's own header decides which flavour comes back — `kind` is `lut`
        for a per-channel table and `lut3d` for a cross-channel cube (whose reply also carries
        `resampled_from` when the grid was larger than `grade_limits.max_lut3d_size`), and either
        way the payload goes straight into `clip.color.grade`.
        """
        return parse_cube(request.content)

    @app.post("/v1/animation/curve", dependencies=auth)
    def animation_curve(clip: Clip, property: Property):
        """Read-only geometry for a committed or dry-run clip; no media IO or writes."""
        return graph_curve(clip, property)

    @app.post("/v1/animation/layer_curve", dependencies=auth)
    def animation_layer_curve(clip: Clip, property: LayerProperty, layer: int, quantum: Ticks):
        """那一层那一个数的阶梯——只读，交回的就是**导出执行的那张窗表**。

        1.192 起那一层会按窗挪位置、改大小、自己淡，1.204 起还会转；这些台阶以前只能在检查器里
        逐枚敲，曲线编辑器里看不见——因为读路由只认 `Clip.keyframes` 那一条数组。这一条补的就是
        那一句：`limits` 取自契约的同一条带，`curve` 取自同一份 `layer_schedule`，刻度折的那一次
        与别的针一样，界面因此不自己算任何数。`layer` 是「这一条链上启用的那几层」里的第几个
        （顺序只由 `animation.layer_nodes` 数一次），越界点名拒并说清一共几层。
        """
        nodes = layer_nodes(clip)
        if quantum < 1:
            raise EditorError(
                "LAYER_CURVE_TARGET",
                f"那一层的阶梯得按一个格长来切：quantum 给的是 {quantum}，"
                "要至少 1 格（界面传的就是这条轨的渲染格长）",
                422,
                layer=layer,
                quantum=quantum,
                layers=len(nodes),
            )
        if not 0 <= layer < len(nodes):
            raise EditorError(
                "LAYER_CURVE_TARGET",
                f"这条片段的链上没有第 {layer + 1} 层外部画面（启用的现在一共 {len(nodes)} 层）："
                "先在检查器里选一层，或把这一层加回来",
                422,
                layer=layer,
                layers=len(nodes),
                property=property,
            )
        return layer_graph(clip, layer, property, quantum)

    @app.post("/v1/animation/sample", dependencies=auth)
    def animation_sample(clip: Clip, at_ticks: Ticks):
        """Read-only values for a saved or dry-run clip; no media IO or writes."""
        return {"values": sample_values(clip, at_ticks)}

    @app.get("/v1/projects/{project_id}/frame", dependencies=auth)
    def composite_frame(
        project_id: Identifier,
        at_ticks: Ticks,
        projects: Store,
        revision: Revision | None = None,
        sequence_id: SequenceRef | None = None,
    ):
        project = projects.get(project_id, revision)
        data, at = require_media().render_frame(project, at_ticks, sequence_id)
        return Response(
            data,
            media_type="image/png",
            headers={
                "X-Frame-Ticks": str(at),
                "X-Project-Revision": str(project.revision),
                "Cache-Control": "no-store",
            },
        )

    @app.get("/v1/projects/{project_id}/clips/{clip_id}/sample", dependencies=auth)
    def clip_sample(
        project_id: Identifier,
        clip_id: Identifier,
        at_ticks: Ticks,
        projects: Store,
        revision: Revision | None = None,
        sequence_id: SequenceRef | None = None,
    ):
        project = sequence_view(projects.get(project_id, revision), sequence_id)
        clip = project.clips.get(clip_id)
        if clip is None:
            raise EditorError(
                "NOT_FOUND", "clip does not exist", 404, clip_id=clip_id, revision=revision
            )
        return {
            "revision": project.revision,
            "values": sample_values(clip, at_ticks),
        }

    @app.get("/v1/projects/{project_id}/render-plan", dependencies=auth)
    def render_plan(
        project_id: Identifier,
        preset_id: Identifier,
        projects: Store,
        revision: Revision | None = None,
        sequence_id: SequenceRef | None = None,
        fit: RenderFit = "contain",
        range: RenderRange = "full",
        transparent: bool = False,
        timecode: str | None = None,
        output_fps: str | None = None,
        colour_tag: str | None = None,
    ):
        project = projects.get(project_id, revision)
        plan = plan_for(
            project,
            preset_id,
            sequence_id=sequence_id,
            fit=fit,
            range_mode=range,
            transparent=transparent,
            timecode=timecode,
            output_frame_rate=parse_frame_rate(output_fps),
            colour_tag=colour_tag,
        )
        return {"plan": plan.as_dict(), "argv_preview": plan.ffmpeg_argv("ffmpeg", "out.mp4")}

    @app.post("/v1/projects/{project_id}/master/loudness", dependencies=auth)
    def master_loudness(project_id: Identifier, request: MasterLoudnessRequest, projects: Store):
        """Land the whole mix on a platform loudness target, measured through a throwaway render.

        The probe uses the same audio graph the export uses, so the number is the mix the viewer
        hears — overlaps, fades, ducking and the current master gain included. Applying the result
        writes one `project.update`, so it is one revision and undo returns the previous gain.
        """
        engine = require_media()
        project = projects.get(project_id)
        if not project.clips:
            raise EditorError(
                "INVALID_LOUDNESS_TARGET", "an empty timeline has no mix to measure", 422
            )
        settings = project.settings
        current = settings.master_gain
        measured = probe_mix(engine.ffmpeg, project, Path(engine.cache_dir) / "master-probe")
        # With the limiter on, the ceiling is enforced by the limiter itself, so it must not also
        # clamp the gain — otherwise asking for -14 LUFS at -1 dBTP silently gives you a quiet mix.
        plan = master_plan(
            measured,
            current,
            target_lufs=request.target_lufs,
            ceiling_dbtp=0.0 if request.limiter else request.ceiling_dbtp,
        )
        body = {
            "target_lufs": request.target_lufs,
            "ceiling_dbtp": request.ceiling_dbtp,
            **measured,
            **plan,
        }
        if not request.apply:
            return {"committed": False, "project": project.model_dump(), "master": body}
        if plan["proposed_master_gain"] == current:
            raise EditorError(
                "INVALID_LOUDNESS_TARGET",
                f"the mix already sits at {plan['predicted_lufs']} LUFS with master_gain "
                f"{current}; nothing to change",
                422,
            )
        if request.dry_run:
            # A dry run reports what it would write; `project.update` has no dry-run of its own,
            # so the caller gets the prospective gain without a revision being spent.
            return {"committed": False, "project": project.model_dump(), "master": body}
        update = ProjectUpdate(
            request_id=request.request_id,
            expected_revision=request.expected_revision,
            settings=settings.model_copy(
                update={
                    "master_gain": plan["proposed_master_gain"],
                    "master_limiter": request.limiter,
                    "master_ceiling_dbtp": request.ceiling_dbtp,
                }
            ),
        )
        mutation = projects.update_project(project_id, update)
        # Measure the mix the project now describes, so the answer is what the export will be and
        # not a projection of it. The extra probe costs about a second and reads the same graph.
        written = mutation.project
        after = probe_mix(engine.ffmpeg, written, Path(engine.cache_dir) / "master-probe")
        reported = {
            **body,
            "after": after,
            "after_master_gain": written.settings.master_gain,
            "limiter": written.settings.master_limiter,
            "ceiling_applied_dbtp": written.settings.master_ceiling_dbtp,
            "measured_reaches_target": abs(after["integrated_lufs"] - request.target_lufs) <= 0.5,
        }
        return {**mutation.model_dump(), "master": reported}

    @app.post("/v1/projects/{project_id}/renders/batch", dependencies=auth)
    def create_render_batch(
        project_id: Identifier,
        http_request: Request,
        request: RenderBatch,
        projects: Store,
    ):
        """Queue a whole delivery in one call: every item compiles or nothing is queued."""
        runtime = require_jobs()
        project = projects.get(project_id)
        results = runtime.submit_batch(
            project, request, actor=getattr(http_request.state, "actor", None)
        )
        return {
            "committed": not request.dry_run,
            "jobs": [job.model_dump() for job, _ in results],
            "plans": [plan for _, plan in results],
        }

    @app.get("/v1/jobs/{job_id}", dependencies=auth)
    def get_job(job_id: Identifier, projects: Store):
        runtime = require_jobs()
        job = runtime.get(job_id)
        plan = None
        if job.status in ("queued", "running"):
            try:
                project = projects.get(job.project_id, job.revision)
                # Through `plan_for`, with the job's own range and matte: a plan shown beside a job
                # has to be the plan that job will render, not one rebuilt with the defaults.
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
                ).as_dict()
            except EditorError:
                plan = None
        data = job.model_dump()
        data["progress"] = job.progress
        return {"job": data, "plan": plan}

    @app.get("/v1/jobs/{job_id}/wait", dependencies=auth)
    async def wait_job(
        job_id: Identifier,
        projects: Store,
        timeout: Annotated[float, Query(ge=0, le=120)] = 30.0,
        poll: Annotated[float, Query(ge=0.05, le=2.0)] = 0.25,
    ):
        """等一台作业到终态，或等到这一次自己超时——交回的还是同一份作业文档。

        排队中的作业不该要人一秒打一次：`render_start` 之后拿回 job id，然后一次调用等到
        `succeeded`/`failed`/`cancelled`。超时不是错误——`timed_out` 说清楚「还在跑」，
        调用方可以换个更长的 timeout 再来，或者改去看 `job_status`。
        """
        deadline = time.monotonic() + timeout
        waited = 0.0
        while True:
            answer = get_job(job_id, projects)
            status = answer["job"]["status"]
            if status in TERMINAL or time.monotonic() >= deadline:
                answer["waited_ms"] = int(waited * 1000)
                answer["timed_out"] = status not in TERMINAL
                return answer
            await asyncio.sleep(poll)
            waited = max(0.0, min(timeout, timeout - (deadline - time.monotonic())))

    @app.get("/v1/projects/{project_id}/jobs", dependencies=auth)
    def list_jobs(
        project_id: Identifier,
        projects: Store,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ):
        # An unknown project answers 404 like every other read of it, not an empty list that
        # looks like a timeline with no renders.
        projects.get(project_id)
        runtime = require_jobs()
        return {"jobs": runtime.list_for_project(project_id, limit)}

    @app.get("/v1/jobs/{job_id}/verify", dependencies=auth)
    def verify_delivery_route(
        job_id: Identifier,
        projects: Store,
        target_lufs: Annotated[float | None, Query(ge=-30.0, le=-6.0)] = None,
        ceiling_dbtp: Annotated[float | None, Query(ge=-9.0, le=0.0)] = None,
        duration_tolerance: Annotated[float, Query(ge=0.0, le=5.0)] = 0.25,
    ):
        """Verify a delivered file against the plan that job queued, using the engine's instruments.

        `output_checked` only says a probe agreed the file is readable. This reads the file: its
        length against the compiled plan's, its picture size and rate against the preset's, and its
        EBU R128 loudness and true peak when the caller names a target. A failing check is a
        verdict with numbers, not an exception — the answer can be "no, 5.6 LU off".
        """
        runtime = require_jobs()
        engine = require_media()
        job = runtime.get(job_id)
        project = projects.get(job.project_id, job.revision)
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
        ).as_dict()
        return deliverable.verify_delivery(
            engine.ffmpeg,
            engine.ffprobe,
            job,
            project,
            plan,
            target_lufs=target_lufs,
            ceiling_dbtp=ceiling_dbtp,
            duration_tolerance=duration_tolerance,
        )

    @app.post("/v1/jobs/{job_id}/cancel", dependencies=auth)
    def cancel_job(job_id: Identifier):
        runtime = require_jobs()
        return {"job": runtime.cancel(job_id).model_dump()}

    @app.post("/v1/outputs/roots", dependencies=auth)
    def add_output_root(request: ImportRequest):
        runtime = require_jobs()
        return {"output_roots": runtime.add_output_root(request.path)}

    @app.get("/v1/outputs/roots", dependencies=auth)
    def output_roots():
        runtime = require_jobs()
        return {"output_roots": runtime.describe_output_roots()}

    return app
