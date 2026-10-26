"""1.307：两条门面与那台桥，说的是同一份契约——而且一条真片子要经桥剪得出来。

这一档存在的理由不是「又多一只工具」，而是把三条路收成一条：

* **契约只有一个来源**：`/v1/agent/manifest` 交回的工具表就是 FastMCP 当场报的那一份，
  endpoint 表就是 FastAPI 自己的路由表；少一只工具、路径写错、方法对不上，都在这里红。
* **桥不许再手写**：`agent/tools.py` 的工具名单与 schema 必须与契约逐字相同——以前它手写
  六只、还绕过 HTTP 直开 SQLite，产品后来加的媒体/渲染/字幕/遮罩那几十只它一只都没有，
  那条路越用越像另一个产品。
* **两只门面对同一只工具必须发出同一个请求**：同一份参数，MCP 那一侧与桥这一侧落到引擎的
  method / path / query / body 逐项相同。派发错了（把 `dry_run` 塞进 body 那一类）当场暴露
  ——这是「统一接口」唯一说得通的证法。
* **一条真剪辑要经桥跑完**：建工程 → 导真素材 → 加轨加段 → 切开 → dry_run 不写库 →
  排队交付 → ffprobe 验长度。契约不是文档，跑不通就是假的。

跑法：空闲机器单跑 `uv run python tests/agent_contract_check.py`（要随包 ffmpeg 造夹具）。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from agentcut import agent_contract  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.mcp_server import create_mcp  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECOND = 70_560_000
TOKEN = "agentcontract" + "c" * 36


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def offline_manifest() -> dict[str, Any]:
    """不连引擎也能读到的那一份契约：路由表来自 app 自己，工具表来自 MCP 自己。"""
    with tempfile.TemporaryDirectory() as raw:
        app = create_app(Path(raw) / "offline.sqlite3", TOKEN)
        server = create_mcp("http://127.0.0.1:1", TOKEN)
        return asyncio.run(agent_contract.manifest(app, server, base_url="http://127.0.0.1:1"))


def contract_shape(contract: dict[str, Any]) -> None:
    routes = {(row["method"], row["path"]) for row in contract["endpoints"]}
    missing = [row["name"] for row in contract["tools"] if not row.get("endpoint")]
    assert not missing, f"{len(missing)} 只工具没有登记路由：{missing}"
    ghosts = [
        (row["name"], row["endpoint"]["method"], row["endpoint"]["path"])
        for row in contract["tools"]
        if (row["endpoint"]["method"], row["endpoint"]["path"]) not in routes
    ]
    assert not ghosts, f"契约里的路由在真实路由表里找不到：{ghosts}"
    names = {row["name"] for row in contract["tools"]}
    phantom = [
        (recipe["id"], step["tool"])
        for recipe in contract["recipes"]
        for step in recipe["steps"]
        if step["tool"] not in names
    ]
    assert not phantom, f"配方引用了不存在的工具：{phantom}"
    reads = sum(1 for row in contract["tools"] if row["read_only"])
    print(
        f"   契约：{len(contract['tools'])} 只工具（只读 {reads} / 可写 {len(names) - reads}）、"
        f"{len(contract['endpoints'])} 条路由、{len(contract['recipes'])} 条配方，逐条对得上"
    )


def served_manifest_matches_offline() -> None:
    """HTTP 那一条门交回的，与离线读到的，必须是同一份。"""
    with tempfile.TemporaryDirectory() as raw:
        app = create_app(Path(raw) / "served.sqlite3", TOKEN)
        with TestClient(app, base_url="http://127.0.0.1",
                        headers={"Authorization": f"Bearer {TOKEN}"}) as client:
            answer = client.get("/v1/agent/manifest")
            assert answer.status_code == 200, answer.text
            served = answer.json()
    offline = offline_manifest()
    assert served["tools"] == offline["tools"], "两只门面读到的工具表不一样"
    assert served["endpoints"] == offline["endpoints"], "两只门面读到的路由表不一样"
    assert served["recipes"] == offline["recipes"], "两只门面读到的配方不一样"
    assert served["capabilities"]["features"]["agent_manifest"] is True
    print("   /v1/agent/manifest 与离线契约逐字相同（工具、路由、配方三张表）")


def load_bridge(contract: dict[str, Any]) -> Any:
    """桥的工具名单必须就是契约那一份，不许多写也不许漏写。"""
    with tempfile.TemporaryDirectory() as raw:
        os.environ["AGENTCUT_DATA_DIR"] = str(Path(raw) / "bridge-import")
        try:
            sys.path.insert(0, str(ROOT / "agent"))
            import tools as bridge  # noqa: PLC0415
        finally:
            os.environ.pop("AGENTCUT_DATA_DIR", None)
    expected = {"agentcut.status"} | {f"agentcut.{row['name']}" for row in contract["tools"]}
    got = {row["name"] for row in bridge.TOOLS}
    assert got == expected, f"桥与契约的工具集合不一样：{sorted(got ^ expected)}"
    by_name = {row["name"]: row for row in contract["tools"]}
    for row in bridge.TOOLS:
        bare = row["name"].removeprefix("agentcut.")
        if bare == "status":
            continue
        source = by_name[bare]
        assert row["input_schema"] == source["input_schema"], f"{bare} 的参数表与契约不一样"
        assert row["risk"] == ("read" if source["read_only"] else "write"), (
            f"{bare} 的读写性与契约不一样"
        )
        assert row["endpoint"] == source["endpoint"], f"{bare} 的路由与契约不一样"
    print(f"   agent/ 那台桥交回 {len(bridge.TOOLS)} 只工具，schema 与端点与契约逐字相同")
    return bridge


def example(schema: dict[str, Any], defs: dict[str, Any], depth: int = 0) -> Any:
    """按 schema 造一份形状对的样例：两只门面拿同一份，发出的请求就必须是同一个。"""
    if depth > 4:
        return None
    spec = dict(schema or {})
    seen_refs = 0
    while "$ref" in spec and seen_refs < 6:
        seen_refs += 1
        spec = dict(defs.get(spec["$ref"].rsplit("/", 1)[-1], {}))
    if "const" in spec:
        return spec["const"]
    for key in ("anyOf", "oneOf"):
        branches = spec.get(key) or []
        if branches:
            pick = next((row for row in branches if (row or {}).get("type") != "null"), branches[0])
            spec = {**pick}
            break
    enum = spec.get("enum") or spec.get("examples") or []
    if enum:
        return enum[0]
    kind = spec.get("type")
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), "string")
    if kind == "object" or "properties" in spec:
        out: dict[str, Any] = {}
        for name, child in (spec.get("properties") or {}).items():
            out[name] = example(child, defs, depth + 1)
        for name in spec.get("required") or []:
            out.setdefault(name, "sample")
        return out
    if kind == "array":
        return [example(spec.get("items") or {}, defs, depth + 1)]
    if kind == "null":
        return None
    return {"string": "sample", "integer": 1, "number": 1.0, "boolean": True}.get(kind, "sample")


def args_for(row: dict[str, Any]) -> dict[str, Any]:
    schema = dict(row["input_schema"] or {})
    return example(schema, schema.get("$defs") or {})


class Recorder:
    """一台只记账的「引擎」：留下两侧各自发出的请求用来比对，不实现任何业务。"""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def capture(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else None
                except (UnicodeDecodeError, json.JSONDecodeError):
                    body = raw.decode("utf-8", "replace")
                split = urllib.parse.urlsplit(self.path)
                outer.seen.append({
                    "method": self.command,
                    "path": split.path,
                    "query": dict(urllib.parse.parse_qsl(split.query)),
                    "body": body,
                })

            def respond(self) -> None:
                payload = b'{"ok": true}'
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:  # noqa: N802
                self.capture()
                self.respond()

            def do_POST(self) -> None:  # noqa: N802
                self.capture()
                self.respond()

            def log_message(self, *_a: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> str:
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def last(self) -> dict[str, Any]:
        return self.seen[-1] if self.seen else {}


def normalise(request: dict[str, Any]) -> dict[str, Any]:
    body = request.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            pass
    return {
        "method": request.get("method"),
        "path": request.get("path"),
        "query": {key: str(value) for key, value in (request.get("query") or {}).items()},
        "body": body,
    }


def dispatch_alignment(contract: dict[str, Any]) -> int:
    """静态对齐：每只工具经 resolve() 派出去的请求，必须落在它登记的那条路由的形状里。

    查的是三件会真出事的事：路径参数没填满、schema 上的参数没人接、查询参数被塞进 body
    （`dry_run` 那一类一旦放错，一次「试跑」就变成真写）。
    """
    routes = {(row["method"], row["path"]): row for row in contract["endpoints"]}
    checked = 0
    for row in contract["tools"]:
        name = row["name"]
        endpoint = row["endpoint"]
        key = (endpoint["method"], endpoint["path"])
        route = routes[key]
        properties = row["input_schema"].get("properties") or {}
        args: dict[str, Any] = {}
        for placeholder in route["path_params"]:
            args[placeholder] = "abc123"
        for prop in properties:
            args.setdefault(prop, {} if prop in ("request", "project", "document") else "abc123")
        method, path, query, body = agent_contract.resolve(name, args, {key: {
            "path": route["path_params"], "query": route["query_params"],
            "body": route["body_params"],
        }})
        assert method == endpoint["method"], f"{name}：方法变了"
        assert "{" not in path, f"{name}：路径参数没填满 {path}"
        unknown = [item for item in query if item not in route["query_params"]]
        expected = route["query_params"]
        assert not unknown, f"{name}：查询参数 {unknown} 不在这条路由认识的 {expected} 里"
        taken = set(route["path_params"]) | set(query)
        if route["body_params"]:
            taken |= set(route["body_params"])
            if "request" in properties:
                assert body is not None, f"{name}：这条路由要 body，派出去的却是空的"
        else:
            assert body is None, f"{name}：这条路由没有 body，却派出了 {body}"
        flattened = {
            prop for prop, spec in properties.items()
            if not route["body_params"]
            and ((spec or {}).get("type") == "object" or "$ref" in (spec or {}))
        }
        dropped = [prop for prop in properties if prop not in taken | flattened]
        assert not dropped, f"{name}：参数 {dropped} 没被派发接走"
        checked += 1
    return checked


def mcp_json(answer: Any) -> Any:
    """把 MCP 那一侧的返回摊成普通 JSON：新版 FastMCP 交回 (内容块, structuredContent)。"""
    if isinstance(answer, tuple) and len(answer) == 2:
        content, structured = answer
        if structured is not None:
            return structured
        answer = content
    if isinstance(answer, (list, tuple)):
        blocks = []
        for block in answer:
            raw = getattr(block, "text", None)
            blocks.append(json.loads(raw) if raw else block)
        return blocks[0] if len(blocks) == 1 else blocks
    return answer


def refusal_code(text: str) -> str:
    """从两侧的拒绝话里取出那个 code：MCP 交回的是引擎那份 JSON，桥交回的是 AgentError.code。"""
    try:
        return str(json.loads(text).get("code", "")).upper()
    except (ValueError, TypeError):
        pass
    found = re.search(r'"code"\s*:\s*"([A-Z0-9_]+)"', text)
    if found:
        return found.group(1)
    plain = re.fullmatch(r"[A-Za-z0-9_]+", text.strip())
    return plain.group(0).upper() if plain else ""


def live_double_door(bridge: Any, base_url: str, data_dir: Path) -> int:
    """真调用对照：同一份参数，MCP 与桥在真引擎上必须拿到同一份答案。"""
    server = create_mcp(base_url, TOKEN)
    handlers = {
        row["name"].removeprefix("agentcut."): row["handler"]
        for row in bridge.TOOLS if row["name"] != "agentcut.status"
    }
    clip = data_dir / "double-door.mp4"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i",
         "testsrc2=s=320x180:r=30:d=2", str(clip)], capture_output=True
    )
    cases: list[tuple[str, dict[str, Any]]] = [
        ("editor_capabilities", {}),
        ("editor_info", {}),
        ("render_presets_read", {}),
        ("media_config", {}),
        ("project_list", {"limit": 20}),
    ]
    agreed = 0
    for name, args in cases:
        mcp_answer = mcp_json(asyncio.run(server.call_tool(name, args)))
        bridge_answer = handlers[name](args)
        assert json.dumps(mcp_answer, sort_keys=True, default=str) == json.dumps(
            bridge_answer, sort_keys=True, default=str
        ), f"{name}：两只门面答案不一样"
        agreed += 1

    # ids_request 每次发的是新号，比不了全文——比的是「两只门面都按 count 发到同一条路上」。
    mcp_ids = mcp_json(asyncio.run(server.call_tool("ids_request", {"count": 4})))
    bridge_ids = handlers["ids_request"]({"count": 4})
    assert len(mcp_ids["ids"]) == len(bridge_ids["ids"]) == 4, (mcp_ids, bridge_ids)
    assert len(set(mcp_ids["ids"]) & set(bridge_ids["ids"])) == 0, "两只门面发出了同一批号"
    agreed += 1

    created = handlers["project_create"]({"request": {
        "request_id": "double-door", "name": "对照用",
        "settings": {"width": 320, "height": 180,
                     "frame_rate": {"numerator": 30, "denominator": 1}}}})
    pid = created["project"]["id"]
    same = mcp_json(asyncio.run(server.call_tool("project_get", {"project_id": pid})))
    assert json.dumps(same, sort_keys=True, default=str) == json.dumps(
        handlers["project_get"]({"project_id": pid}), sort_keys=True, default=str
    ), "project_get：两只门面读到的工程不一样"
    agreed += 1

    # 拒绝也要两只门面对得上：同一份假参数，两边必须以同一个 code 说不。
    for name, args in [
        ("project_get", {"project_id": "nope"}),
        ("project_history", {"project_id": "nope"}),
        ("render_plan", {"project_id": "nope", "preset_id": "mp4-1080p"}),
        ("captions_export", {"project_id": "nope", "track_id": "nope"}),
        ("timeline_edit", {"project_id": "nope", "request": {
            "request_id": "x", "expected_revision": 1,
            "commands": [{"op": "track.add", "track": {"id": "v", "kind": "video",
                                                       "name": "画面"}}]}}),
    ]:
        try:
            asyncio.run(server.call_tool(name, args))
            fail(f"{name}：MCP 那侧对不存在的工程居然没拒绝")
        except Exception as error:  # noqa: BLE001
            mcp_code = refusal_code(str(error))
        try:
            handlers[name](args)
            fail(f"{name}：桥那侧对不存在的工程居然没拒绝")
        except Exception as error:  # noqa: BLE001
            bridge_code = refusal_code(str(getattr(error, "code", error)))
        assert mcp_code and bridge_code, f"{name}：有一侧没报出 code"
        assert mcp_code == bridge_code, f"{name}：MCP 说 {mcp_code}，桥说 {bridge_code}"
        agreed += 1
    return agreed


def start_engine(data_dir: Path) -> tuple[subprocess.Popen, str]:
    command = [
        sys.executable, "-m", "agentcut", "api", "--port", "0", "--json",
        "--data-dir", str(data_dir), "--cache-dir", str(data_dir / "cache"),
        "--output-dir", str(data_dir / "out"), "--media-root", str(data_dir),
        "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["AGENTCUT_TOKEN"] = TOKEN
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env=env, cwd=str(ROOT),
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        line = process.stdout.readline() if process.stdout else ""
        if not line and process.poll() is not None:
            fail(f"引擎没起来（退出码 {process.returncode}）：{line[:200]}")
        if '"event": "ready"' in line:
            ready = json.loads(line.strip())
            return process, str(ready["base_url"])
    fail("引擎 120 秒内没有报 ready")
    raise SystemExit(1)


def real_edit_through_bridge(bridge: Any, data_dir: Path) -> None:
    """一条真片子经桥剪出来：契约不是文档，跑不通就是假的。"""
    call = {row["name"]: row["handler"] for row in bridge.TOOLS}

    def tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
        answer = call["agentcut." + name](args)
        assert isinstance(answer, dict), f"{name} 回了非 JSON：{type(answer)}"
        return answer

    clip = data_dir / "bridge-clip.mp4"
    ran = subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-nostdin", "-f", "lavfi",
         "-i", "testsrc2=s=320x180:r=30:d=4", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(clip)],
        capture_output=True,
    )
    if ran.returncode != 0:
        fail("造不出桥用的夹具：" + ran.stderr[-300:].decode("utf-8", "replace"))

    made = tool("project_create", {"request": {
        "request_id": "bridge-project", "name": "桥剪的一条",
        "settings": {"width": 320, "height": 180,
                     "frame_rate": {"numerator": 30, "denominator": 1}}}})
    pid = made["project"]["id"]
    revision = made["project"]["revision"]
    ids = tool("ids_request", {"count": 6})["ids"]
    probe = tool("media_import", {"path": str(clip)})
    tool("timeline_edit", {"project_id": pid, "request": {
        "request_id": "bridge-seed", "expected_revision": revision,
        "commands": [
            {"op": "track.add", "track": {"id": ids[0], "kind": "video", "name": "画面"}},
            {"op": "asset.import", "asset_id": ids[1], "label": clip.name,
             "probe_id": probe["id"], "verified": probe["verified"]},
            {"op": "clip.add", "clip": {"id": ids[2], "asset_id": ids[1], "track_id": ids[0],
                                        "position_ticks": 0, "duration_ticks": 4 * SECOND}},
        ]}})
    revision = tool("project_get", {"project_id": pid})["revision"]
    split = tool("timeline_edit", {"project_id": pid, "request": {
        "request_id": "bridge-split", "expected_revision": revision,
        "commands": [{"op": "clip.split", "clip_id": ids[2], "at_ticks": 2 * SECOND,
                                 "right_clip_id": ids[3]}]}})
    clips = split["project"]["clips"]
    assert len([row for row in clips.values() if row["track_id"] == ids[0]]) == 2, clips
    revision = split["project"]["revision"]
    dry = tool("timeline_edit", {"project_id": pid, "request": {
        "request_id": "bridge-dry", "expected_revision": revision, "dry_run": True,
        "commands": [{"op": "clip.remove", "clip_id": sorted(clips)[-1]}]}})
    after = tool("project_get", {"project_id": pid})
    assert after["revision"] == revision, "dry_run 经桥居然写了库"
    assert len(dry["project"]["clips"]) == len(after["clips"]) - 1, (
        "dry_run 交回的那一份应当比库里少一段（少的正是刚去掉的那一段）"
    )

    presets = tool("render_presets_read", {})["presets"]
    preset = next(row for row in presets if row["container"] == "mp4")
    queued = tool("render_start", {"project_id": pid, "request": {
        "request_id": "bridge-render", "expected_revision": revision,
        "preset_id": preset["id"], "filename": "bridge.mp4"}})
    job_id = queued["job"]["id"]
    deadline = time.time() + 420
    job: dict[str, Any] = {}
    while time.time() < deadline:
        job = tool("job_status", {"job_id": job_id})["job"]
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.5)
    assert job.get("status") == "succeeded", json.dumps(job, ensure_ascii=False)[:400]
    out = Path(job["output_path"])
    assert out.exists(), f"桥交付说成功了，文件却不在：{out}"
    meta = json.loads(subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=codec_type", "-of", "json", str(out)],
        capture_output=True).stdout.decode("utf-8"))
    seconds = float(meta["format"]["duration"])
    kinds = sorted(stream["codec_type"] for stream in meta["streams"])
    assert 3.4 < seconds < 4.6, f"桥交付的片子长度不对：{seconds} 秒"
    assert kinds == ["audio", "video"], kinds
    print(
        f"   经桥跑完一条真剪辑：建工程→导素材→加轨加段→2 秒处切开→dry_run 不写库→排队交付，"
        f"出片 {seconds:.2f} 秒（{'+'.join(kinds)}）"
    )


def process_alive(pid: int) -> bool:
    """问操作系统：这个 PID 还在不在（Windows 上不能用 os.kill(pid, 0) 那套）。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def hub_door(contract: dict[str, Any]) -> int:
    """第三道门：`agent/server.py` 那台本机 Agent API 桥（别的 agent 就是从这里调进来的）。

    桥交回的工具名单必须与契约同名同风险；一次真建工程与一次真拒绝都要走通——
    「agent 直接调用 agent 完成剪辑」这句话，到这里才有凭据。
    """
    import socket
    import urllib.error
    import urllib.request

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    with tempfile.TemporaryDirectory(prefix="agentcut-hub-") as raw:
        data = Path(raw)
        env = dict(os.environ)
        env.update({
            "AGENT_PORT": str(port),
            "AGENTCUT_DATA_DIR": str(data / "engine"),
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONIOENCODING": "utf-8",
            "AGENTCUT_FFMPEG": str(FFMPEG),
            "AGENTCUT_FFPROBE": str(FFPROBE),
        })
        env.pop("AGENTCUT_API_URL", None)
        env.pop("AGENTCUT_TOKEN", None)
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "agent/server.py")], cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace",
        )

        def call(path: str, body=None, token=None) -> dict[str, Any]:
            payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=payload,
                                             method="POST" if payload else "GET")
            if payload:
                request.add_header("content-type", "application/json")
                request.add_header("x-agentcut-token", token or "")
            try:
                with urllib.request.urlopen(request, timeout=240) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                return json.loads(error.read().decode("utf-8"))

        try:
            manifest: dict[str, Any] = {}
            deadline = time.time() + 90
            while time.time() < deadline and not manifest:
                time.sleep(0.5)
                try:
                    manifest = call("/api/agent/manifest").get("data") or {}
                except (urllib.error.URLError, OSError):
                    continue
            assert manifest, "桥没起来：" + str(process.stdout.readline() if process.stdout else "")
            rows = {row["name"].removeprefix("agentcut."): row for row in manifest["tools"]}
            assert "status" in rows
            engine_rows = {row["name"]: row for row in contract["tools"]}
            shorted = sorted(set(engine_rows) - set(rows))
            assert not shorted, f"桥少交了工具：{shorted}"
            for name, source in engine_rows.items():
                assert rows[name]["risk"] == ("read" if source["read_only"] else "write"), (
                    f"{name}：桥报的风险性与契约不一样"
                )
                assert rows[name]["input_schema"] == source["input_schema"], (
                    f"{name}：桥交回的参数表与契约不一样"
                )
            token = Path(manifest["api"]["token_file"]).read_text(encoding="utf-8").strip()
            made = call("/api/agent/tool", {
                "tool": "agentcut.project_create",
                "input": {"request": {"request_id": "hub-door", "name": "第三道门"}},
            }, token)
            assert made.get("ok") is True, json.dumps(made, ensure_ascii=False)[:300]
            pid = made["data"]["project"]["id"]
            refused = call("/api/agent/tool", {"tool": "agentcut.project_get",
                                              "input": {"project_id": "nope"}}, token)
            assert refused.get("ok") is False and refused["error"]["code"] == "not_found", refused
            read = call("/api/agent/tool", {"tool": "agentcut.project_get",
                                           "input": {"project_id": pid}}, token)
            assert read.get("ok") is True and read["data"]["id"] == pid, str(read)[:300]
            status = call("/api/agent/tool", {"tool": "agentcut.status", "input": {}}, token)
            assert status["data"]["bridge"]["started_by_bridge"] is True, str(status)[:300]
            engine_pid = int(status["data"]["bridge"]["engine_pid"])
            assert engine_pid > 0, str(status)[:300]
            # 一台桥只该配一台引擎：抓「每次调用都再拉起一台」（真漏过，一次跑完留 8 台）。
            for _ in range(3):
                call("/api/agent/tool", {"tool": "agentcut.project_list", "input": {}}, token)
            again = call("/api/agent/tool", {"tool": "agentcut.status", "input": {}}, token)
            second = int(again["data"]["bridge"]["engine_pid"])
            assert second == engine_pid, f"桥每次调用都新拉起一台引擎：{engine_pid} → {second}"
            # 强杀桥（`TerminateProcess` 不给 atexit 任何机会）之后，引擎不该留在机器上：
            # 本轮实测一次门禁就在这台机器上留下 24 台没人管的引擎。
            subprocess.run(["taskkill", "/PID", str(process.pid), "/F"], capture_output=True)
            deadline = time.time() + 20
            while time.time() < deadline and process_alive(engine_pid):
                time.sleep(0.5)
            assert not process_alive(engine_pid), f"桥被强杀后引擎 {engine_pid} 还活着"
            return len(manifest["tools"])
        finally:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()


