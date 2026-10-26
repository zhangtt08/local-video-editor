"""AgentCut tools for the local Agent API hub — generated, not hand-written.

This file used to declare six operations and open `data/agentcut.sqlite3` with
`ProjectStore` itself: a second, shallower implementation of the same rules, free to drift
from the product and blind to everything the product added later (media, render, captions,
masks, interchange…). Now the tool list comes from the engine's own contract
(`agentcut.agent_contract`, the same object `/v1/agent/manifest` serves), and every call is
dispatched to the engine's own HTTP API — one token, one revision check, one idempotency
rule, one media-root guard, for all 72 tools and for whichever agent is on the other end.
"""

from __future__ import annotations

import atexit
import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from errors import AgentError  # noqa: E402  与 server.py 共用同一个类对象

from agentcut import agent_contract  # noqa: E402
from agentcut.contracts import APP_VERSION  # noqa: E402

PROJECT = {
    "id": "agentcut",
    "name": "AgentCut",
    "version": APP_VERSION,
    "summary": (
        "本地视频剪辑与时间线引擎：多轨剪辑、转场特效、关键帧动画、文字字幕、"
        "调色混音、批量渲染交付，以及五种工程格式（OTIO / FCPXML / xmeml / EDL / 剪映）进出。"
    ),
    "port": 8780,
}

# 引擎自己的数据目录（桌面端与 CLI 用的就是这一份）；AGENTCUT_DATA_DIR 让验收脚本
# 指到自己的那一份，不去动用户真实的工程库。
DATA_DIR = Path(os.environ.get("AGENTCUT_DATA_DIR") or PROJECT_ROOT / "data")
TOKEN_FILE = Path(os.environ.get("AGENTCUT_TOKEN_FILE") or DATA_DIR / "agentcut.token")
DEFAULT_URL = "http://127.0.0.1:8765"
_TIMEOUT = float(os.environ.get("AGENTCUT_BRIDGE_TIMEOUT") or 600)

_STARTED: subprocess.Popen | None = None
_STARTED_URL = ""
_STARTED_TOKEN = ""


def _contract() -> dict[str, Any]:
    """契约的离线读法：路由表来自 app 自己，工具表来自 MCP 自己，都不碰数据库。"""
    import asyncio

    from agentcut.http_api import create_app
    from agentcut.mcp_server import create_mcp

    probe = "agentcut-bridge-contract-" + "0" * 32
    app = create_app(DATA_DIR / "unused-by-bridge.sqlite3", probe)
    server = create_mcp("http://127.0.0.1:0", probe)
    return asyncio.run(agent_contract.manifest(app, server, base_url=""))


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _http(url: str, token: str, method: str, path: str, query=None, body=None) -> Any:
    full = url + path
    if query:
        pairs: list[tuple[str, str]] = []
        for key, value in query.items():
            if value is None:
                continue
            items = value if isinstance(value, (list, tuple)) else [value]
            pairs += [(key, str(item)) for item in items]
        full += "?" + urllib.parse.urlencode(pairs)
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(full, data=payload, method=method)
    request.add_header("authorization", f"Bearer {token}")
    if payload is not None:
        request.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            raw = response.read()
            ctype = response.headers.get("content-type", "")
    except urllib.error.HTTPError as failure:
        raw = failure.read()
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = repr(raw[:180])
            raise AgentError("engine_unreachable", f"引擎回了读不懂的话：{detail}") from failure
        error = envelope.get("error") or {}
        raise AgentError(
            str(error.get("code") or f"http_{failure.code}").lower(),
            str(error.get("message") or f"引擎以 {failure.code} 拒绝"),
        ) from failure
    except (urllib.error.URLError, OSError) as failure:
        raise AgentError("engine_unreachable", f"引擎没有回答（{url}）：{failure}") from failure
    if "json" not in ctype:
        return {"content_type": ctype, "base64": base64.b64encode(raw).decode("ascii")}
    return json.loads(raw.decode("utf-8"))


def _alive(url: str, token: str) -> bool:
    try:
        _http(url, token, "GET", "/v1/capabilities")
        return True
    except AgentError:
        return False


