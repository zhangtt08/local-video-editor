"""One Agent call that walks a whole delivery recipe inside the engine.

The recipes in `agent_contract.py` are the answer to "how do I cut a film here", and for two
releases they were only ever *read*: an Agent took the steps and made one HTTP call per step
itself, chaining `expected_revision` off each reply. That is a lot of doors for one cut, and every
one of them is a place a caller can go wrong — so this module walks the recipe instead.

What it does NOT do is invent a second set of rules. Each step dispatches through the HTTP surface
the recipe names, in-process, with the same bearer token — the same door an outside Agent uses,
the same routes, the same reducer. A one-call run therefore cannot mean something different from
the step-by-step run: the step names in the reply ARE the endpoint table's tool names, and the
`steps` list is read from the recipe, never copied into here.

Three recipes run through this one door since 1.312: `cut-from-media`, `speech-to-captions`
(what the caller decides is handed over as data — which phrases to drop, how long a pause counts)
and `imitate-imported-edit` (someone else's project document, recognised by the engine itself).
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from .agent_contract import RECIPES, RUNNABLE_RECIPES
from .contracts import TIMEBASE, EditorError, RecipeRun

# door(method, path, payload) -> (status, body)。http_api 交回一个绑在自己 app 上的门。
Door = Callable[[str, str, "dict[str, Any] | None"], Awaitable[tuple[int, dict[str, Any]]]]

Handler = Callable[[Door, RecipeRun, dict[str, Any]], Awaitable[dict[str, Any]]]

# 每一种交换格式对轨道不够的说法都同一族：「先加轨道，再来读」。这一刀把那一句当指令，
# 不当失败——加几条由引擎自己数出来（`details.wanted`），门禁钉着这个名字族还在。
TRACK_COUNT_REFUSALS = tuple(
    f"{name}_TRACK_COUNT" for name in ("OTIO", "FCPXML", "XMEML", "EDL", "JIANYING")
)

# 每条配方非有不可的参数：缺哪一样就点名拒掉，不许半路才撞在某个路由上。
# render=false 的刀不排交付，所以交付那一档的参数也就不再必需。
def required_fields(recipe_id: str, request: RecipeRun) -> tuple[str, ...]:
    if recipe_id == "imitate-imported-edit":
        base: tuple[str, ...] = ("interchange_document", "files")
        delivery: tuple[str, ...] = ("deliver_items",)
    else:
        base = ("files",)
        delivery = ("preset_id", "filename")
    return base + (delivery if request.render else ())


def declared_steps(recipe_id: str) -> list[str]:
    """The recipe's own step order — the single owner this runner walks, never a copy."""
    for recipe in RECIPES:
        if recipe["id"] == recipe_id:
            return [str(step["tool"]) for step in recipe["steps"]]
    return []


def refusal(recipe_id: str) -> EditorError:
    """Unknown recipe by name. Every known one is runnable since 1.312."""
    known = sorted(recipe["id"] for recipe in RECIPES)
    return EditorError(
        "NOT_FOUND",
        f"没有配方 {recipe_id}，能一把跑完的是 {sorted(RUNNABLE_RECIPES)}",
        404,
        recipes=known,
        runnable=sorted(RUNNABLE_RECIPES),
    )


def missing_params(recipe_id: str, request: RecipeRun) -> list[str]:
    """The parameters this recipe cannot do without, named as the model names them."""
    return [name for name in required_fields(recipe_id, request) if not getattr(request, name)]


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


def size_of(body: dict[str, Any]) -> int:
    return len(json.dumps(body, ensure_ascii=False))


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
    ctx["speech_ready"] = bool(features.get("speech_captions"))
    return ran("GET", "/v1/capabilities", app_version=body.get("app_version"),
               speech=features.get("speech_captions"))


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
    return ran("POST", "/v1/projects", project_id=ctx["project_id"], replayed=ctx["replayed"])