async def mcp_primitives(env: dict[str, str], errlog) -> tuple[list[str], dict[str, Any], str]:
    """真 stdio 会话那一侧：prompts 与 `agentcut://manifest` 资源都要当场读到。"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "agentcut", "mcp"],
                                   env=env, cwd=str(ROOT))
    async with stdio_client(params, errlog=errlog) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            prompts = sorted(row.name for row in (await session.list_prompts()).prompts)
            first = await session.get_prompt("recipe_cut_from_media", {})
            recipe_text = str(getattr(first.messages[0].content, "text", ""))
            resource = await session.read_resource("agentcut://manifest")
            return prompts, json.loads(resource.contents[0].text), recipe_text


def main() -> None:
    if not FFMPEG.exists() or not FFPROBE.exists():
        fail(f"没有随包 ffmpeg/ffprobe：{FFMPEG} / {FFPROBE}")
    contract = offline_manifest()
    contract_shape(contract)
    served_manifest_matches_offline()
    bridge = load_bridge(contract)
    aligned = dispatch_alignment(contract)
    assert aligned == len(contract["tools"]), f"只对齐了 {aligned}/{len(contract['tools'])} 只"
    print(f"   派发对齐：{aligned} 只工具经 resolve() 都落在登记的那条路由上")
    hub_tools = hub_door(contract)
    print(f"   第三道门（agent/server.py 桥）交回 {hub_tools} 只工具，建过工程也按 code 拒过")
    with tempfile.TemporaryDirectory(prefix="agentcut-agent-contract-") as raw:
        data_dir = Path(raw)
        (data_dir / "out").mkdir()
        os.environ["AGENTCUT_FFMPEG"] = str(FFMPEG)
        os.environ["AGENTCUT_FFPROBE"] = str(FFPROBE)
        process, base_url = start_engine(data_dir)
        try:
            os.environ["AGENTCUT_API_URL"] = base_url
            os.environ["AGENTCUT_TOKEN"] = TOKEN
            doors = live_double_door(bridge, base_url, data_dir)
            print(f"   同一份参数两只门面答案一致：{doors} 组真调用对照")
            env = {
                **os.environ, "PYTHONPATH": str(ROOT / "src"),
                "AGENTCUT_API_URL": base_url, "AGENTCUT_TOKEN": TOKEN,
                "PYTHONIOENCODING": "utf-8",
            }
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
                prompts, payload, recipe_text = asyncio.run(mcp_primitives(env, errlog))
            want = {"recipe_cut_from_media", "recipe_speech_to_captions",
                    "recipe_imitate_imported_edit"}
            assert want <= set(prompts), f"MCP 的 prompts 少了剪辑配方：{prompts}"
            served_names = [row["name"] for row in payload["tools"]]
            contract_names = [row["name"] for row in contract["tools"]]
            assert served_names == contract_names, "MCP 资源读到的工具表与契约不一样"
            assert payload["endpoints"] == contract["endpoints"], (
                "MCP 资源读到的路由表与契约不一样"
            )
            assert "timeline_edit" in recipe_text and "1. " in recipe_text, recipe_text[:200]
            print(f"   MCP 原语：{len(prompts)} 只 prompt，agentcut://manifest 与契约同一份")
            real_edit_through_bridge(bridge, data_dir)
        finally:
            process.kill()
            for key in ("AGENTCUT_API_URL", "AGENTCUT_TOKEN"):
                os.environ.pop(key, None)
    print("agent_contract_check: all green")


main()