def _start_engine() -> tuple[str, str]:
    """没人应答时才自己拉一台：只杀自己拉起的那一个进程，绝不动别人的引擎。"""
    global _STARTED
    port = _free_port()
    command = [
        sys.executable, "-m", "agentcut", "api", "--port", str(port), "--json",
        "--data-dir", str(DATA_DIR), "--media-root", str(DATA_DIR),
        # 桥被强杀（TerminateProcess 不给 atexit 机会）时，引擎自己盯着父进程离开；
        # 只杀自己拉起的那一个 PID，绝不动桌面端那台。
        "--exit-with-parent", str(os.getpid()),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=env, cwd=str(PROJECT_ROOT),
    )
    global _STARTED_URL, _STARTED_TOKEN
    _STARTED = process
    atexit.register(_stop_engine)
    deadline = time.time() + 120
    while time.time() < deadline:
        line = process.stdout.readline() if process.stdout else ""
        if not line and process.poll() is not None:
            raise AgentError("engine_unreachable", f"引擎起不来（退出码 {process.returncode}）")
        if '"event": "ready"' in line:
            ready = json.loads(line.strip())
            token = ""
            written = Path(ready.get("token_file") or TOKEN_FILE)
            if written.exists():
                token = written.read_text(encoding="utf-8").strip()
            _STARTED_URL = str(ready["base_url"]).rstrip("/")
            _STARTED_TOKEN = token
            return _STARTED_URL, _STARTED_TOKEN
    raise AgentError("engine_unreachable", "引擎 120 秒内没有报 ready")


def _stop_engine() -> None:
    global _STARTED
    process = _STARTED
    _STARTED = None
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _engine() -> tuple[str, str]:
    """按引擎自己那套约定找人：AGENTCUT_API_URL + 令牌文件，都没有就自己拉一台。"""
    # 自己拉起来的那一台优先复用：不先问它，每一次调用都会再开一台引擎
    # （这一步真的漏过：一次门禁跑完，机器上留着 8 台没人管的引擎）。
    if _STARTED is not None and _STARTED.poll() is None and _alive(_STARTED_URL, _STARTED_TOKEN):
        return _STARTED_URL, _STARTED_TOKEN
    configured = os.environ.get("AGENTCUT_API_URL", "").rstrip("/")
    token = os.environ.get("AGENTCUT_TOKEN", "")
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if configured:
        if token and _alive(configured, token):
            return configured, token
        raise AgentError(
            "engine_unreachable",
            f"AGENTCUT_API_URL 指到 {configured}，但那台引擎没应答或令牌不对；"
            "把它起来或改掉这个环境变量再试。",
        )
    if token and _alive(DEFAULT_URL, token):
        return DEFAULT_URL, token
    return _start_engine()


def _make_handler(tool: str, params: dict) -> Any:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        # 派发规则只有一份主人：resolve() 按路由自己的签名分 path / query / body，
        # 所以 `dry_run` 这类查询参数不会被塞进 JSON 里悄悄变成一次真写。
        method, path, query, body = agent_contract.resolve(tool, args or {}, params)
        url, token = _engine()
        answer = _http(url, token, method, path, query=query, body=body)
        return answer if isinstance(answer, dict) else {"result": answer}

    return handler


def _build() -> tuple[list[dict[str, Any]], dict]:
    contract = _contract()
    params = {
        (row["method"], row["path"]): {
            "path": row.get("path_params") or [],
            "query": row.get("query_params") or [],
            "body": row.get("body_params") or [],
        }
        for row in contract["endpoints"]
    }
    tools = [{
        "name": "agentcut.status",
        "description": "桥与引擎的当前状态：连的是哪一台、它报什么版本、这台机器上有几个工程。",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "risk": "read",
        "endpoint": {"method": "GET", "path": "/v1/info"},
        "handler": handle_status,
    }]
    for row in contract["tools"]:
        if not row.get("endpoint"):
            # 少登记一条路由，宁可在这里就炸掉：静默少一只工具正是旧那份手写表的病。
            raise RuntimeError(f"工具 {row['name']} 在契约里没有路由，桥无法代理它")
        tools.append({
            "name": "agentcut." + row["name"],
            "description": row["description"] or row["name"],
            "input_schema": row["input_schema"],
            "risk": "read" if row["read_only"] else "write",
            "endpoint": row["endpoint"],
            "handler": _make_handler(row["name"], params),
        })
    return tools, params


def handle_status(args: dict[str, Any]) -> dict[str, Any]:
    """桥自己的状态：连的是哪台引擎、它报什么版本、这台机器上有几个工程。"""
    url, token = _engine()
    info = _http(url, token, "GET", "/v1/info")
    projects = _http(url, token, "GET", "/v1/projects", query={"limit": 1})
    return {
        "version": APP_VERSION,
        "engine": {
            "base_url": url,
            "app_version": info.get("app_version"),
            "media_ready": info.get("media_ready"),
            "render_ready": info.get("render_ready"),
        },
        "bridge": {
            "tools": len(TOOLS),
            "started_by_bridge": _STARTED is not None,
            "engine_pid": _STARTED.pid if _STARTED else None,
        },
        "total_projects": len(projects.get("projects") or []),
    }


TOOLS, _PARAMS = _build()


CONTRACT = {
    "tools": len(TOOLS),
    "recipes": [row["id"] for row in agent_contract.recipes()],
}
