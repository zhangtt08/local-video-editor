#!/usr/bin/env python3
"""Agent API server（标准实现，Python 项目用，本机守卫版）。项目只需在同目录提供 tools.py 并导出 TOOLS / PROJECT。

契约见 personal-agent-hub/docs/AGENT_API_STANDARD.md。只用标准库，只监听 127.0.0.1。

守卫（与 node 模板 local-guard.mjs 同一套判据，标准第 1~5 条）：
  1) 只绑 127.0.0.1，绑非回环直接拒绝启动；
  2) Host 逐字等于 127.0.0.1:<port> / localhost:<port> / [::1]:<port>（挡 DNS rebinding）；
  3) Origin/Referer 只要出现就必须落在本机回环上；
  4) 非 GET/HEAD 必须带令牌，请求头 x-<项目id>-token（或 Authorization: Bearer），
     令牌自动生成落盘 0600（AGENT_API_TOKEN 环境变量优先；AGENT_API_DATA_DIR 改落盘目录）；
  5) 任何响应都不发 Access-Control-Allow-Origin: *。
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import stat
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from errors import AgentError  # noqa: E402  与 tools.py 共用同一个类对象

START = time.time()

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
TOKEN_FILE_NAME = "agent-api.token"
MIN_TOKEN_LENGTH = 32

# 调用方修得了的失败不是 500：5xx 会让 Agent 以为"服务坏了"而反复重试。
CALLER_FIXABLE = {"bad_json", "too_large", "bad_input", "unknown_tool", "not_found"}


def app_data_dir(project_id: str) -> Path:
    override = os.environ.get("AGENT_API_DATA_DIR", "").strip()
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA") or os.environ.get("AppData")
    if appdata:
        return Path(appdata) / project_id
    return Path.home() / ".agent-api" / project_id


def token_file(project_id: str) -> Path:
    return app_data_dir(project_id) / TOKEN_FILE_NAME


def _read_token(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
        return value if len(value) >= MIN_TOKEN_LENGTH else ""
    except OSError:
        return ""


def read_agent_token(project_id: str) -> str:
    from_env = os.environ.get("AGENT_API_TOKEN", "").strip()
    if from_env:
        return from_env
    return _read_token(token_file(project_id))


def ensure_agent_token(project_id: str) -> tuple[str, str | None]:
    """返回 (token, 落盘文件)。取不到就抛 —— 服务宁可不起，也不能没有令牌地开写接口。"""
    from_env = os.environ.get("AGENT_API_TOKEN", "").strip()
    if from_env:
        return from_env, None
    path = token_file(project_id)
    existing = _read_token(path)
    if existing:
        return existing, str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(secret + "\n")
    except FileExistsError:
        adopted = _read_token(path)
        if adopted:
            return adopted, str(path)
        _write_existing(path, secret)
    except OSError as e:
        raise SystemExit(f"本机令牌写不进 {path}：{e}。可指定 AGENT_API_TOKEN 或把 AGENT_API_DATA_DIR 指到可写目录") from e
    if os.name == "posix":
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    written = _read_token(path)
    if not written:
        raise SystemExit(f"本机令牌写完读不回（{path}）：拒绝以「没有守卫」的状态提供服务")
    return written, str(path)


def _write_existing(path: Path, secret: str) -> None:
    path.write_text(secret + "\n", encoding="utf-8")
    if os.name == "posix":
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def token_matches(provided: str | None, expected: str) -> bool:
    """定长时间比较：两侧都哈希成固定长度，连长度本身都不泄露。"""
    if not expected:
        return False
    a = hashlib.sha256((provided or "").encode("utf-8")).digest()
    b = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(a, b)


def _split_hostport(value: str | None) -> tuple[str, int | None]:
    s = (value or "").strip()
    s = s.split("://", 1)[-1].split("/", 1)[0]
    if s.startswith("["):
        end = s.find("]")
        if end < 0:
            return s, None
        host, rest = s[: end + 1], s[end + 1 :]
        m = rest.removeprefix(":")
        return host, int(m) if m.isdigit() else None
    if ":" in s:
        host, _, port = s.rpartition(":")
        return host, int(port) if port.isdigit() else None
    return s, None


def host_allowed(header_value: str | None, port: int) -> bool:
    host, p = _split_hostport(header_value)
    if p != port:
        return False
    return host.strip("[]").lower() in LOOPBACK_HOSTS


def origin_allowed(origin: str | None) -> bool:
    """没带 = 放行（curl/MCP 桥都不带）；带了就必须是本机回环。
    绝不拿 Origin 与请求自带的 Host 比 —— 那正是 DNS rebinding 会伪造的那一半。"""
    s = (origin or "").strip()
    if not s:
        return True
    if s in ("null", "file://"):
        return False
    parts = urlsplit(s)
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        return False
    port = parts.port
    return port is None or port > 0


def load_tools() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    p = HERE / "tools.py"
    if not p.exists():
        raise SystemExit(f"missing {p}: 项目必须实现 agent/tools.py")
    spec = importlib.util.spec_from_file_location("agent_tools", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return getattr(mod, "PROJECT", {"name": "agent", "version": "0.0.0"}), list(getattr(mod, "TOOLS"))


def validate(schema: dict[str, Any] | None, data: Any) -> None:
    if not schema or schema.get("type") != "object":
        return
    obj = data if isinstance(data, dict) else {}
    missing = [k for k in schema.get("required", []) if obj.get(k) in (None, "")]
    if missing:
        raise AgentError("bad_input", "缺少必填参数：" + ", ".join(missing))
    if schema.get("additionalProperties") is False:
        props = schema.get("properties", {})
        unknown = [k for k in obj if k not in props]
        if unknown:
            raise AgentError("bad_input", f"未知参数：{', '.join(unknown)}；可用：{', '.join(props) or '无'}")


def guard_denied_body(verdict: dict[str, Any], token_header: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {"code": verdict["code"], "message": verdict["message"]},
        "guard": {"host": "127.0.0.1 only", "origin": "loopback only", "token_header": token_header, "mutating_methods_need_token": True},
    }


def check_guard(handler: BaseHTTPRequestHandler, port: int, token: str, token_header: str) -> dict[str, Any] | None:
    """返回 None = 放行；返回 dict = 拒绝理由（调用方必须先回它再 return）。"""
    if not host_allowed(handler.headers.get("Host"), port):
        return {"status": 403, "code": "HOST_NOT_ALLOWED",
                "message": f"Host 头不被允许：本机服务只接受 127.0.0.1:{port} / localhost:{port} / [::1]:{port}（挡 DNS rebinding）"}
    for name in ("Origin", "Referer"):
        value = handler.headers.get(name)
        if value and not origin_allowed(value):
            return {"status": 403, "code": f"{name.upper()}_NOT_ALLOWED",
                    "message": f"{name} 不是本机来源：{value[:160]}。本接口只服务本机回环请求，不从网页里直接调用"}
    method = (handler.command or "").upper()
    if method in ("GET", "HEAD"):
        return None
    if not token:
        return {"status": 500, "code": "TOKEN_UNAVAILABLE",
                "message": "服务端没能取到本机令牌，写接口按 fail-closed 拒绝。检查 AGENT_API_TOKEN 或令牌落盘目录"}
    provided = handler.headers.get(token_header, "").strip()
    if not provided:
        auth = handler.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
    if not token_matches(provided, token):
        return {"status": 401, "code": "TOKEN_REQUIRED",
                "message": f"缺少或错误的本机令牌：请带请求头 {token_header}: <令牌>（见 manifest api.token_file）"}
    return None


def serve(project: dict[str, Any], tools: list[dict[str, Any]], port: int = 8790, host: str = "127.0.0.1") -> None:
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(f"只允许监听本机回环（127.0.0.1），拒绝绑定到 {host or '(空)'}")
    project_id = str(project.get("id") or project.get("projectId") or "agent")
    token_header = f"x-{project_id}-token"
    token, token_path = ensure_agent_token(project_id)
    by_name = {t["name"]: t for t in tools}
    descriptor = lambda t: {"name": t["name"], "description": t["description"], "input_schema": t.get("input_schema", {}), "risk": t.get("risk", "read")}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(raw)))
            self.send_header("cache-control", "no-store")
            self.send_header("x-content-type-options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def _guard_or_send(self) -> bool:
            bound_port = self.server.server_address[1]
            verdict = check_guard(self, bound_port, token, token_header)
            if verdict is not None:
                self._send(verdict["status"], guard_denied_body(verdict, token_header))
                return False
            return True

        def do_OPTIONS(self) -> None:  # noqa: N802
            if not self._guard_or_send():
                return
            # 能走到这里说明带了合法令牌且来源是本机回环；仍回 405 且不发任何 Access-Control-*：
            # 本服务不做跨源放行，跨源页面连预检都过不了。
            self._send(405, {"ok": False, "error": {"code": "no_cors", "message": "本机服务不做跨源放行；请从本机回环地址带令牌直接调用"}})

        def do_GET(self) -> None:  # noqa: N802
            if not self._guard_or_send():
                return
            route = self.path.split("?")[0].rstrip("/") or "/"
            if route == "/api/health":
                self._send(200, {"ok": True, "data": {"project": project["name"], "version": project.get("version", "0.0.0"), "agent_api": 1, "tools": len(tools), "uptime_ms": int((time.time() - START) * 1000), "guard": {"host": f"127.0.0.1:{port} / localhost:{port} / [::1]:{port}", "origin": "loopback only", "token_required_for": "非 GET/HEAD", "token_file": token_path or "env", "wildcard_cors": False}}})
            elif route == "/api/agent/tools":
                self._send(200, {"ok": True, "data": [descriptor(t) for t in tools]})
            elif route == "/api/agent/manifest":
                self._send(200, {"ok": True, "data": {"project": project["name"], "version": project.get("version", "0.0.0"), "description": project.get("summary", ""), "base_url": f"http://{host}:{self.server.server_address[1]}", "tools": [descriptor(t) for t in tools], "api": {"token_header": token_header, "token_env": "AGENT_API_TOKEN", "token_file": token_path}}})
            else:
                self._send(404, {"ok": False, "error": {"code": "not_found", "message": f"未知路径 {route}", "endpoints": ["/api/health", "/api/agent/tools", "/api/agent/manifest", "POST /api/agent/tool"]}})

        def do_POST(self) -> None:  # noqa: N802
            if not self._guard_or_send():
                return
            route = self.path.split("?")[0].rstrip("/") or "/"
            if route != "/api/agent/tool":
                self._send(404, {"ok": False, "error": {"code": "not_found", "message": f"未知路径 {route}"}})
                return
            try:
                length = int(self.headers.get("content-length") or 0)
                if length > 8 * 1024 * 1024:
                    raise AgentError("too_large", "请求体超过 8MB")
                body = json.loads(self.rfile.read(length) or b"{}")
                tool = by_name.get(body.get("tool"))
                if tool is None:
                    self._send(400, {"ok": False, "error": {"code": "unknown_tool", "message": f"未注册的工具：{body.get('tool')}", "available": list(by_name)}})
                    return
                t0 = time.time()
                validate(tool.get("input_schema"), body.get("input"))
                fn: Callable[..., Any] = tool["handler"]
                data = fn(body.get("input") or {})
                self._send(200, {"ok": True, "tool": tool["name"], "ms": int((time.time() - t0) * 1000), "data": data})
            except AgentError as e:
                status = 400 if e.code in CALLER_FIXABLE else 500
                self._send(status, {"ok": False, "error": {"code": e.code, "message": str(e)}})
            except json.JSONDecodeError:
                self._send(400, {"ok": False, "error": {"code": "bad_json", "message": "请求体不是合法 JSON"}})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"ok": False, "error": {"code": "handler_failed", "message": f"{type(e).__name__}: {e}"}})

        def log_message(self, *_a: Any) -> None:
            pass

    bound = None
    for p in range(port, port + 12):
        try:
            httpd = ThreadingHTTPServer((host, p), Handler)
            bound = p
            break
        except OSError:
            continue
    if bound is None:
        raise SystemExit(f"端口 {port}~{port+11} 全部被占用")
    (HERE / ".endpoint").write_text(f"http://{host}:{bound}\n", encoding="utf-8")
    # 控制台可能是 GBK，中文会乱码甚至抛 UnicodeEncodeError，因此启动行只用 ASCII。
    print(f"[agent] {project['name']} v{project.get('version','0.0.0')} -> http://{host}:{bound} ({len(tools)} tools)", flush=True)
    print(f"[agent] local guard: Host 127.0.0.1/localhost/[::1]:{bound} only, non-GET needs {token_header}" + (f" (token file {token_path})" if token_path else " (token from env)"), flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    proj, tl = load_tools()
    serve(proj, tl, int(os.environ.get("AGENT_PORT") or proj.get("port") or 8790))
