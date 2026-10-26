"""One machine-readable answer to "what may an agent do here, and through which door".

The engine speaks to agents through two surfaces: the HTTP API and the MCP adapter.
Before this file an agent learned them from prose, and a third copy had grown up in
`agent/tools.py` (six hand-written tools opening the project database directly) — three
doors, three truths. This module builds the contract from the two live objects instead:
FastAPI's own route table and the FastMCP tool registry. A name, a schema or a read/write
flag can then only be reported as it actually is, and the recipes below are the same
objects the MCP prompts serve, so "how do I cut a whole film" has one answer.
"""

from __future__ import annotations

import re
from typing import Any

from .contracts import APP_VERSION, SCHEMA_VERSION, TIMEBASE, capabilities

# FastAPI mounts these itself; they describe the framework, not what an agent may call.
INTERNAL_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
READ_METHODS = frozenset({"GET", "HEAD"})

# 三条配方是「一个 agent 接手另一个 agent 的活」时真正要抄的东西：步骤按工具名排，
# 每一步说清为什么是这一步。工具名一律用 MCP 那一份，门禁逐条对manifest。
RECIPES: tuple[dict[str, Any], ...] = (
    {
        "id": "cut-from-media",
        "title": "从素材到一条粗剪并交付",
        "when": "手上只有几个原始文件，要出一条能直接发出去的片子。",
        "steps": [
            {"tool": "editor_capabilities", "why": "先问这台引擎认哪些命令与预设，别照记忆写"},
            {"tool": "media_config", "why": "素材必须落在授权根目录里，先看清是哪几个目录"},
            {"tool": "media_import", "why": "探测出真实时长、帧率与声轨，交回可信的素材记录"},
            {"tool": "project_create", "why": "一个 request_id 一次创建，重复提交拿回同一个工程"},
            {"tool": "ids_request", "why": "轨道/素材/片段的 id 由服务端发，避免两边撞号"},
            {"tool": "timeline_edit", "why": "轨道、素材与片段一批写完，一个 revision"},
            {
                "tool": "track_silence",
                "why": "把每条里的停顿找出来，apply=true 让服务端同一批落库",
            },
            {
                "tool": "track_rough_cut",
                "why": "每个镜头只留头几秒，整条轨道一次做完，仍是普通命令",
            },
            {"tool": "timeline_overview", "why": "一张接触表看完整条时间线，确认剪的是什么"},
            {"tool": "preview_frame", "why": "抽查几个刻度：预览与导出读的是同一份编译"},
            {"tool": "render_plan", "why": "只编译不渲染：看清 ffmpeg 的 argv 与图"},
            {"tool": "render_start", "why": "对固定 revision 排队交付"},
            {
                "tool": "job_wait",
                "why": "一次调用等到终态，拿回输出路径与校验过的长度",
            },
        ],
    },
    {
        "id": "speech-to-captions",
        "title": "口播转字幕并按句子剪",
        "when": "一条讲话素材，要字幕、要按句剪、要能改字。",
        "steps": [
            {"tool": "editor_capabilities", "why": "看这台引擎有没有本地语音与字幕能力位"},
            {"tool": "media_import", "why": "先有可信的音频素材记录"},
            {"tool": "captions_auto", "why": "本地模型出字幕 cue，只交计划不写库"},
            {"tool": "timeline_edit", "why": "字幕作为文字片段落进字幕轨"},
            {"tool": "timeline_transcript", "why": "读回「说了什么、在哪」，含句间静音"},
            {"tool": "transcript_cut_plan", "why": "删一行字＝剪掉那一段，交回普通命令"},
            {"tool": "timeline_edit", "why": "应用这一批剪切命令，撤销一步整体退回"},
            {"tool": "captions_export", "why": "要交给别人时导出 SRT"},
        ],
    },
    {
        "id": "imitate-imported-edit",
        "title": "把别人剪好的一刀搬过来再交付",
        "when": "手上是 FCPXML / Premiere XML / EDL / OTIO / 剪映草稿，要接着剪。",
        "steps": [
            {"tool": "interchange_import_plan", "why": "引擎自己认格式，先交回命令与清单"},
            {"tool": "timeline_edit", "why": "审过计划再落库，一个 revision"},
            {"tool": "project_get", "why": "核对轨道、片段与 revision"},
            {"tool": "preview_frame", "why": "抽查画面，确认对上了源"},
            {"tool": "project_otio", "why": "交回中性格式"},
            {"tool": "project_xmeml", "why": "交回 Premiere / FCP7 那一支"},
            {"tool": "project_jianying", "why": "交回剪映草稿"},
            {"tool": "render_batch", "why": "一次排多个预设/画幅，一单交付"},
        ],
    },
)


