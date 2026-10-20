from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from errors import AgentError  # noqa: E402  与 server.py 共用同一个类对象

from agentcut.contracts import (  # noqa: E402  必须先有 sys.path 才导得到
    APP_VERSION,
    SCHEMA_VERSION,
    TIMEBASE,
    CreateProject,
    EditBatch,
    EditorError,
    FrameRate,
    SequenceSettings,
    capabilities,
)
from agentcut.projects import ProjectStore  # noqa: E402

PROJECT = {
    "id": "agentcut",
    "name": "AgentCut",
    "version": APP_VERSION,
    "summary": (
        "本地视频剪辑与时间线引擎：多轨剪辑、转场特效、关键帧动画、"
        "文字字幕、调色混音与批量渲染交付。"
    ),
    "port": 8780,
}
PROJECT_ID = "agentcut"

# 默认落在工程自己的 data 目录（与桌面端、HTTP 服务同一个库）；AGENTCUT_DATA_DIR 让
# 验收脚本与并行的第二个实例指到自己的那一份，不会去动用户真实的工程数据库。
DATA_DIR = Path(os.environ.get("AGENTCUT_DATA_DIR") or PROJECT_ROOT / "data")
DB_PATH = DATA_DIR / "agentcut.sqlite3"
DATA_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG = os.environ.get("AGENTCUT_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("AGENTCUT_FFPROBE") or shutil.which("ffprobe") or "ffprobe"

store = ProjectStore(DB_PATH)


def _find_binaries():
    return {
        "ffmpeg": shutil.which(FFMPEG) or FFMPEG,
        "ffprobe": shutil.which(FFPROBE) or FFPROBE,
        "database": str(DB_PATH),
        "data_dir": str(DATA_DIR),
    }


def _engine_error(failure: Exception) -> AgentError:
    """引擎的拒绝原样交回：它已经带了 code 与那句话，Agent 要的就是这一句。"""
    if isinstance(failure, EditorError):
        return AgentError(failure.code.lower(), failure.message)
    return AgentError("edit_failed", str(failure))


def _project_id(args: dict[str, Any]) -> str:
    project_id = str(args.get("id", "")).strip()
    if not project_id:
        raise AgentError("bad_input", "缺少必填参数: id")
    return project_id


def _request_id(args: dict[str, Any]) -> str:
    """幂等回执的键：调用方不给就生成一个（uuid4 的字符集落在 Identifier 里）。"""
    return str(args.get("request_id") or uuid.uuid4())


def handle_status(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "binaries": _find_binaries(),
        "total_projects": len(store.list_projects()),
    }


def handle_capabilities(args: dict[str, Any]) -> dict[str, Any]:
    """引擎自己那张能力表，一个字不抄：转场名、淡的形状、上限都在这里，
    与 /v1/capabilities 同一份，所以 Agent 按着它写的命令一定认。"""
    table = capabilities()
    table["timebase"] = TIMEBASE
    return table


def handle_project_create(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name", "未命名剪辑工程")).strip()
    settings_args: dict[str, Any] = {}
    if args.get("fps") is not None:
        settings_args["frame_rate"] = FrameRate(numerator=int(args["fps"]))
    for side in ("width", "height"):
        if args.get(side) is not None:
            settings_args[side] = int(args[side])
    request = CreateProject(
        request_id=_request_id(args),
        name=name,
        settings=SequenceSettings(**settings_args),
    )
    project = store.create(request).project
    return {
        "id": project.id,
        "name": project.name,
        "revision": project.revision,
        "frame_rate": project.settings.frame_rate.model_dump(),
        "width": project.settings.width,
        "height": project.settings.height,
        "timebase": project.settings.timebase,
    }


def handle_project_list(args: dict[str, Any]) -> dict[str, Any]:
    """行是引擎那一份：id、name、revision、clips、assets、content_ticks（格数）。"""
    rows = store.list_projects(
        limit=max(1, min(int(args.get("limit") or 100), 500)),
        offset=max(0, int(args.get("offset") or 0)),
    )
    return {"total": len(rows), "projects": rows}


def handle_project_get(args: dict[str, Any]) -> dict[str, Any]:
    project_id = _project_id(args)
    try:
        project = store.get(project_id)
    except EditorError as failure:
        raise _engine_error(failure) from failure
    return project.model_dump(mode="json")


def handle_timeline_edit(args: dict[str, Any]) -> dict[str, Any]:
    project_id = _project_id(args)
    commands = args.get("commands")
    if not isinstance(commands, list) or not commands:
        raise AgentError("bad_input", "commands 必须是非空列表")
    if args.get("expected_revision") is None:
        raise AgentError("bad_input", "缺少必填参数: expected_revision")
    batch = EditBatch(
        request_id=_request_id(args),
        expected_revision=int(args["expected_revision"]),
        commands=commands,
        dry_run=bool(args.get("dry_run", False)),
    )
    try:
        result = store.mutate(project_id, batch)
    except EditorError as failure:
        raise _engine_error(failure) from failure
    return result.model_dump(mode="json")


EMPTY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

TOOLS = [
    {
        "name": "agentcut.status",
        "description": (
            "获取 AgentCut 剪辑引擎版本、FFmpeg/FFprobe 环境与本地数据库状态。"
        ),
        "input_schema": EMPTY_INPUT_SCHEMA,
        "risk": "read",
        "handler": handle_status,
    },
    {
        "name": "agentcut.capabilities",
        "description": (
            "查询剪辑引擎特性清单（转场类型、淡入淡出曲线形状、时间基准与上限参数）；"
            "这一份与 HTTP 的 /v1/capabilities 同源。"
        ),
        "input_schema": EMPTY_INPUT_SCHEMA,
        "risk": "read",
        "handler": handle_capabilities,
    },
    {
        "name": "agentcut.project_create",
        "description": "创建一个新的视频剪辑工程，指定分辨率、帧率与工程名称。",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "工程名称"},
                "fps": {
                    "type": "integer",
                    "description": "帧率分子，如 30 或 60",
                },
                "width": {
                    "type": "integer",
                    "description": "画面宽度（像素），如 1920",
                },
                "height": {
                    "type": "integer",
                    "description": "画面高度（像素），如 1080",
                },
                "request_id": {
                    "type": "string",
                    "description": "幂等请求 ID（可选）",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "risk": "write",
        "handler": handle_project_create,
    },
    {
        "name": "agentcut.project_list",
        "description": "列出本机数据库里已保存的剪辑工程（每行给 revision 与片段数）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "最多列几条，1..500，默认 100",
                },
                "offset": {
                    "type": "integer",
                    "description": "跳过前几条，默认 0",
                },
            },
            "additionalProperties": False,
        },
        "risk": "read",
        "handler": handle_project_list,
    },
    {
        "name": "agentcut.project_get",
        "description": "根据工程 ID 读取完整的工程时间线数据（轨道、片段、关键帧与属性）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "工程 ID"},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        "risk": "read",
        "handler": handle_project_get,
    },
    {
        "name": "agentcut.timeline_edit",
        "description": (
            "执行时间线批量编辑命令（分割、修剪、移动、滤镜属性变更），"
            "支持 dry_run 试跑验证。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "工程 ID"},
                "commands": {"type": "array", "description": "编辑命令列表"},
                "expected_revision": {
                    "type": "integer",
                    "description": "期望的工程版本号，防止并发写冲突",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "若为 true 则只校验命令不写库",
                },
                "request_id": {
                    "type": "string",
                    "description": "幂等请求 ID（可选）",
                },
            },
            "required": ["id", "commands", "expected_revision"],
            "additionalProperties": False,
        },
        "risk": "write",
        "handler": handle_timeline_edit,
    },
]
