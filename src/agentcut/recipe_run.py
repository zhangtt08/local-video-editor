"""One Agent call that walks a whole delivery recipe inside the engine.

The recipes in `agent_contract.py` are the answer to "how do I cut a film here", and until now
they were only ever *read*: an Agent took the 13 steps and made 13 calls itself, chaining
`expected_revision` off each reply. That is a lot of doors to get through for one cut, and every
one of them is a place a caller can go wrong — so this module makes the engine walk its own recipe.

What it does NOT do is invent a second set of rules. Each step dispatches through the HTTP surface
the recipe names, in-process, with the same bearer token — the same door an outside Agent uses, the
same routes, the same reducer. A one-call run therefore cannot mean something different from the
step-by-step run: the step names in the reply ARE the endpoint table's tool names.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from .agent_contract import RECIPE_LIMITS, RECIPES, RUNNABLE_RECIPES
from .contracts import TIMEBASE, EditorError, RecipeRun

# door(method, path, payload) -> (status, body)。http_api 交回一个绑在自己 app 上的门。
Door = Callable[[str, str, "dict[str, Any] | None"], Awaitable[tuple[int, dict[str, Any]]]]

Handler = Callable[[Door, RecipeRun, dict[str, Any]], Awaitable[dict[str, Any]]]


def declared_steps(recipe_id: str) -> list[str]:
    """The recipe's own step order — the single owner this runner walks, never a copy."""
    for recipe in RECIPES:
        if recipe["id"] == recipe_id:
            return [str(step["tool"]) for step in recipe["steps"]]
    return []


def refusal(recipe_id: str) -> EditorError:
    """Unknown recipe by name; known-but-not-runnable by reason. Both say what to call instead."""
    known = sorted(recipe["id"] for recipe in RECIPES)
    if recipe_id not in known:
        return EditorError(
            "NOT_FOUND",
            f"没有配方 {recipe_id}，能一把跑完的是 {sorted(RUNNABLE_RECIPES)}",
            404,
            recipes=known,
            runnable=sorted(RUNNABLE_RECIPES),
        )
    return EditorError(
        "RECIPE_NOT_RUNNABLE",
        f"配方 {recipe_id} 一把跑不完：{RECIPE_LIMITS.get(recipe_id, '这一步要你点名')}",
        422,
        runnable=sorted(RUNNABLE_RECIPES),
        steps=declared_steps(recipe_id),
    )


async def ask(
    door: Door,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    tolerate: tuple[str, ...] = (),
) -> tuple[int, dict[str, Any]]:
    """Call one door and keep its own error envelope; `tolerate` lets a refusal be an answer.

    A route that says "nothing quiet enough to cut" did not break the run — it made the same
    judgement the step would have, so the caller gets the code back. Everything else is raised
    with the status the route used, so an Agent reads one error language here as on any other door.
    """
    status, body = await door(method, path, payload)
    if status < 400:
        return status, body
    error = body.get("error") if isinstance(body, dict) else None
    code = str((error or {}).get("code") or "AGENT_RUN_FAILED")
    if code in tolerate:
        return status, body
    raise EditorError(
        code,
        str((error or {}).get("message") or f"{method} {path} 回了 {status}"),
        status,
        called=f"{method} {path}",
        details=(error or {}).get("details"),
    )


def ran(method: str, path: str, **evidence: Any) -> dict[str, Any]:
    return {"ran": True, "called": f"{method} {path}", **evidence}


def skipped(why: str) -> dict[str, Any]:
    return {"ran": False, "why": why}