# 1.311：`recipe_run` 能把哪条配方一把跑完。不在这里的配方在契约里带着原因说清楚——
# 一把跑不完是缺输入或缺判断，不是这一版偷懒。
RUNNABLE_RECIPES = frozenset({"cut-from-media"})
RECIPE_LIMITS = {
    "speech-to-captions": "字幕要不要落库、改哪一行是人的判断，这一刀只交回 cue",
    "imitate-imported-edit": "要先点名读哪一份工程文件，搬哪些轨道由你决定",
}


# 每一只 MCP 工具背后就是这一条路由——两条门面因此是同一批口，不是两套规则。
# 这张表是 agent/ 那台桥唯一的派发依据，也是门禁逐条对照的清单：路径写错、少一只工具，
# 都会在 agent_contract_check 上红在自家断言里。
TOOL_ENDPOINTS: dict[str, tuple[str, str]] = {
    "animation_curve": ("POST", "/v1/animation/curve"),
    "animation_layer_curve": ("POST", "/v1/animation/layer_curve"),
    "animation_sample": ("POST", "/v1/animation/sample"),
    "audio_beats": ("POST", "/v1/projects/{project_id}/audio/beats"),
    "captions_auto": ("POST", "/v1/projects/{project_id}/speech-captions"),
    "captions_export": ("GET", "/v1/projects/{project_id}/captions/{track_id}"),
    "clip_attribute_plan": ("POST", "/v1/projects/{project_id}/clips/{clip_id}/attribute-plan"),
    "clip_auto_grade": ("POST", "/v1/projects/{project_id}/clips/{clip_id}/auto-grade"),
    "clip_color_space": ("POST", "/v1/projects/{project_id}/clips/{clip_id}/color-space"),
    "clip_four_point": ("POST", "/v1/projects/{project_id}/four-point"),
    "clip_loudness": ("POST", "/v1/projects/{project_id}/clips/{clip_id}/loudness"),
    "clip_reframe": ("POST", "/v1/projects/{project_id}/clips/{clip_id}/reframe"),
    "clip_rough_cut": ("POST", "/v1/projects/{project_id}/clips/{clip_id}/rough-cut"),
    "clip_sample": ("GET", "/v1/projects/{project_id}/clips/{clip_id}/sample"),
    "clip_scenes": ("POST", "/v1/projects/{project_id}/clips/{clip_id}/scenes"),
    "clip_silence": ("POST", "/v1/projects/{project_id}/clips/{clip_id}/silence"),
    "clip_stabilize": ("POST", "/v1/projects/{project_id}/clips/{clip_id}/stabilize"),
    "clips_sync": ("POST", "/v1/projects/{project_id}/sync"),
    "editor_capabilities": ("GET", "/v1/capabilities"),
    "editor_contracts": ("GET", "/v1/contracts"),
    "editor_info": ("GET", "/v1/info"),
    "frame_stability": ("POST", "/v1/projects/{project_id}/frame-stability"),
    "grade_capacity": ("GET", "/v1/projects/{project_id}/grade-capacity"),
    "ids_request": ("POST", "/v1/ids"),
    "interchange_import_plan": ("POST", "/v1/projects/{project_id}/import"),
    "job_cancel": ("POST", "/v1/jobs/{job_id}/cancel"),
    "job_list": ("GET", "/v1/projects/{project_id}/jobs"),
    "job_status": ("GET", "/v1/jobs/{job_id}"),
    "job_wait": ("GET", "/v1/jobs/{job_id}/wait"),
    "lut_parse": ("POST", "/v1/lut/parse"),
    "marker_split": ("POST", "/v1/projects/{project_id}/markers/split"),
    "mask_stack_track": (
        "POST", "/v1/projects/{project_id}/clips/{clip_id}/mask-stack/{index}/track"
    ),
    "mask_track": ("POST", "/v1/projects/{project_id}/mask-track"),
    "master_loudness": ("POST", "/v1/projects/{project_id}/master/loudness"),
    "media_cache_prune": ("POST", "/v1/media/cache/prune"),
    "media_cache_read": ("GET", "/v1/media/cache"),
    "media_config": ("GET", "/v1/media/config"),
    "media_import": ("POST", "/v1/media/import"),
    "media_probe": ("GET", "/v1/media/{probe_id}"),
    "media_proxies_prune": ("POST", "/v1/media/proxies/prune"),
    "otio_import_plan": ("POST", "/v1/projects/{project_id}/otio/import"),
    "output_root_add": ("POST", "/v1/outputs/roots"),
    "output_roots_read": ("GET", "/v1/outputs/roots"),
    "preview_candidate": ("POST", "/v1/preview-manifest"),
    "preview_frame": ("GET", "/v1/projects/{project_id}/frame"),
    "preview_manifest": ("GET", "/v1/projects/{project_id}/preview-manifest"),
    "project_asset_urls": ("GET", "/v1/projects/{project_id}/asset-urls"),
    "project_clips": ("GET", "/v1/projects/{project_id}/clips"),
    "project_create": ("POST", "/v1/projects"),
    "project_edl": ("GET", "/v1/projects/{project_id}/edl"),
    "project_fcpxml": ("GET", "/v1/projects/{project_id}/fcpxml"),
    "project_get": ("GET", "/v1/projects/{project_id}"),
    "project_history": ("GET", "/v1/projects/{project_id}/history"),
    "project_jianying": ("GET", "/v1/projects/{project_id}/jianying"),
    "project_list": ("GET", "/v1/projects"),
    "project_otio": ("GET", "/v1/projects/{project_id}/otio"),
    "project_restore": ("POST", "/v1/projects/{project_id}/restore"),
    "project_update": ("POST", "/v1/projects/{project_id}"),
    "project_xmeml": ("GET", "/v1/projects/{project_id}/xmeml"),
    "recipe_run": ("POST", "/v1/agent/recipes/{recipe_id}/run"),
    "render_batch": ("POST", "/v1/projects/{project_id}/renders/batch"),
    "render_plan": ("GET", "/v1/projects/{project_id}/render-plan"),
    "render_presets_read": ("GET", "/v1/render-presets"),
    "render_start": ("POST", "/v1/projects/{project_id}/renders"),
    "timeline_edit": ("POST", "/v1/projects/{project_id}/edits"),
    "timeline_overview": ("GET", "/v1/projects/{project_id}/overview"),
    "timeline_transcript": ("GET", "/v1/projects/{project_id}/transcript"),
    "track_duck": ("POST", "/v1/projects/{project_id}/tracks/{track_id}/duck"),
    "track_fade_adoption": ("POST", "/v1/projects/{project_id}/tracks/{track_id}/fade-adopt"),
    "track_grade_apply": ("POST", "/v1/projects/{project_id}/tracks/{track_id}/grade-apply"),
    "track_loudness": ("POST", "/v1/projects/{project_id}/tracks/{track_id}/loudness"),
    "track_rough_cut": ("POST", "/v1/projects/{project_id}/tracks/{track_id}/rough-cut"),
    "track_silence": ("POST", "/v1/projects/{project_id}/tracks/{track_id}/silence"),
    "transcript_cut_plan": ("POST", "/v1/projects/{project_id}/transcript/cut"),
}

