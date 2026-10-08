"""Official MCP stdio adapter; the HTTP service remains the sole project writer.

Every tool here is a thin, typed pass-through: no editing, media or scheduling rule is
re-implemented on this side, so an Agent and the desktop UI cannot diverge.
"""

import json
from typing import Any
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .contracts import (
    Clip,
    ClipStabilizeRequest,
    CreateProject,
    DuckRequest,
    EditBatch,
    FourPointRequest,
    Identifier,
    ImportRequest,
    LutParse,
    MarkerSplitRequest,
    MaskTrackRequest,
    MasterLoudnessRequest,
    MutationResult,
    Project,
    ProjectUpdate,
    Property,
    ReframeRequest,
    RenderBatch,
    RenderFit,
    RenderRequest,
    RestoreProject,
    Revision,
    SilenceRequest,
    SpeechCaptionsRequest,
    Ticks,
)

INSTRUCTIONS = (
    "AgentCut 本地剪辑引擎。发现能力先读 editor_capabilities，契约读 editor_contracts。"
    "时间一律整数 tick（70,560,000/秒）；写入需要 request_id，编辑需要 expected_revision。"
    "复杂编辑先 timeline_edit(dry_run=true)，再用同一 request_id 正式提交。"
    "REVISION_CONFLICT 表示他人已改：重读项目并换新 request_id。"
    "网络丢失时用同一 request_id 与同一 payload 重试，不会重复执行。"
    "剪真实视频的顺序：media_import(path) → timeline_edit 内 asset.import(probe_id) → "
    "render_plan 预检 → render_start → job_status 轮询。"
    "clip 时间必须落在序列帧/采样边界上；素材必须是 media_import 返回的可信记录。"
)


