"""Official MCP stdio adapter; the HTTP service remains the sole project writer.

Every tool here is a thin, typed pass-through: no editing, media or scheduling rule is
re-implemented on this side, so an Agent and the desktop UI cannot diverge.
"""

import base64
import hashlib
import json
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .contracts import (
    AutoGradeRequest,
    CachePrune,
    Clip,
    ClipStabilizeRequest,
    CreateProject,
    DuckRequest,
    EditBatch,
    FadeAdoptTrackRequest,
    FourPointRequest,
    GradeApplyTrackRequest,
    Identifier,
    ImportRequest,
    LoudnessRequest,
    LutParse,
    MarkerSplitRequest,
    MaskTrackRequest,
    MasterLoudnessRequest,
    MutationResult,
    Project,
    ProjectUpdate,
    Property,
    ProxyPrune,
    ReframeRequest,
    RenderBatch,
    RenderFit,
    RenderRange,
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

    async def raw(
        method: str, path: str, payload: dict | None = None, timeout: float = 60
    ) -> httpx.Response:
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
        return response

    async def call(
        method: str, path: str, payload: dict | None = None, timeout: float = 60
    ) -> dict:
        return (await raw(method, path, payload, timeout)).json()

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
        in clip.color.grade. The file's header decides the kind: `lut` is a per-channel 1D table
        that both ends draw, `lut3d` is a cross-channel cube the exporter applies and the browser
        cannot, so a clip using one previews unchanged."""
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
    async def preview_frame(
        project_id: Identifier,
        at_ticks: Ticks,
        revision: Revision | None = None,
        sequence_id: Identifier | None = None,
    ) -> dict[str, Any]:
        """Look at the composited picture at one integer tick -- the frame the export will contain.

        These bytes come from the same renderer the exporter drives, so this is not a browser
        approximation: a grade, a mask, a keyframe or a transition that is missing here is missing
        from the delivered file. `at_ticks` is on the timeline being read -- pass `sequence_id` for
        a nested composition -- and is clamped down to the frame grid, which the answer reports
        back as `at_ticks`. The PNG is downscaled for transport (long edge 256 px, aspect ratio
        kept); `sha256` covers exactly those bytes, so a client that cannot see images can still
        prove a change moved the picture.
        """
        query = f"?at_ticks={at_ticks}" + ("" if revision is None else f"&revision={revision}")
        if sequence_id is not None:
            query += f"&sequence_id={sequence_id}"
        response = await raw("GET", f"/v1/projects/{project_id}/frame{query}", timeout=600)
        body = response.content
        if body[:8] != b"\x89PNG\r\n\x1a\n":
            raise ToolError(
                json.dumps(
                    {
                        "code": "MEDIA_FAILED",
                        "message": "the media engine returned something that is not a PNG frame",
                    },
                    ensure_ascii=False,
                )
            )
        return {
            "png_base64": base64.b64encode(body).decode(),
            "at_ticks": int(response.headers["x-frame-ticks"]),
            "revision": int(response.headers["x-project-revision"]),
            "width": int.from_bytes(body[16:20], "big"),
            "height": int.from_bytes(body[20:24], "big"),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }

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
        """Atomically edit a timeline; dry_run returns a prospective snapshot without saving.

        `sequence_id` makes the clip and track ids of this batch mean the clips inside one nested
        composition, which is how a plan from `clip_silence`/`clip_reframe` is applied back.
        """
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
        `sequence_id` reads the clip from inside that nested composition; the commands then have to
        be submitted with the same `sequence_id`.
        """
        body = request.model_dump(mode="json") | {"apply": False, "dry_run": False}
        return await call(
            "POST",
            f"/v1/projects/{project_id}/clips/{clip_id}/silence",
            body,
            timeout=600,
        )

    @server.tool(annotations=read)
    async def clip_loudness(
        project_id: Identifier, clip_id: Identifier, request: LoudnessRequest
    ) -> dict[str, Any]:
        """Measure one clip's loudness and get the ordinary `clip.effects` command that fixes it.

        Read-only here: `apply` and `dry_run` are forced off, so nothing is written. The answer
        carries the measured LUFS, the true peak, the suggested gain and whether the gain can reach
        the target without clipping. Submit the returned command with `timeline_edit` to land it.
        `sequence_id` measures the clip inside that nested composition, and the command then has to
        be submitted with the same `sequence_id`.
        """
        body = request.model_dump(mode="json") | {"apply": False, "dry_run": False}
        return await call(
            "POST",
            f"/v1/projects/{project_id}/clips/{clip_id}/loudness",
            body,
            timeout=600,
        )

    @server.tool(annotations=read)
    async def track_loudness(
        project_id: Identifier, track_id: Identifier, request: LoudnessRequest
    ) -> dict[str, Any]:
        """Measure every clip on one track and get the commands that align them to a target.

        Read-only here: `apply` and `dry_run` are forced off. Each clip is measured over its own
        source window, the same window the exporter reads it from; fades and overlaps in the mix are
        only accounted for by `master_loudness`, which probes the real audio graph. `changed` says
        how many clips actually move and `off_target` how many cannot reach the target under the
        ceiling. With `sequence_id` the track is the one inside that nested composition — the root's
        same-named track is not read.
        """
        body = request.model_dump(mode="json") | {"apply": False, "dry_run": False}
        return await call(
            "POST",
            f"/v1/projects/{project_id}/tracks/{track_id}/loudness",
            body,
            timeout=600,
        )

    @server.tool(annotations=read)
    async def track_silence(
        project_id: Identifier, track_id: Identifier, request: SilenceRequest
    ) -> dict[str, Any]:
        """Scan every clip on one track for pauses and get the cut commands that remove them.

        Read-only here: `apply` and `dry_run` are forced off, so nothing is written. Clips that
        cannot carry audio are skipped with the reason instead of failing the whole track. With
        `sequence_id` the track is read inside that nested composition; the commands then have to be
        submitted with the same `sequence_id`, or they will name clips the root does not have.
        """
        body = request.model_dump(mode="json") | {"apply": False, "dry_run": False}
        return await call(
            "POST",
            f"/v1/projects/{project_id}/tracks/{track_id}/silence",
            body,
            timeout=600,
        )

    @server.tool(annotations=read)
    async def track_grade_apply(
        project_id: Identifier, track_id: Identifier, request: GradeApplyTrackRequest
    ) -> dict[str, Any]:
        """Plan copying one clip's grade chain onto every other clip of one track.

        Read-only here: `apply` and `dry_run` are forced off, so nothing is written. Each entry is
        either a clip that will take the chain (`nodes` / `added_samples`) or a refusal naming why
        (the per-chain node cap, an audio clip, or the project's inline lookup-table budget from
        1.104). Submit the returned `clip.grade` commands with `timeline_edit` to land the whole
        track in one revision, or call the same endpoint with `apply=true`.
        """
        body = request.model_dump(mode="json") | {"apply": False, "dry_run": False}
        return await call(
            "POST",
            f"/v1/projects/{project_id}/tracks/{track_id}/grade-apply",
            body,
        )

    @server.tool(annotations=read)
    async def grade_capacity(project_id: Identifier) -> dict[str, Any]:
        """Report this project's inline lookup-table usage: samples used, the limit, what is left,
        and which clips hold the biggest tables.

        Read-only. These are exactly the numbers `clip.grade` refuses against, so a plan that puts
        a LUT on a whole track can check `room` first instead of discovering the ceiling by being
        refused with GRADE_INLINE_BUDGET.
        """
        return await call("GET", f"/v1/projects/{project_id}/grade-capacity")

    @server.tool(annotations=read)
    async def track_fade_adoption(
        project_id: Identifier, track_id: Identifier, request: FadeAdoptTrackRequest
    ) -> dict[str, Any]:
        """List the pre-1.90 keyframe fades on one track that can become edge windows.

        Read-only here: `apply` and `dry_run` are forced off, so nothing is written. Each entry is
        either an adoptable fade (`in_ticks` / `out_ticks` / `shape` as they will be stored) or a
        refusal with the reason and the keyframes actually found on that property. Submit the
        returned `clip.fade_adopt` commands with `timeline_edit` to land the whole track in one
        revision. With `sequence_id` the track is read inside that nested composition, and the
        commands then have to be submitted with the same `sequence_id`.
        """
        body = request.model_dump(mode="json") | {"apply": False, "dry_run": False}
        return await call(
            "POST",
            f"/v1/projects/{project_id}/tracks/{track_id}/fade-adopt",
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
        `timeline_edit` to land the whole subtitle track as a single undoable revision. With
        `sequence_id` the clip is read from that nested composition and the track lands inside it.
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
        returned `commands` with `timeline_edit` for one atomic revision. `sequence_id` reads the
        mask path from a clip inside that nested composition.
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
        `sequence_id` ducks one track of a nested composition, listening to the driver tracks that
        sit beside it in the same composition.
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
        and a stabilised clip refuses `clip.speed`/`clip.speed_curve` and `clip.reframe` as
        `STABILIZE_LOCKED`: the correction is one keyframe per frame the clip plays and lives in
        `x`/`y`/`scale` curves the follow writes, so a speed change would play it at the wrong rate
        and a reframe would delete it while the record still claimed it. `sequence_id` measures and
        writes a clip that lives inside a nested composition. A clip at a constant speed is
        measured on the frames it actually plays — `stabilization.sample_rate` names the stride
        (15/1 for a 200 % clip of a 30 fps source); a speed curve is still refused, because no
        single stride describes it.
        """
        return await call(
            "POST",
            f"/v1/projects/{project_id}/clips/{clip_id}/stabilize",
            request.model_dump(mode="json"),
            timeout=900,
        )

    @server.tool(annotations=write)
    async def clip_auto_grade(
        project_id: Identifier, clip_id: Identifier, request: AutoGradeRequest
    ) -> dict[str, Any]:
        """Stretch one clip's own picture to full range by writing a levels node.

        The measurement decodes the clip's source window with the media engine and takes percentile
        black/white points, so it reports what is really in the frames rather than a preset look.
        The write is an ordinary `clip.grade` in the same transaction as `timeline_edit`: `dry_run`
        saves nothing, a repeated request_id replays, and one apply is one revision.

        `mode` is `luma` (one node, cannot invent a colour cast) or `rgb` (three per-channel nodes,
        removes a cast and costs three of the eight node slots). `percentile` is how much of the
        picture may be clipped at each end. A picture that already spans the measured range gets its
        numbers back and writes nothing. Pressing again replaces the previous auto correction unless
        doing so would overwrite a levels node nobody measured, which is refused as
        `AUTO_GRADE_CONFLICT` naming the position. `sequence_id` measures and writes a clip that
        lives inside a nested composition.
        """
        return await call(
            "POST",
            f"/v1/projects/{project_id}/clips/{clip_id}/auto-grade",
            request.model_dump(mode="json"),
            timeout=900,
        )

    @server.tool(annotations=write)
    async def clip_track(
        project_id: Identifier, clip_id: Identifier, request: MaskTrackRequest
    ) -> dict[str, Any]:
        """Follow one box mask across the picture and write the path as mask keyframes.

        The analysis reads the server-verified media; the write goes through the same transaction as
        `timeline_edit`, so dry_run saves nothing and a repeated request_id replays. `merge` (on by
        default) keeps the points outside the analysed window, so a run that loses the subject can
        be continued from a later frame instead of starting over and wiping the first half.
        `sequence_id` follows a mask on a clip inside a nested composition. While the subject is
        hidden `reacquire` searches the whole picture once more per frame, so a target that comes
        back somewhere else — or after a long occlusion — is found again instead of reported lost;
        the reply lists the ticks it was re-found at and how far the guesses had to be shifted.
        A clip's curve list is the second ceiling: one sized sighting costs four curves, so the run
        is shortened to whatever the clip can still hold and the reply says so with `budget_frames`.
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
    async def media_cache_read() -> dict[str, Any]:
        """What the derived cache holds right now: entries, bytes, and the budget it is kept under.

        Filmstrip tiles, waveform peaks and playback proxies are derived data — nothing here is a
        person's edit, and anything missing is rebuilt on demand.
        """
        return await call("GET", "/v1/media/cache")

    @server.tool(annotations=write)
    async def media_cache_prune(request: CachePrune) -> dict[str, Any]:
        """Bound the whole derived cache, dropping whole entries least-recently-used first.

        `dry_run` returns the same plan without deleting anything, and `keep` protects the hashes
        still being looked at. This is disk housekeeping: it cannot change a project or a revision.
        """
        return await call("POST", "/v1/media/cache/prune", request.model_dump(mode="json"))

    @server.tool(annotations=write)
    async def media_proxies_prune(request: ProxyPrune) -> dict[str, Any]:
        """Drop playback proxies down to a byte budget, keeping the originals untouched."""
        return await call("POST", "/v1/media/proxies/prune", request.model_dump(mode="json"))

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
        range: RenderRange = "full",
        transparent: bool = False,
        timecode: str | None = None,
        output_fps: str | None = None,
    ) -> dict[str, Any]:
        """Dry-run: compile the RenderPlan (graph mode, segments, argv) without rendering."""
        query = f"?preset_id={preset_id}" + ("" if revision is None else f"&revision={revision}")
        if sequence_id is not None:
            query += f"&sequence_id={sequence_id}"
        if fit != "contain":
            query += f"&fit={fit}"
        # 干跑要问的就是真导出会用的那组词：入出点和透明背景在这里缺一个，就会出现
        # 「计划看着是绿的，落地文件不是那个东西」。
        if range != "full":
            query += f"&range={range}"
        if transparent:
            query += "&transparent=true"
        if timecode:
            # 分号在 query 里是有歧义的字符，必须百分号编码，否则 API 收到的不是那串时间码。
            query += f"&timecode={quote(timecode, safe='')}"
        if output_fps:
            query += f"&output_fps={quote(output_fps, safe='')}"
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