# 这两只交回的是 PNG 而不是 JSON：桥把它们包成 base64，别假装是普通应答。
BINARY_TOOLS = frozenset({"preview_frame", "timeline_overview"})


def resolve(
    name: str,
    args: dict[str, Any],
    params: dict[tuple[str, str], dict[str, list[str]]] | None = None,
) -> tuple[str, str, dict[str, Any], Any]:
    """Turn (tool, arguments) into (method, path, query, body) — one rule for every caller.

    The split between path / query / body is read off the route's own signature when
    `params` is given (the bridge gets it from the manifest), so an argument the server
    expects as a query parameter cannot quietly be swallowed into a JSON body — that is
    how a `dry_run` would turn into a real write. The agent bridge and the contract gate
    both go through here, so a tool cannot mean one request on one surface and another on
    the other.
    """
    try:
        method, template = TOOL_ENDPOINTS[name]
    except KeyError as failure:
        raise KeyError(f"工具 {name} 没有登记路由") from failure
    shape = (params or {}).get((method, template), {})
    rest = dict(args or {})
    path = template
    for placeholder in re.findall(r"\{([a-z_]+)\}", template):
        if placeholder not in rest:
            raise ValueError(f"缺少必填参数：{placeholder}")
        path = path.replace("{" + placeholder + "}", str(rest.pop(placeholder)))
    query_names = set(shape.get("query") or [])
    body_names = shape.get("body") or []
    query: dict[str, Any] = {}
    body: Any = None
    if method == "GET":
        # GET 那几支里，有的参数是一整个请求模型（`timeline_transcript` 的 merge_gap_ms 那一类）：
        # 引擎把它摊平成查询参数，这里也摊平——不摊平就会把 `request` 当成一个查询键发出去。
        for key, value in rest.items():
            if value is None:
                continue
            if isinstance(value, dict):
                query.update({name: item for name, item in value.items() if item is not None})
            else:
                query[key] = value
    else:
        inline: dict[str, Any] = {}
        for key in list(rest):
            if key in query_names:
                query[key] = rest.pop(key)
            elif len(body_names) == 1 and key == body_names[0] and body is None:
                body = rest.pop(key)
            else:
                inline[key] = rest.pop(key)
        if body is None and inline:
            body = inline
    return method, path, query, body


