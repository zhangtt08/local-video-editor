from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any
import uuid

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from errors import AgentError
from agentcut.contracts import (
    APP_VERSION,
    SCHEMA_VERSION,
    CreateProject,
    EditBatch,
    ProjectUpdate,
)
from agentcut.media import MediaService
from agentcut.projects import ProjectStore

PROJECT = {
    "id": "agentcut",
    "name": "AgentCut",
    "version": APP_VERSION,
    "summary": "本地视频剪辑与时间线引擎：多轨剪辑、转场特效、关键帧动画、文字字幕、调色混音与批量渲染交付。",
    "port": 8780,
}
PROJECT_ID = "agentcut"

DATA_DIR = PROJECT_ROOT / "data"
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


def handle_status(args: dict[str, Any]) -> dict[str, Any]:
    bins = _find_binaries()
    return {
        "version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "binaries": bins,
        "total_projects": len(store.list_projects()),
    }


def handle_capabilities(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "ticks_per_second": 70_560_000,
        "transition_kinds": [
            "dissolve", "fade_black", "flash_white",
            "wipe_left", "wipe_right", "wipe_up", "wipe_down",
            "zoom_in", "zoom_out",
            "push_from_left", "push_from_right", "push_from_top", "push_from_bottom"
        ],
        "fade_shapes": ["linear", "ease_in", "ease_out", "smoothstep"],
        "limits": {
            "max_tracks": 32,
            "max_clips": 2048,
            "max_inline_samples": 200_000
        }
    }


def handle_project_create(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name", "未命名剪辑工程")).strip()
    fps = int(args.get("fps", 30))
    width = int(args.get("width", 1920))
    height = int(args.get("height", 1080))
    
    req = CreateProject(
        name=name,
        fps=fps,
        width=width,
        height=height
    )
    result = store.create_project(req)
    return {
        "id": result.project.id,
        "name": result.project.name,
        "fps": result.project.fps,
        "width": result.project.width,
        "height": result.project.height,
        "revision": result.project.revision,
    }


def handle_project_list(args: dict[str, Any]) -> dict[str, Any]:
    rows = store.list_projects()
    items = []
    for p in rows:
        items.append({
            "id": p.id,
            "name": p.name,
            "revision": p.revision,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
            "tracks_count": len(p.tracks),
            "clips_count": len(p.clips),
        })
    return {"total": len(items), "projects": items}


def handle_project_get(args: dict[str, Any]) -> dict[str, Any]:
    project_id = str(args.get("id", "")).strip()
    if not project_id:
        raise AgentError("bad_input", "缺少必填参数: id")
    project = store.get_project(project_id)
    if not project:
        raise AgentError("not_found", f"未找到工程: {project_id}")
    return project.model_dump(mode="json")


def handle_timeline_edit(args: dict[str, Any]) -> dict[str, Any]:
    project_id = str(args.get("id", "")).strip()
    if not project_id:
        raise AgentError("bad_input", "缺少必填参数: id")
    commands = args.get("commands", [])
    expected_revision = args.get("expected_revision")
    dry_run = bool(args.get("dry_run", False))
    request_id = str(args.get("request_id") or uuid.uuid4())

    if not isinstance(commands, list):
        raise AgentError("bad_input", "commands 必须为列表")

    batch = EditBatch(
        request_id=request_id,
        expected_revision=expected_revision,
        commands=commands,
        dry_run=dry_run,
    )
    try:
        outcome = store.apply_batch(project_id, batch)
        return outcome.model_dump(mode="json")
    except Exception as e:
        raise AgentError("edit_failed", str(e))


TOOLS = [
    {
        "name": "agentcut.status",
        "description": "获取 AgentCut 剪辑引擎版本、FFmpeg/FFprobe 环境与本地数据库状态。",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "risk": "read",
        "handler": handle_status,
    },
    {
        "name": "agentcut.capabilities",
        "description": "查询剪辑引擎特性清单（转场类型、淡入淡出曲线形状、时间基准单位与上限参数）。",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
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
                "fps": {"type": "integer", "description": "帧率，如 30 或 60"},
                "width": {"type": "integer", "description": "画面宽度（像素），如 1920 或 1080"},
                "height": {"type": "integer", "description": "画面高度（像素），如 1080 或 1920"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "risk": "write",
        "handler": handle_project_create,
    },
    {
        "name": "agentcut.project_list",
        "description": "列出数据库中所有已保存的剪辑工程及其简要信息。",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "risk": "read",
        "handler": handle_project_list,
    },
    {
        "name": "agentcut.project_get",
        "description": "根据工程 ID 读取完整的工程时间线数据（轨道、片段、关键帧与属性）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "工程 ID"}
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        "risk": "read",
        "handler": handle_project_get,
    },
    {
        "name": "agentcut.timeline_edit",
        "description": "执行时间线批量编辑命令（分割、修剪、移动、滤镜属性变更），支持 dry_run 试跑验证。",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "工程 ID"},
                "commands": {"type": "array", "description": "编辑命令列表"},
                "expected_revision": {"type": "integer", "description": "期望的工程版本号，防止并发写冲突"},
                "dry_run": {"type": "boolean", "description": "若为 true 则只校验命令不写库"},
                "request_id": {"type": "string", "description": "幂等请求 ID（可选）"},
            },
            "required": ["id", "commands"],
            "additionalProperties": False,
        },
        "risk": "write",
        "handler": handle_timeline_edit,
    },
]