def create_mcp(base_url: str, token: str) -> FastMCP:
    url = urlsplit(base_url)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost"}
        or url.username
        or url.password
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise ValueError("AGENTCUT_API_URL must be a local HTTP origin")
    if len(token) < 32:
        raise ValueError("AGENTCUT_TOKEN must contain at least 32 characters")
    headers = {"Authorization": f"Bearer {token}"}
    server = FastMCP("AgentCut", instructions=INSTRUCTIONS)

    async def call(
        method: str, path: str, payload: dict | None = None, timeout: float = 60
    ) -> dict:
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as session:
                response = await session.request(
                    method, base_url.rstrip("/") + path, headers=headers, json=payload
                )
        except httpx.HTTPError as error:
            raise ToolError(
                json.dumps(
                    {
                        "code": "API_UNAVAILABLE",
                        "message": "API unavailable; retry writes with the same id",
                    }
                )
            ) from error
        if response.is_error:
            try:
                error = response.json()["error"]
            except (ValueError, KeyError):
                error = {"code": "API_ERROR", "message": f"API returned {response.status_code}"}
            raise ToolError(json.dumps(error, ensure_ascii=False))
        return response.json()

    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    write = ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False
    )
    safe_write = write.model_copy(update={"destructiveHint": False})

    @server.tool(annotations=read)
    async def editor_capabilities() -> dict[str, Any]:
        """List implemented commands, feature availability and render presets before planning."""
        return await call("GET", "/v1/capabilities")

    @server.tool(annotations=read)
    async def editor_contracts() -> dict[str, Any]:
        """Read authoritative project, command, import and render JSON schemas."""
        return await call("GET", "/v1/contracts")

    @server.tool(annotations=read)
    async def editor_info() -> dict[str, Any]:
        """Runtime facts: media/render readiness, media roots, output roots, data dir."""
        return await call("GET", "/v1/info")

    @server.tool(annotations=read)
    async def lut_parse(request: LutParse) -> dict[str, Any]:
        """Read `.cube` text with the engine's only LUT parser; returns a grade node payload to put
        in clip.color.grade. 1D tables only — a 3D LUT mixes channels and is refused by name."""
        return await call("POST", "/v1/lut/parse", request.model_dump(mode="json"))

    @server.tool(annotations=safe_write)
    async def project_create(request: CreateProject) -> MutationResult:
        """Create a durable project; request_id makes identical retries safe."""
        return MutationResult.model_validate(
            await call("POST", "/v1/projects", request.model_dump(mode="json"))
        )

    @server.tool(annotations=read)
    async def project_list(limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """List projects (limit 1..100, offset >=0)."""
        return await call("GET", f"/v1/projects?limit={limit}&offset={offset}")

    @server.tool(annotations=read)
    async def project_get(project_id: Identifier, revision: Revision | None = None) -> Project:
        """Read current project and revision, or an immutable historical snapshot."""
        query = "" if revision is None else f"?revision={revision}"
        return Project.model_validate(await call("GET", f"/v1/projects/{project_id}{query}"))

    @server.tool(annotations=read)
    async def project_history(
        project_id: Identifier, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        """Read revision audit metadata (limit 1..100, offset >=0)."""
        return await call("GET", f"/v1/projects/{project_id}/history?limit={limit}&offset={offset}")

    @server.tool(annotations=read)
    async def preview_manifest(
        project_id: Identifier,
        revision: Revision | None = None,
        sequence_id: Identifier | None = None,
    ) -> dict:
        """Read authoritative animation curves used by the native desktop compositor."""
        query = f"?sequence_id={sequence_id}" if sequence_id else "?"
        if revision is not None:
            query += f"&revision={revision}"
        return await call("GET", f"/v1/projects/{project_id}/preview-manifest{query}")

    @server.tool(annotations=read)
    async def animation_curve(clip: Clip, property: Property) -> dict[str, Any]:
        """Compile a clip value graph using the render clock, without persisting or reading media.

        Pass a clip from project_get or a timeline_edit dry-run result. Key times in the output
        are relative to the visible clip, including trimming offsets.
        """
        return await call(
            "POST", f"/v1/animation/curve?property={property}", clip.model_dump(mode="json")
        )

    @server.tool(annotations=read)
    async def animation_sample(clip: Clip, at_ticks: Ticks) -> dict[str, Any]:
        """Sample all six properties of a saved or dry-run clip without writes or media IO."""
        return await call(
            "POST", f"/v1/animation/sample?at_ticks={at_ticks}", clip.model_dump(mode="json")
        )

    @server.tool(annotations=read)
    async def preview_candidate(
        project: Project, sequence_id: Identifier | None = None
    ) -> dict[str, Any]:
        """Compile the native preview for a timeline_edit dry-run project, without writes."""
        query = f"?sequence_id={sequence_id}" if sequence_id else ""
        return await call("POST", "/v1/preview-manifest" + query, project.model_dump(mode="json"))

    @server.tool(annotations=read)
    async def captions_export(
        project_id: Identifier,
        track_id: Identifier,
        revision: Revision | None = None,
        sequence_id: Identifier | None = None,
    ) -> dict:
        """Export timed text clips from one track as plain SubRip subtitles."""
        query = f"?sequence_id={sequence_id}" if sequence_id else "?"
        if revision is not None:
            query += f"&revision={revision}"
        return await call("GET", f"/v1/projects/{project_id}/captions/{track_id}{query}")

    @server.tool(annotations=read)
    async def clip_sample(
        project_id: Identifier,
        clip_id: Identifier,
        at_ticks: Ticks,
        revision: Revision | None = None,
        sequence_id: Identifier | None = None,
    ) -> dict:
        """Sample animated properties at a clip-relative integer tick, using the render clock."""
        query = f"?at_ticks={at_ticks}" + ("" if revision is None else f"&revision={revision}")
        if sequence_id is not None:
            query += f"&sequence_id={sequence_id}"
        return await call("GET", f"/v1/projects/{project_id}/clips/{clip_id}/sample{query}")

    @server.tool(annotations=write)
    async def timeline_edit(project_id: Identifier, request: EditBatch) -> MutationResult:
        """Atomically edit a timeline; dry_run returns a prospective snapshot without saving."""
        return MutationResult.model_validate(
            await call("POST", f"/v1/projects/{project_id}/edits", request.model_dump(mode="json"))
        )

    @server.tool(annotations=read)
    async def clip_silence(
        project_id: Identifier, clip_id: Identifier, request: SilenceRequest
    ) -> dict[str, Any]:
        """Scan one clip's audio for pauses and get the ordinary cut commands that remove them.

        Read-only here: `apply` and `dry_run` are forced off, so nothing is written. Review or edit
        the returned `commands`, then submit them with `timeline_edit` to keep one atomic revision.
        """
        body = request.model_dump(mode="json") | {"apply": False, "dry_run": False}
        return await call(
            "POST",
            f"/v1/projects/{project_id}/clips/{clip_id}/silence",
            body,
            timeout=600,
        )

    @server.tool(annotations=read)
    async def captions_auto(
        project_id: Identifier, request: SpeechCaptionsRequest
    ) -> dict[str, Any]:
        """Transcribe speech into subtitle cues with the local model; plan only.

        Read-only here: `apply` and `dry_run` are forced off, so nothing is written. The answer
        carries the cues, their SubRip text and the one `captions.import` command — submit it with
        `timeline_edit` to land the whole subtitle track as a single undoable revision.
        """
        body = request.model_dump(mode="json") | {"apply": False, "dry_run": False}
        return await call(
            "POST",
            f"/v1/projects/{project_id}/speech-captions",
            body,
            timeout=600,
        )

    @server.tool(annotations=read)
    async def marker_split(project_id: Identifier, request: MarkerSplitRequest) -> dict[str, Any]:
        """Plan the split commands that cut every clip a timeline marker falls inside.

        Read-only here: `apply` and `dry_run` are forced off, so nothing is written. Review or edit
        the returned `commands`, then submit them with `timeline_edit` for one atomic revision.
        """
        return await call(
            "POST",
            f"/v1/projects/{project_id}/markers/split",
            request.model_dump(mode="json") | {"apply": False, "dry_run": False},
            timeout=120,
        )

    @server.tool(annotations=read)
    async def clip_reframe(
        project_id: Identifier, clip_id: Identifier, request: ReframeRequest
    ) -> dict[str, Any]:
        """Plan the pan-and-zoom that keeps a tracked subject centred.

        Read-only here: `apply` and `dry_run` are forced off. The answer says how many points it
        follows, how far it has to zoom, and whether the framing had to stop short; submit the
        returned `commands` with `timeline_edit` for one atomic revision.
        """
        return await call(
            "POST",
            f"/v1/projects/{project_id}/clips/{clip_id}/reframe",
            request.model_dump(mode="json") | {"apply": False, "dry_run": False},
            timeout=120,
        )

    @server.tool(annotations=read)
    async def clip_four_point(project_id: Identifier, request: FourPointRequest) -> dict[str, Any]:
        """Resolve two source points and two destination points into one placement command.

        Read-only here: `apply` and `dry_run` are forced off. The answer says whether the source was
        trimmed or re-timed and how many source ticks the placement will actually read; submit the
        returned `commands` with `timeline_edit` for one atomic revision.
        """
        return await call(
            "POST",
            f"/v1/projects/{project_id}/four-point",
            request.model_dump(mode="json") | {"apply": False, "dry_run": False},
            timeout=120,
        )

    @server.tool(annotations=write)
    async def track_duck(
        project_id: Identifier, track_id: Identifier, request: DuckRequest
    ) -> dict[str, Any]:
        """Pull one audio track back while the driver tracks are talking.

        The listening is the same silence detector the cut tools use; the write lands as `gain`
        keyframes through the same transaction as `timeline_edit`, so `dry_run` saves nothing, a
        repeated request_id replays, and `apply=false` only hands the commands back to review.
        """
        return await call(
            "POST",
            f"/v1/projects/{project_id}/tracks/{track_id}/duck",
            request.model_dump(mode="json"),
            timeout=600,
        )

    @server.tool(annotations=write)
    async def clip_stabilize(
        project_id: Identifier, clip_id: Identifier, request: ClipStabilizeRequest
    ) -> dict[str, Any]:
        """Take the camera's jitter off one clip by writing the inverse motion as keyframes.

        The analysis reads the server-verified media; the write goes through the same transaction as
        `timeline_edit`, so dry_run saves nothing and a repeated request_id replays. The reply's
        `stabilization` block says how far the picture actually moved and what is left over.

        The clip keeps a record of the run, so pressing again replaces that correction (another
        strength, one call) instead of stacking a second copy of the same measurement, and
        `strength 0` takes it off again. A clip whose `x`/`y`/`rotation`/`scale` curves were keyed
        by hand is refused as `STABILIZE_CONFLICT` — the engine cannot tell those from its own —
        and a stabilised clip refuses `clip.speed`/`clip.speed_curve` as `STABILIZE_LOCKED`,
        because the correction is one keyframe per source frame.
        """
        return await call(
            "POST",
            f"/v1/projects/{project_id}/clips/{clip_id}/stabilize",
            request.model_dump(mode="json"),
            timeout=900,
        )

    @server.tool(annotations=write)
    async def clip_track(
        project_id: Identifier, clip_id: Identifier, request: MaskTrackRequest
    ) -> dict[str, Any]:
        """Follow one box mask across the picture and write the path as mask keyframes.

        The analysis reads the server-verified media; the write goes through the same transaction as
        `timeline_edit`, so dry_run saves nothing and a repeated request_id replays.
        """
        return await call(
            "POST",
            f"/v1/projects/{project_id}/clips/{clip_id}/track",
            request.model_dump(mode="json"),
            timeout=900,
        )

    @server.tool(annotations=write)
    async def project_update(project_id: Identifier, request: ProjectUpdate) -> MutationResult:
        """Rename a project, edit its notes, or change sequence settings (new revision)."""
        return MutationResult.model_validate(
            await call("POST", f"/v1/projects/{project_id}", request.model_dump(mode="json"))
        )

    @server.tool(annotations=write)
    async def project_restore(project_id: Identifier, request: RestoreProject) -> MutationResult:
        """Restore a snapshot as a NEW revision; history is preserved."""
        return MutationResult.model_validate(
            await call(
                "POST", f"/v1/projects/{project_id}/restore", request.model_dump(mode="json")
            )
        )

    @server.tool(annotations=safe_write)
    async def ids_request(count: int = 32) -> dict[str, Any]:
        """Fetch server-issued unique ids to use for new tracks/assets/clips (1..200)."""
        return await call("POST", f"/v1/ids?count={count}")

    @server.tool(annotations=safe_write)
    async def media_import(request: ImportRequest) -> dict[str, Any]:
        """Probe a local file inside a media root; returns a trusted record plus probe_id.

        Use the probe_id in an asset.import command inside timeline_edit. Thumbnails,
        waveform and a preview stream URL come back with it. Nothing is copied or decoded
        beyond frame/waveform cache generation.
        """
        # Real media takes minutes to decode; the default 60s would abort a healthy import.
        return await call("POST", "/v1/media/import", request.model_dump(mode="json"), timeout=600)

    @server.tool(annotations=read)
    async def media_probe(probe_id: Identifier) -> dict[str, Any]:
        """Re-read a previously issued probe record."""
        return await call("GET", f"/v1/media/{probe_id}")

    @server.tool(annotations=read)
    async def media_config() -> dict[str, Any]:
        """Media roots, cache dir, allowed extensions and ffmpeg availability."""
        return await call("GET", "/v1/media/config")

    @server.tool(annotations=read)
    async def render_presets_read() -> dict[str, Any]:
        """Controlled output presets usable by render_start."""
        return await call("GET", "/v1/render-presets")

    @server.tool(annotations=read)
    async def render_plan(
        project_id: Identifier,
        preset_id: Identifier,
        revision: Revision | None = None,
        sequence_id: Identifier | None = None,
        fit: RenderFit = "contain",
    ) -> dict[str, Any]:
        """Dry-run: compile the RenderPlan (graph mode, segments, argv) without rendering."""
        query = f"?preset_id={preset_id}" + ("" if revision is None else f"&revision={revision}")
        if sequence_id is not None:
            query += f"&sequence_id={sequence_id}"
        if fit != "contain":
            query += f"&fit={fit}"
        return await call("GET", f"/v1/projects/{project_id}/render-plan{query}")

    @server.tool(annotations=safe_write)
    async def render_start(project_id: Identifier, request: RenderRequest) -> dict[str, Any]:
        """Queue a durable render of a fixed revision. Returns {job, plan}."""
        return await call(
            "POST", f"/v1/projects/{project_id}/renders", request.model_dump(mode="json")
        )

    @server.tool(annotations=safe_write)
    async def master_loudness(
        project_id: Identifier, request: MasterLoudnessRequest
    ) -> dict[str, Any]:
        """Measure the whole mix through a probe render and land it on a target.

        The probe uses the same audio graph the export uses, so the number is what the viewer hears
        (overlaps, fades, ducking and the current master gain included). `apply=true` writes one
        `project.update`, so it is one revision and undo returns the previous gain.
        """
        return await call(
            "POST",
            f"/v1/projects/{project_id}/master/loudness",
            request.model_dump(mode="json"),
            timeout=600,
        )

    @server.tool(annotations=safe_write)
    async def render_batch(project_id: Identifier, request: RenderBatch) -> dict[str, Any]:
        """Queue a whole delivery (up to four preset/framing combinations) in one call.

        Every item is compiled before anything is queued, so one bad item fails the batch instead of
        leaving half a delivery running. Returns {committed, jobs, plans}.
        """
        return await call(
            "POST", f"/v1/projects/{project_id}/renders/batch", request.model_dump(mode="json")
        )

    @server.tool(annotations=read)
    async def job_status(job_id: Identifier) -> dict[str, Any]:
        """Poll a render job: status, progress, message, output path."""
        return await call("GET", f"/v1/jobs/{job_id}")

    @server.tool(annotations=read)
    async def job_list(project_id: Identifier, limit: int = 20) -> dict[str, Any]:
        """Recent render jobs for a project."""
        return await call("GET", f"/v1/projects/{project_id}/jobs?limit={limit}")

    @server.tool(annotations=safe_write)
    async def job_cancel(job_id: Identifier) -> dict[str, Any]:
        """Cancel a queued or running render; partial files are never published."""
        return await call("POST", f"/v1/jobs/{job_id}/cancel")

    @server.tool(annotations=read)
    async def project_asset_urls(project_id: Identifier) -> dict[str, Any]:
        """Signed preview stream URLs so a reviewer can watch what the Agent cut."""
        return await call("GET", f"/v1/projects/{project_id}/asset-urls")

    @server.tool(annotations=safe_write)
    async def output_root_add(request: ImportRequest) -> dict[str, Any]:
        """Register a folder renders may write into (absolute path)."""
        return await call("POST", "/v1/outputs/roots", request.model_dump(mode="json"))

    @server.tool(annotations=read)
    async def output_roots_read() -> dict[str, Any]:
        """Folders the render engine is allowed to publish into."""
        return await call("GET", "/v1/outputs/roots")

    @server.resource("project://{project_id}")
    async def project_resource(project_id: str) -> str:
        # Resource templates also validate ids; they may not inject URL paths.
        from pydantic import TypeAdapter

        project_id = TypeAdapter(Identifier).validate_python(project_id)
        return json.dumps(await call("GET", f"/v1/projects/{project_id}"), ensure_ascii=False)

    @server.resource("renderjob://{job_id}")
    async def job_resource(job_id: str) -> str:
        from pydantic import TypeAdapter

        job_id = TypeAdapter(Identifier).validate_python(job_id)
        return json.dumps(await call("GET", f"/v1/jobs/{job_id}"), ensure_ascii=False)

    return server