def route_params(app: Any) -> dict[tuple[str, str], dict[str, list[str]]]:
    """(method, path) -> the route's own path / query / body parameter names."""
    table: dict[tuple[str, str], dict[str, list[str]]] = {}
    for route in getattr(app, "routes", []):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        dependant = getattr(route, "dependant", None)
        if not path or not methods or dependant is None:
            continue
        split = {
            "path": [item.name for item in dependant.path_params],
            "query": [item.name for item in dependant.query_params],
            "body": [item.name for item in dependant.body_params],
        }
        for method in methods:
            if method not in {"HEAD", "OPTIONS"}:
                table[(method, path)] = split
    return table


def route_table(app: Any) -> list[dict[str, Any]]:
    """Every endpoint the running app actually answers, with its read/write nature."""
    params = route_params(app)
    rows: list[dict[str, Any]] = []
    for route in getattr(app, "routes", []):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods or path in INTERNAL_PATHS:
            continue
        summary = (getattr(route, "summary", "") or "").strip()
        if not summary:
            description = (getattr(route, "description", "") or "").strip()
            summary = description.splitlines()[0] if description else ""
        for method in sorted(methods):
            if method in {"HEAD", "OPTIONS"}:
                continue
            split = params.get((method, path), {})
            rows.append({
                "method": method,
                "path": path,
                "read_only": method in READ_METHODS,
                "operation": getattr(route, "name", "") or "",
                "summary": summary[:180],
                "path_params": split.get("path", []),
                "query_params": split.get("query", []),
                "body_params": split.get("body", []),
            })
    rows.sort(key=lambda row: (row["path"], row["method"]))
    return rows


async def tool_table(server: Any) -> list[dict[str, Any]]:
    """The MCP roster as the live server reports it — names, schemas, read-only flags."""
    tools = await server.list_tools()
    rows = []
    for tool in tools:
        rows.append({
            "name": tool.name,
            "description": (tool.description or "").strip(),
            "read_only": bool(tool.annotations and tool.annotations.readOnlyHint),
            "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
        })
    rows.sort(key=lambda row: row["name"])
    return rows