async def _capabilities(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    _status, body = await ask(door, "GET", "/v1/capabilities")
    features = body.get("features") or {}
    if not features.get("media_probe") or not features.get("render"):
        raise EditorError(
            "MEDIA_UNAVAILABLE",
            "这一刀要探测素材、看镜头切点并排交付，媒体引擎没就绪",
            503,
            media_probe=features.get("media_probe"),
            render=features.get("render"),
        )
    return ran("GET", "/v1/capabilities", app_version=body.get("app_version"))


async def _media_config(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    _status, body = await ask(door, "GET", "/v1/media/config")
    return ran(
        "GET",
        "/v1/media/config",
        roots=len(body.get("media_roots") or []),
        suffixes=len(body.get("allowed_suffixes") or []),
    )


async def _project_create(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    payload = {"request_id": f"{request.request_id}-create", "name": request.name}
    _status, body = await ask(door, "POST", "/v1/projects", payload)
    ctx["project_id"] = str(body["project"]["id"])
    ctx["revision"] = int(body["project"]["revision"])
    ctx["replayed"] = bool(body.get("replayed"))
    return ran(
        "POST",
        "/v1/projects",
        project_id=ctx["project_id"],
        replayed=ctx["replayed"],
    )


async def _ids_request(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    needed = 1 + 2 * len(request.files)
    path = f"/v1/ids?count={needed}"
    _status, body = await ask(door, "POST", path)
    ctx["ids"] = [str(item) for item in body["ids"]]
    return ran("POST", path, issued=len(ctx["ids"]))


async def _media_import(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    verified: list[dict[str, Any]] = []
    for path in request.files:
        _status, body = await ask(door, "POST", "/v1/media/import", {"path": path})
        verified.append(dict(body["verified"]))
    ctx["verified"] = verified
    ticks = sum(int(item["duration_ticks"]) for item in verified)
    return ran(
        "POST",
        "/v1/media/import",
        files=len(verified),
        seconds=round(ticks / TIMEBASE, 3),
        kinds=sorted({str(item["kind"]) for item in verified}),
    )


def seed_commands(request: RecipeRun, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """One picture track, one asset and one clip per file, laid end to end.

    The ids come from the `ids_request` step above, so nothing here invents a key the server
    might already be using. Audio follows the picture — a clip carries its own sound until
    `clip.detach_audio` says otherwise — which is why there is no second track to keep aligned.
    """
    track_id = ctx["ids"][0]
    ctx["track_id"] = track_id
    commands: list[dict[str, Any]] = [
        {"op": "track.add", "track": {"id": track_id, "kind": "video", "name": "画面"}}
    ]
    position = 0
    cursor = 1
    for item in ctx["verified"]:
        asset_id = ctx["ids"][cursor]
        clip_id = ctx["ids"][cursor + 1]
        cursor += 2
        commands.append(
            {
                "op": "asset.import",
                "asset_id": asset_id,
                "label": str(item["label"])[:256],
                "probe_id": item["probe_id"],
                "verified": item,
            }
        )
        commands.append(
            {
                "op": "clip.add",
                "clip": {
                    "id": clip_id,
                    "asset_id": asset_id,
                    "track_id": track_id,
                    "position_ticks": position,
                    "source_in_ticks": 0,
                    "duration_ticks": int(item["duration_ticks"]),
                },
            }
        )
        position += int(item["duration_ticks"])
    return commands


async def _timeline_edit(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    commands = seed_commands(request, ctx)
    path = f"/v1/projects/{ctx['project_id']}/edits?receipt=slim"
    payload = {
        "request_id": f"{request.request_id}-seed",
        "expected_revision": ctx["revision"],
        "commands": commands,
    }
    _status, body = await ask(door, "POST", path, payload)
    ctx["revision"] = int(body["revision"])
    return ran(
        "POST",
        "/v1/projects/{id}/edits",
        commands=len(commands),
        clips=len(ctx["verified"]),
        track_id=ctx["track_id"],
        revision=ctx["revision"],
    )


async def _track_cut(
    door: Door,
    request: RecipeRun,
    ctx: dict[str, Any],
    step: str,
    suffix: str,
    knobs: dict[str, Any],
    quiet: str,
) -> dict[str, Any]:
    """One whole-track analysis, applied as the engine's own batch.

    `apply: true` submits the plan through the same `/edits` door a caller would use, so the reducer
    stays the only thing that decides what a cut does. A refusal that means "nothing to cut" is
    recorded as the step's answer instead of failing the run.
    """
    path = f"/v1/projects/{ctx['project_id']}/tracks/{ctx['track_id']}/{step}"
    payload = {
        "request_id": f"{request.request_id}-{suffix}",
        "expected_revision": ctx["revision"],
        **knobs,
    }
    status, body = await ask(door, "POST", path, payload, tolerate=(quiet,))
    if status >= 400:
        return ran(
            "POST",
            path,
            changed=False,
            note=str((body.get("error") or {}).get("message")),
        )
    ctx["revision"] = int(body["project"]["revision"])
    plan = body.get("silence") or body.get("rough") or {}
    return ran(
        "POST",
        path,
        commands=len(plan.get("commands") or []),
        removed_ticks=int(plan.get("removed_ticks") or 0),
        clips=len(plan.get("clips") or []),
        revision=ctx["revision"],
    )


async def _track_silence(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    knobs = {
        "threshold_db": request.threshold_db,
        "min_silence_ms": request.min_silence_ms,
        "apply": True,
    }
    return await _track_cut(
        door, request, ctx, "silence", "silence", knobs, "INVALID_SILENCE_TARGET"
    )


async def _track_rough_cut(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    knobs = {
        "keep_ms": request.keep_ms,
        "threshold": request.scene_threshold,
        "min_scene_ms": request.min_scene_ms,
        "apply": True,
    }
    return await _track_cut(door, request, ctx, "rough-cut", "rough", knobs, "ROUGH_NONE")


async def _overview(_door: Door, _request: RecipeRun, _ctx: dict[str, Any]) -> dict[str, Any]:
    return skipped(
        "接触表是一张 PNG，这一刀不替你看图；要眼睛就单独叫 timeline_overview"
    )


async def _preview(_door: Door, _request: RecipeRun, _ctx: dict[str, Any]) -> dict[str, Any]:
    return skipped("抽帧也是 PNG：想要某一秒长什么样，用 preview_frame 带上 t 单独调")


async def _render_plan(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    if not request.render:
        return skipped("render=false：这一刀只到粗剪，交付由你自己排 render_start")
    path = (
        f"/v1/projects/{ctx['project_id']}/render-plan"
        f"?preset_id={request.preset_id}&revision={ctx['revision']}"
    )
    _status, body = await ask(door, "GET", path)
    ctx["plan"] = body
    inner = body.get("plan") if isinstance(body.get("plan"), dict) else body
    return ran(
        "GET",
        "/v1/projects/{id}/render-plan",
        seconds=inner.get("duration_seconds"),
        inputs=inner.get("inputs"),
        filter_nodes=inner.get("filter_nodes"),
        resolution=inner.get("resolution"),
        argv=len(body.get("argv_preview") or []),
    )


async def _render_start(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    if not request.render:
        return skipped("render=false：没有排交付")
    payload = {
        "request_id": f"{request.request_id}-render",
        "expected_revision": ctx["revision"],
        "preset_id": request.preset_id,
        "filename": request.filename,
    }
    _status, body = await ask(door, "POST", f"/v1/projects/{ctx['project_id']}/renders", payload)
    ctx["job"] = dict(body["job"])
    return ran("POST", "/v1/projects/{id}/renders", job_id=ctx["job"]["id"],
               status=ctx["job"]["status"])


async def _job_wait(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    if not request.render:
        return skipped("render=false：没有作业可等")
    if request.wait_seconds <= 0:
        return skipped("wait_seconds=0：交付已排队，要在这刀里等到终态就把它设到 1..120")
    poll = min(0.5, max(0.05, request.wait_seconds / 20))
    path = f"/v1/jobs/{ctx['job']['id']}/wait?timeout={request.wait_seconds}&poll={poll}"
    _status, body = await ask(door, "GET", path)
    ctx["job"] = dict(body["job"])
    ctx["waited_ms"] = body.get("waited_ms")
    ctx["timed_out"] = body.get("timed_out")
    return ran(
        "GET",
        "/v1/jobs/{id}/wait",
        status=ctx["job"]["status"],
        waited_ms=ctx["waited_ms"],
        timed_out=ctx["timed_out"],
        output_checked=ctx["job"].get("output_checked"),
    )


RUNNERS: dict[str, Handler] = {
    "editor_capabilities": _capabilities,
    "media_config": _media_config,
    "media_import": _media_import,
    "project_create": _project_create,
    "ids_request": _ids_request,
    "timeline_edit": _timeline_edit,
    "track_silence": _track_silence,
    "track_rough_cut": _track_rough_cut,
    "timeline_overview": _overview,
    "preview_frame": _preview,
    "render_plan": _render_plan,
    "render_start": _render_start,
    "job_wait": _job_wait,
}

# 同一个 request_id 再叫一次：建工程那一步会交回它当时的凭据，后面这些写步就不能再写一遍。
WRITE_STEPS = frozenset(
    {
        "ids_request",
        "timeline_edit",
        "track_silence",
        "track_rough_cut",
        "render_plan",
        "render_start",
        "job_wait",
    }
)
REPLAY_NOTE = "这一刀已经跑过（同一个 request_id），交回它当时的工程与交付，不重写一遍"


async def read_back(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> None:
    """Read what the earlier run left behind: the live revision and the delivery it queued."""
    project_id = ctx["project_id"]
    _status, project = await ask(door, "GET", f"/v1/projects/{project_id}")
    ctx["revision"] = int(project["revision"])
    _status, listed = await ask(door, "GET", f"/v1/projects/{project_id}/jobs?limit=20")
    jobs = list(listed.get("jobs") or [])
    wanted = next((job for job in jobs if job.get("filename") == request.filename), None)
    if wanted is None and jobs:
        wanted = jobs[0]
    if wanted is not None:
        ctx["job"] = dict(wanted)
        ctx["waited_ms"] = 0
        ctx["timed_out"] = str(wanted.get("status")) not in {"queued", "running"}


async def run(door: Door, recipe_id: str, request: RecipeRun) -> dict[str, Any]:
    """Walk the recipe, one declared step at a time, and answer with the step log."""
    if recipe_id not in RUNNABLE_RECIPES:
        raise refusal(recipe_id)
    ctx: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for tool in declared_steps(recipe_id):
        handler = RUNNERS.get(tool)
        if handler is None:
            raise EditorError(
                "RECIPE_STEP_UNIMPLEMENTED",
                f"配方写了 {tool}，这一版没有对应的执行步",
                500,
                steps=declared_steps(recipe_id),
            )
        if ctx.get("replayed") and tool in WRITE_STEPS:
            rows.append({"step": tool, **skipped(REPLAY_NOTE)})
            continue
        rows.append({"step": tool, **(await handler(door, request, ctx))})
    if ctx.get("replayed"):
        await read_back(door, request, ctx)
    job = ctx.get("job") or {}
    return {
        "recipe": recipe_id,
        "request_id": request.request_id,
        "replayed": bool(ctx.get("replayed")),
        "project_id": ctx.get("project_id"),
        "revision": ctx.get("revision"),
        "clips": len(ctx.get("verified") or []),
        "steps": rows,
        "job": ctx.get("job"),
        "output_path": job.get("output_path"),
        "waited_ms": ctx.get("waited_ms"),
        "timed_out": ctx.get("timed_out"),
        "plan": ctx.get("plan"),
    }