async def _ids_request(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    needed = 2 + 3 * len(request.files or [])
    path = f"/v1/ids?count={needed}"
    _status, body = await ask(door, "POST", path)
    ctx["ids"] = [str(item) for item in body["ids"]]
    ctx["cursor"] = 0
    return ran("POST", path, issued=len(ctx["ids"]))


def take_ids(ctx: dict[str, Any], want: int) -> list[str]:
    """Hand out the server-issued ids in order, so two steps never share one."""
    ids = ctx.get("ids") or []
    cursor = int(ctx.get("cursor") or 0)
    picked = ids[cursor:cursor + want]
    ctx["cursor"] = cursor + len(picked)
    return picked


async def _media_import(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    verified: list[dict[str, Any]] = []
    for path in request.files or []:
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


def seed_commands(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Lay the files end to end, each on the track whose kind it is.

    The ids come from the `ids_request` step above, so nothing here invents a key the server might
    already be using. A picture (or an image) goes on 画面 and keeps its own sound until
    `clip.detach_audio` says otherwise; a bare audio file goes on 声音, because that is what the
    reducer's own validation asks for. `captions_auto` reads the voice track through
    `audio_track_id`, which is the audio one when there is one.
    """
    picture_id, voice_id = take_ids(ctx, 2)
    kinds = {str(item["kind"]) for item in ctx["verified"]}
    has_picture = bool(kinds & {"video", "image"})
    has_voice = "audio" in kinds
    commands: list[dict[str, Any]] = []
    if has_picture:
        commands.append({"op": "track.add", "track": {"id": picture_id, "kind": "video",
                                                      "name": "画面"}})
        ctx["track_id"] = picture_id
    if has_voice:
        commands.append({"op": "track.add", "track": {"id": voice_id, "kind": "audio",
                                                      "name": "声音"}})
        ctx.setdefault("audio_track_id", voice_id)
    ctx.setdefault("track_id", picture_id if has_picture else voice_id)
    ctx.setdefault("audio_track_id", voice_id if has_voice else None)
    placed: dict[str, int] = {picture_id: 0, voice_id: 0}
    for item in ctx["verified"]:
        asset_id, clip_id = take_ids(ctx, 2)
        track_id = voice_id if str(item["kind"]) == "audio" else picture_id
        commands.append(asset_command(item, asset_id))
        commands.append(
            {
                "op": "clip.add",
                "clip": {
                    "id": clip_id,
                    "asset_id": asset_id,
                    "track_id": track_id,
                    "position_ticks": placed[track_id],
                    "source_in_ticks": 0,
                    "duration_ticks": int(item["duration_ticks"]),
                },
            }
        )
        placed[track_id] += int(item["duration_ticks"])
        ctx.setdefault("clip_ids", []).append(clip_id)
    return commands


def asset_command(item: dict[str, Any], asset_id: str) -> dict[str, Any]:
    """One verified file, written the same way for our own clip and for a borrowed cut."""
    return {
        "op": "asset.import",
        "asset_id": asset_id,
        "label": str(item["label"])[:256],
        "probe_id": item["probe_id"],
        "verified": item,
    }


def asset_commands(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Register the media a borrowed document names, before reading that document.

    The interchange readers refuse to guess: media is matched by name against assets this engine
    already verified, so registering them first is what makes the plan's `clip.add` commands point
    at real assets in THIS project instead of at ids that came from somewhere else.
    """
    return [asset_command(item, take_ids(ctx, 1)[0]) for item in ctx.get("verified") or []]


async def _timeline_edit(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    """Write this cut's own batch: the seeded timeline, or the plan a borrowed document made.

    The borrowed case is two batches when the reader asked for tracks first: the `track.add`
    commands it counted, then the commands it produced once those tracks exist. Both go through
    the same `/edits` door, each as its own revision, and the row says both happened.
    """
    path = f"/v1/projects/{ctx['project_id']}/edits?receipt=slim"
    evidence: dict[str, Any] = {}
    if request.interchange_document and not ctx.get("assets_written"):
        commands = asset_commands(ctx)
        ctx["assets_written"] = True
        suffix = "assets"
    elif ctx.get("imported_commands") is not None:
        commands = list(ctx["imported_commands"])
        suffix = "import"
    elif request.interchange_document:
        commands, evidence = await borrow_plan(door, request, ctx)
        suffix = "import"
    else:
        commands = seed_commands(ctx)
        suffix = "seed"
    payload = {
        "request_id": f"{request.request_id}-{suffix}",
        "expected_revision": ctx["revision"],
        "commands": commands,
    }
    _status, body = await ask(door, "POST", path, payload)
    ctx["revision"] = int(body["revision"])
    return ran(
        "POST",
        "/v1/projects/{id}/edits",
        commands=len(commands),
        source=suffix,
        clips=len(ctx.get("verified") or []) or None,
        track_id=ctx.get("track_id"),
        revision=ctx["revision"],
        **evidence,
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

    `apply: true` submits the plan through the same `/edits` door a caller would use, so the
    reducer stays the only thing that decides what a cut does. A refusal that means "nothing to
    cut" is recorded as the step's answer instead of failing the run.
    """
    path = f"/v1/projects/{ctx['project_id']}/tracks/{ctx['track_id']}/{step}"
    payload = {
        "request_id": f"{request.request_id}-{suffix}",
        "expected_revision": ctx["revision"],
        **knobs,
    }
    status, body = await ask(door, "POST", path, payload, tolerate=(quiet,))
    if status >= 400:
        return ran("POST", path, changed=False, note=str((body.get("error") or {}).get("message")))
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


async def _captions_auto(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    """Listen to the seeded voice and land the cues as the engine's own single batch."""
    if not ctx.get("speech_ready"):
        return skipped("这台引擎没有本地语音模型：字幕那一步做不了，换一条配方或装好模型")
    path = f"/v1/projects/{ctx['project_id']}/speech-captions"
    source_track = ctx.get("audio_track_id") or ctx["track_id"]
    payload = {
        "request_id": f"{request.request_id}-captions",
        "expected_revision": ctx["revision"],
        "track_id": source_track,
        "apply": True,
    }
    if request.language:
        payload["language"] = request.language
    if request.caption_max_chars:
        payload["max_chars"] = request.caption_max_chars
    _status, body = await ask(door, "POST", path, payload)
    speech = body.get("speech") or {}
    ctx["caption_track_id"] = str((speech.get("command") or {}).get("track_id"))
    ctx["revision"] = int(body["project"]["revision"])
    return ran(
        "POST",
        path,
        cues=len(speech.get("cues") or []),
        model=speech.get("model"),
        language=speech.get("language"),
        caption_track_id=ctx["caption_track_id"],
        revision=ctx["revision"],
    )


async def _transcript_view(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    _status, body = await ask(door, "GET", f"/v1/projects/{ctx['project_id']}/transcript")
    ctx["transcript"] = body
    return ran(
        "GET",
        "/v1/projects/{id}/transcript",
        phrases=int(body.get("phrase_count") or 0),
        silences=int(body.get("silence_count") or 0),
        speech_ms=round(int(body.get("speech_ticks") or 0) * 1000 / TIMEBASE, 1),
    )


def chosen_spans(ctx: dict[str, Any], request: RecipeRun) -> list[dict[str, int]]:
    """Turn the caller's data into timeline ranges, reading only the engine's own view.

    Which lines deserve cutting stays a human's or the calling agent's judgement — so it arrives
    here as data: text patterns to drop and how long a pause has to be before it counts. The
    ranges themselves come from the phrase view the `timeline_transcript` step just read back,
    which is the same statement the person's subtitle track shows.
    """
    view = ctx.get("transcript") or {}
    spans: list[dict[str, int]] = []
    patterns = [str(item).lower() for item in request.filler_patterns]
    for phrase in view.get("phrases") or []:
        text = str(phrase.get("text") or "").lower()
        if any(pattern and pattern in text for pattern in patterns):
            spans.append(
                {"from_ticks": int(phrase["from_ticks"]), "to_ticks": int(phrase["to_ticks"])}
            )
    if request.cut_gap_ms:
        floor = request.cut_gap_ms * TIMEBASE // 1000
        for hole in view.get("silences") or []:
            if int(hole["to_ticks"]) - int(hole["from_ticks"]) >= floor:
                spans.append(
                    {"from_ticks": int(hole["from_ticks"]), "to_ticks": int(hole["to_ticks"])}
                )
    return sorted(spans, key=lambda item: item["from_ticks"])


async def _transcript_cut(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    spans = chosen_spans(ctx, request)
    if not spans:
        return skipped("没选出要剪的段：给 filler_patterns 或 cut_gap_ms，这一刀不替你想删哪句")
    path = f"/v1/projects/{ctx['project_id']}/transcript/cut"
    payload = {
        "request_id": f"{request.request_id}-transcript-cut",
        "expected_revision": ctx["revision"],
        "spans": spans,
        "apply": True,
    }
    status, body = await ask(
        door, "POST", path, payload, tolerate=("TRANSCRIPT_NOTHING_TO_CUT",)
    )
    if status >= 400:
        return ran("POST", path, changed=False, spans=len(spans),
                   note=str((body.get("error") or {}).get("message")))
    ctx["revision"] = int(body["project"]["revision"])
    return ran(
        "POST",
        path,
        spans=len(spans),
        commands=len(body.get("commands") or []),
        revision=ctx["revision"],
    )


async def _captions_export(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    track_id = ctx.get("caption_track_id")
    if not track_id:
        return skipped("字幕轨不存在：这一刀没落字幕，没有可交的文字")
    path = f"/v1/projects/{ctx['project_id']}/captions/{track_id}"
    _status, body = await ask(door, "GET", path)
    srt = str(body.get("srt") or "")
    evidence: dict[str, Any] = {"srt_chars": len(srt), "track_id": track_id}
    if request.include_text:
        evidence["srt"] = srt
    return ran("GET", "/v1/projects/{id}/captions/{track_id}", **evidence)


async def _interchange_plan(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    """Read somebody else's edit — the engine names the format, not the caller.

    One read here, and it is allowed to refuse: `*_TRACK_COUNT` means "add tracks first", which
    the next step acts on. A document that answers outright is remembered so nothing is read twice.
    """
    path = f"/v1/projects/{ctx['project_id']}/import"
    payload: dict[str, Any] = {"document": request.interchange_document, "apply": False}
    if request.interchange_format:
        payload["format"] = request.interchange_format
    status, body = await ask(door, "POST", path, payload, tolerate=TRACK_COUNT_REFUSALS)
    if status >= 400:
        details = (body.get("error") or {}).get("details") or {}
        return ran("POST", "/v1/projects/{id}/import",
                   needs_tracks=wanted_tracks(details, {"video": 0, "audio": 0}))
    ctx["imported_commands"] = list(body.get("commands") or [])
    return ran(
        "POST",
        "/v1/projects/{id}/import",
        format=body.get("format"),
        commands=len(ctx["imported_commands"]),
        omitted=len(body.get("omitted") or []),
        complete=bool(body.get("complete")),
    )


def wanted_tracks(details: dict[str, Any], added: dict[str, int]) -> dict[str, int]:
    """Normalise a reader's `wanted` into per-kind counts.

    Two shapes exist and both are the engine's own statement: OTIO / EDL / 剪映 say
    `{"video": n, "audio": m}`, FCPXML / xmeml say one integer for the kind they checked and tell
    which by the `available` count — the number that matches what is already there. On a tie the
    picture kind goes first, which is the order those readers check in.
    """
    raw = details.get("wanted")
    if isinstance(raw, dict):
        return {"video": int(raw.get("video") or 0), "audio": int(raw.get("audio") or 0)}
    need = int(raw or 0)
    have = int(details.get("available") or 0)
    kind = "audio" if (have == added.get("audio", 0) and have != added.get("video", 0)) else "video"
    return {"video": need if kind == "video" else 0, "audio": need if kind == "audio" else 0}


async def borrow_plan(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> tuple[list, dict]:
    """Read the borrowed document, adding exactly the tracks it asks for, until it answers.

    Every round is one refusal from the engine naming counts — never a guess of ours — and each
    round writes its `track.add` batch through the same `/edits` door. The loop stops when the
    reader answers, or when a round would add nothing (then the refusal is raised as it came).
    """
    path = f"/v1/projects/{ctx['project_id']}/import"
    payload: dict[str, Any] = {"document": request.interchange_document, "apply": False}
    if request.interchange_format:
        payload["format"] = request.interchange_format
    added = {"video": 0, "audio": 0}
    rounds = 0
    while rounds < 6:
        rounds += 1
        status, body = await ask(door, "POST", path, payload, tolerate=TRACK_COUNT_REFUSALS)
        if status < 400:
            commands = list(body.get("commands") or [])
            counts = {"plan_rounds": rounds, "added_tracks": added["video"] + added["audio"]}
            ctx["imported_commands"] = commands
            return commands, {**counts, "format": body.get("format"),
                              "omitted": len(body.get("omitted") or [])}
        details = (body.get("error") or {}).get("details") or {}
        want = wanted_tracks(details, added)
        missing = {kind: max(0, want[kind] - added[kind]) for kind in ("video", "audio")}
        if not any(missing.values()):
            raise EditorError(
                str((body.get("error") or {}).get("code") or "AGENT_RUN_FAILED"),
                f"那份文档要的轨道补不上了：{details}",
                status,
                called="POST /v1/projects/{id}/import",
                details=details,
            )
        await ensure_ids(door, ctx, missing["video"] + missing["audio"])
        commands = []
        for kind, label in (("video", "画面"), ("audio", "声音")):
            for index in range(missing[kind]):
                commands.append(
                    {"op": "track.add",
                     "track": {"id": take_ids(ctx, 1)[0], "kind": kind,
                               "name": f"{label} {added[kind] + index + 1}"}}
                )
            added[kind] += missing[kind]
        _status, receipt = await ask(
            door,
            "POST",
            f"/v1/projects/{ctx['project_id']}/edits?receipt=slim",
            {
                "request_id": f"{request.request_id}-tracks-{rounds}",
                "expected_revision": ctx["revision"],
                "commands": commands,
            },
        )
        ctx["revision"] = int(receipt["revision"])
    raise EditorError("RECIPE_STEP_UNIMPLEMENTED", "补轨道那几轮没走完", 500, rounds=rounds)


async def ensure_ids(door: Door, ctx: dict[str, Any], want: int) -> int:
    """Top the id pool up to what the engine just asked for; says how many it fetched."""
    missing = want - (len(ctx.get("ids") or []) - int(ctx.get("cursor") or 0))
    if missing <= 0:
        return 0
    path = f"/v1/ids?count={missing}"
    _status, body = await ask(door, "POST", path)
    ctx["ids"] = list(ctx.get("ids") or []) + [str(item) for item in body["ids"]]
    return missing


async def _project_get(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    _status, body = await ask(door, "GET", f"/v1/projects/{ctx['project_id']}")
    ctx["revision"] = int(body["revision"])
    return ran(
        "GET",
        "/v1/projects/{id}",
        revision=ctx["revision"],
        tracks=len(body.get("tracks") or []),
        clips=len(body.get("clips") or {}),
        assets=len(body.get("assets") or {}),
    )


async def _export_document(
    door: Door, request: RecipeRun, ctx: dict[str, Any], tool: str
) -> dict[str, Any]:
    path = f"/v1/projects/{ctx['project_id']}/{tool}"
    _status, body = await ask(door, "GET", path)
    evidence: dict[str, Any] = {"bytes": size_of(body), "revision": body.get("revision")}
    if request.include_text:
        evidence["document"] = body
    return ran("GET", f"/v1/projects/{{id}}/{tool}", **evidence)


async def _otio(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    return await _export_document(door, request, ctx, "otio")


async def _xmeml(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    return await _export_document(door, request, ctx, "xmeml")


async def _jianying(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    return await _export_document(door, request, ctx, "jianying")


async def _render_batch(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    if not request.render:
        return skipped("render=false：没有排交付")
    items = [item.model_dump(mode="json") for item in (request.deliver_items or [])]
    payload = {
        "request_id": f"{request.request_id}-batch",
        "expected_revision": ctx["revision"],
        "items": items,
    }
    _status, body = await ask(door, "POST", f"/v1/projects/{ctx['project_id']}/renders/batch",
                              payload)
    ctx["jobs"] = list(body.get("jobs") or [])
    ctx["job"] = ctx["jobs"][0] if ctx["jobs"] else None
    return ran(
        "POST",
        "/v1/projects/{id}/renders/batch",
        jobs=len(ctx["jobs"]),
        filenames=[str(job.get("filename")) for job in ctx["jobs"]],
    )


async def _master_loudness(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    """Land the whole mix on the caller's loudness target, measured the way the export plays it.

    The meter reads a throwaway render of the same audio graph the export uses, so the number is
    the mix a viewer hears (overlaps, fades and ducking included) and the write is one
    `project.update` — one revision, undo returns the previous gain. No target means hands off:
    this door does not get to decide how loud someone's film is.
    """
    target = request.loudness_target_lufs
    if target is None:
        return skipped("没给 loudness_target_lufs：这一刀不替人决定响度，master_gain 原样留着")
    path = f"/v1/projects/{ctx['project_id']}/master/loudness"
    payload = {
        "request_id": f"{request.request_id}-loudness",
        "expected_revision": ctx["revision"],
        "target_lufs": target,
        "apply": True,
    }
    status, body = await ask(door, "POST", path, payload, tolerate=("INVALID_LOUDNESS_TARGET",))
    master = body.get("master") or {}
    if status >= 400:
        return ran("POST", path, changed=False, predicted_lufs=master.get("predicted_lufs"),
                   note=str((body.get("error") or {}).get("message")))
    ctx["revision"] = int(body["project"]["revision"])
    return ran(
        "POST",
        path,
        target_lufs=master.get("target_lufs"),
        measured_lufs=master.get("integrated_lufs"),
        predicted_lufs=master.get("predicted_lufs"),
        reaches_target=bool(master.get("reaches_target")),
        gain=master.get("proposed_master_gain"),
        revision=ctx["revision"],
    )


async def _overview(_door: Door, _request: RecipeRun, _ctx: dict[str, Any]) -> dict[str, Any]:
    return skipped("接触表是一张 PNG，这一刀不替你看图；要眼睛就单独叫 timeline_overview")


async def _preview(_door: Door, _request: RecipeRun, _ctx: dict[str, Any]) -> dict[str, Any]:
    return skipped("抽帧也是 PNG：想要某一秒长什么样，用 preview_frame 带上 t 单独调")


async def _render_plan(door: Door, request: RecipeRun, ctx: dict[str, Any]) -> dict[str, Any]:
    if not request.render:
        return skipped("render=false：这一刀只到中间状态，交付由你自己排 render_start")
    if request.deliver_items:
        return skipped("这一刀走批量交付（render_batch），单预设的编译计划不在形状里")
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
    if request.deliver_items:
        return skipped("这一刀走批量交付（render_batch）")
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
    jobs = ctx.get("jobs") or ([ctx["job"]] if ctx.get("job") else [])
    if not jobs:
        return skipped("render=false 或没排上交付：没有作业可等")
    if request.wait_seconds <= 0:
        return skipped("wait_seconds=0：交付已排队，要在这刀里等到终态就把它设到 1..120")
    poll = min(0.5, max(0.05, request.wait_seconds / 20))
    waited: list[dict[str, Any]] = []
    for job in jobs:
        path = f"/v1/jobs/{job['id']}/wait?timeout={request.wait_seconds}&poll={poll}"
        _status, body = await ask(door, "GET", path)
        waited.append(dict(body["job"]))
        ctx["waited_ms"] = int(ctx.get("waited_ms") or 0) + int(body.get("waited_ms") or 0)
        ctx["timed_out"] = bool(ctx.get("timed_out")) or bool(body.get("timed_out"))
    ctx["jobs"] = waited
    ctx["job"] = waited[0]
    return ran(
        "GET",
        "/v1/jobs/{id}/wait",
        jobs=len(waited),
        statuses=sorted({str(job.get("status")) for job in waited}),
        waited_ms=ctx["waited_ms"],
        timed_out=ctx["timed_out"],
        output_checked=waited[0].get("output_checked"),
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
    "master_loudness": _master_loudness,
    "captions_auto": _captions_auto,
    "timeline_transcript": _transcript_view,
    "transcript_cut_plan": _transcript_cut,
    "captions_export": _captions_export,
    "interchange_import_plan": _interchange_plan,
    "project_get": _project_get,
    "project_otio": _otio,
    "project_xmeml": _xmeml,
    "project_jianying": _jianying,
    "render_batch": _render_batch,
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
        "master_loudness",
        "captions_auto",
        "transcript_cut_plan",
        "interchange_import_plan",
        "render_plan",
        "render_start",
        "render_batch",
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
    jobs = [dict(job) for job in (listed.get("jobs") or [])]
    if jobs:
        wanted = next((job for job in jobs if job.get("filename") == request.filename), None)
        ctx["job"] = wanted or jobs[0]
        ctx["jobs"] = jobs
        ctx["waited_ms"] = 0
        ctx["timed_out"] = str((wanted or jobs[0]).get("status")) not in {
            "succeeded",
            "failed",
            "cancelled",
        }


async def run(door: Door, recipe_id: str, request: RecipeRun) -> dict[str, Any]:
    """Walk the recipe, one declared step at a time, and answer with the step log."""
    if recipe_id not in RUNNABLE_RECIPES:
        raise refusal(recipe_id)
    gaps = missing_params(recipe_id, request)
    if gaps:
        raise EditorError(
            "RECIPE_PARAM_MISSING",
            f"配方 {recipe_id} 缺这些参数：{'、'.join(gaps)}",
            422,
            recipe_id=recipe_id,
            missing=gaps,
            required=list(required_fields(recipe_id, request)),
        )
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
    jobs = ctx.get("jobs") or ([ctx["job"]] if ctx.get("job") else [])
    return {
        "recipe": recipe_id,
        "request_id": request.request_id,
        "replayed": bool(ctx.get("replayed")),
        "project_id": ctx.get("project_id"),
        "revision": ctx.get("revision"),
        "clips": len(ctx.get("verified") or []),
        "steps": rows,
        "job": ctx.get("job"),
        "jobs": jobs or None,
        "output_path": (jobs[0].get("output_path") if jobs else None),
        "waited_ms": ctx.get("waited_ms"),
        "timed_out": ctx.get("timed_out"),
        "plan": ctx.get("plan"),
    }