def recipes() -> list[dict[str, Any]]:
    return [
        {
            "id": recipe["id"],
            "title": recipe["title"],
            "when": recipe["when"],
            # 一把跑完的门只对得上开的那条；开不通的两条带着原因说，不装作什么都能自动。
            "runnable": recipe["id"] in RUNNABLE_RECIPES,
            "why_not": RECIPE_LIMITS.get(recipe["id"]),
            "steps": [dict(step) for step in recipe["steps"]],
        }
        for recipe in RECIPES
    ]


def render_recipe(recipe: dict[str, Any]) -> str:
    """One recipe as the text an agent gets from the MCP prompt — same words, one owner."""
    lines = [f"配方：{recipe['title']}", recipe["when"], ""]
    for index, step in enumerate(recipe["steps"], 1):
        lines.append(f"{index}. {step['tool']} —— {step['why']}")
    lines.append("")
    if recipe["id"] in RUNNABLE_RECIPES:
        lines += [
            f"这一条也能一把跑完：recipe_run（POST /v1/agent/recipes/{recipe['id']}/run）。",
            "它走的就是上面这些路由：同一条 bearer 令牌、同一个 reducer，",
            "一个 request_id 贯穿整刀，重放拿回同一个工程、同一批 revision、同一个交付作业。",
        ]
    else:
        lines.append(f"这一条不能一把跑完：{RECIPE_LIMITS.get(recipe['id'], '这一步要你点名')}。")
    lines += [
        "",
        "工具名与参数以 GET /v1/agent/manifest（MCP 资源 agentcut://manifest）为准；",
        "每一步的 expected_revision 用上一步返回的那一个；被拒绝时按 error.code 改这一步，"
        "不要绕开引擎自己补规则。",
    ]
    return "\n".join(lines)


async def manifest(
    app: Any,
    server: Any,
    *,
    base_url: str,
    live_capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The whole agent contract in one payload: what exists, how to call it, in what order.

    `live_capabilities` is the route's own answer to /v1/capabilities (it knows whether media,
    speech and fonts are ready on this machine). Left out, the contract falls back to the static
    table — and would then claim readiness it cannot see, which is the one thing a contract must
    not do.
    """
    table = await tool_table(server)
    for row in table:
        # 没有登记路由的工具交回 None，不偷偷少一只：门禁就钉在这个 None 上。
        entry = TOOL_ENDPOINTS.get(row["name"])
        row["endpoint"] = {"method": entry[0], "path": entry[1]} if entry else None
        row["binary"] = row["name"] in BINARY_TOOLS
    return {
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "timebase": TIMEBASE,
        "base_url": base_url,
        "auth": {
            "scheme": "bearer",
            "header": "authorization",
            "note": "每个 /v1 请求都要带引擎密钥（Authorization: Bearer <token>）；"
                    "桌面端把它写在自己的数据目录里，命令行用 AGENTCUT_TOKEN。",
        },
        "surfaces": {
            "http": "endpoints 就是全部路由；写一律 POST，幂等靠 request_id",
            "mcp": "tools 就是 MCP 那一侧的全部工具，每只都是同一批路由的薄壳，不在这一侧重写规则",
            "agent_api": "agent/ 那台本机桥把 tools 原样转成 /api/agent/tool",
        },
        "error_shape": {
            "envelope": '{"error":{"code":"...","message":"...","details":{...}}}',
            "retry": "同 request_id 同内容重发拿回同一份；内容不同是 IDEMPOTENCY_CONFLICT",
            "conflict": "expected_revision 落后是 REVISION_CONFLICT：先 project_get 再重做这一步",
        },
        "capabilities": live_capabilities if live_capabilities is not None else capabilities(),
        "endpoints": route_table(app),
        "tools": table,
        # 配方里的工具名一个都不过滤：写错名字要让门禁红，不能让契约自己把幽灵步骤吞掉。
        "recipes": recipes(),
    }
