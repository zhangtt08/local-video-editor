#!/usr/bin/env python3
"""agent/ 那一层标准 Agent API：真起服务、真发请求，六只工具逐条走到引擎。

这一档存在的原因：`agent/tools.py` 原先调的是 `store.create_project` /
`store.apply_batch` / `p.id`（`list_projects` 交回的是 dict），一个字都没跑通过；
它的 `capabilities` 还把转场名抄成了 `fade_black` / `wipe_left`——引擎那张表里叫
`dip_black` / `wipe_from_left`，照着这份名单写命令的 Agent 一定被拒。

所以这里断的不是「模块能 import」，而是**每一次 HTTP 往返都落到真的引擎上**，
并且写的是这份临时库，不是用户真实的 `data/agentcut.sqlite3`。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import scratch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import APP_VERSION, SCHEMA_VERSION, TIMEBASE  # noqa: E402
from agentcut.contracts import capabilities as engine_capabilities  # noqa: E402

EXPECTED_TOOLS = [
    "agentcut.status",
    "agentcut.capabilities",
    "agentcut.project_create",
    "agentcut.project_list",
    "agentcut.project_get",
    "agentcut.timeline_edit",
]
# 1.219 之前那份手抄名单里的名字：引擎从来没有这些，出现一次就是又回到抄错的那一份。
STALE_KINDS = (
    "fade_black",
    "flash_white",
    "wipe_left",
    "wipe_right",
    "wipe_up",
    "wipe_down",
)

FAILURES: list[str] = []


def check(label: str, condition: bool, evidence: object = "") -> bool:
    if not condition:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")
    return bool(condition)


def err_code(body: dict) -> str:
    """拒绝信封里那个名字；成功的那一份没有 error，就交回空串。"""
    return body.get("error", {}).get("code", "")


def refused(reply, status: int, code: str) -> bool:
    """拒绝那一手的两判：状态码与那个名字都要对；红的时候把整个回信带回去。"""
    return reply[0] == status and err_code(reply[1]) == code


ROW_KEYS = {"id", "name", "revision", "clips", "assets", "content_ticks"}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def request(base, token, path, payload=None, headers=None):
    """返回 (status, body, headers)。拒绝也要读正文，不然红的那句没有证据。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method="POST" if data else "GET")
    sent = {"Host": base.split("//", 1)[1]}
    if token:
        sent["x-agentcut-token"] = token
    for key, value in (headers or {}).items():
        if value is None:
            sent.pop(key, None)
        else:
            sent[key] = value
    for key, value in sent.items():
        req.add_header(key, value)
    if data:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}"), dict(response.headers)
    except urllib.error.HTTPError as failure:
        raw = failure.read()
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {"raw": raw.decode("utf-8", "replace")[:300]}
        return failure.code, body, dict(failure.headers)


def tool(base, token, name, args):
    """成功交回那一格的内容，失败交回整个信封（信封里有 ok=False 与 error.code）。"""
    body = request(base, token, "/api/agent/tool", {"tool": name, "input": args})[1]
    return body["data"] if body.get("ok") else body


def edit_input(project_id, revision, command, dry_run=False):
    return {
        "id": project_id,
        "expected_revision": revision,
        "commands": [command],
        "dry_run": dry_run,
    }


def boot(work: Path, port: int, token: str):
    """拉起 agent/server.py：库、令牌目录、端口全指到这一份临时工作区。"""
    env = dict(
        os.environ,
        AGENTCUT_DATA_DIR=str(work / "data"),
        AGENT_API_DATA_DIR=str(work / "token"),
        AGENT_API_TOKEN=token,
        AGENT_PORT=str(port),
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
    )
    log = (work / "server.log").open("wb")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "agent" / "server.py")],
        cwd=str(ROOT / "agent"),
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
    )
    return proc, log


def wait_ready(base: str, proc) -> bool:
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            if request(base, "", "/api/health")[0] == 200:
                return True
        except OSError:
            pass
        time.sleep(0.4)
    return False


def main() -> None:
    work = scratch.make("agentcut-agentapi-")
    data_dir = work / "data"
    token = "0123456789abcdef0123456789abcdef"
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    real_db = ROOT / "data" / "agentcut.sqlite3"
    real_before = real_db.stat().st_mtime_ns if real_db.exists() else None
    proc, log = boot(work, port, token)
    try:
        if not wait_ready(base, proc):
            tail = (work / "server.log").read_text(encoding="utf-8", errors="replace")[:400]
            check("服务在 90 s 内起来并回健康", False, f"rc={proc.poll()} log={tail}")
            return

        # ① 健康那一格说的是真的：项目名、工具数、守卫的三句话
        _, health, head = request(base, "", "/api/health")
        info = health.get("data", {})
        check("健康报的是 AgentCut", info.get("project") == "AgentCut", health)
        check("六只工具都注册了", info.get("tools") == 6, info)
        guard = info.get("guard", {})
        check("守卫说令牌来自 env", guard.get("token_file") == "env", guard)
        check("不发通配 CORS", "access-control-allow-origin" not in {k.lower() for k in head}, head)

        # ② 守卫：假 Host、外来 Origin、没令牌，三条都必须在业务逻辑之前被拒
        bad_host = request(base, "", "/api/health", headers={"Host": "evil.example:1"})
        check("Host 不对就 403", refused(bad_host, 403, "HOST_NOT_ALLOWED"), bad_host)
        outer = request(base, "", "/api/health", headers={"Origin": "http://evil.example"})
        check("Origin 外来就 403", refused(outer, 403, "ORIGIN_NOT_ALLOWED"), outer)
        no_token = request(
            base, "", "/api/agent/tool", {"tool": "agentcut.status", "input": {}},
            headers={"x-agentcut-token": None},
        )
        check("写接口不带令牌就 401", refused(no_token, 401, "TOKEN_REQUIRED"), no_token)

        # ③ 名单与清单：manifest 里那一份就是路由用的那一份
        listed = request(base, token, "/api/agent/tools")[1].get("data", [])
        check("工具名单就是这六个", [item["name"] for item in listed] == EXPECTED_TOOLS, listed)
        shaped = [
            item
            for item in listed
            if item.get("input_schema", {}).get("type") == "object"
            and item.get("risk") in ("read", "write")
        ]
        check("每只都带了 schema 与 risk", len(shaped) == 6, listed)
        manifest = request(base, token, "/api/agent/manifest")[1].get("data", {})
        api = manifest.get("api", {})
        check("清单点名的令牌头就是用的那一个", api.get("token_header") == "x-agentcut-token", api)
        check("清单里 base_url 是本机回环", manifest.get("base_url", "").startswith(base), manifest)

        # ④ status：版本必须是仓库里那一个，库必须落在临时目录
        st = tool(base, token, "agentcut.status", {})
        check("status 报的版本 = 契约里那一个", st.get("version") == APP_VERSION, st)
        check("status 报的 schema = 同一个常量", st.get("schema_version") == SCHEMA_VERSION, st)
        binaries = st.get("binaries", {})
        check("库在临时目录，不碰用户的", str(data_dir) in binaries.get("database", ""), binaries)
        check("空库里一个工程都没有", st.get("total_projects") == 0, st)

        # ⑤ capabilities：转场名必须是引擎那张表，抄错的那份名单一个字不许留下
        caps = tool(base, token, "agentcut.capabilities", {})
        table = engine_capabilities()
        served = [item["id"] for item in caps.get("transition_kinds", [])]
        ids = [item["id"] for item in table["transition_kinds"]]
        check("转场名单与引擎那张表逐字相同", served == ids, served)
        for stale in STALE_KINDS:
            check(f"抄错的旧名 {stale} 已绝迹", stale not in served, served)
        check("淡的形状也同源", caps.get("fade_shapes") == table["fade_shapes"], caps)
        check("时间基准就是那一个数", caps.get("timebase") == TIMEBASE, caps)

        # ⑥ 建一个工程，读回来，再按引擎的命令改它一格
        made = tool(
            base, token, "agentcut.project_create",
            {"name": "接口验真", "fps": 25, "width": 640, "height": 360},
        )
        project_id = str(made.get("id", ""))
        check("新建的工程头就是 0", made.get("revision") == 0, made)
        check("帧率按分子交回", made.get("frame_rate", {}).get("numerator") == 25, made)
        check("宽高落了库", (made.get("width"), made.get("height")) == (640, 360), made)

        read = tool(base, token, "agentcut.project_get", {"id": project_id})
        check(
            "读回来的是同一份时间线",
            read.get("id") == project_id and {"tracks", "clips"} <= set(read),
            list(read)[:8],
        )
        rows = tool(base, token, "agentcut.project_list", {"limit": 10})
        row_list = rows.get("projects", [])
        check(
            "列表交回引擎那几列",
            row_list and set(row_list[0]) == ROW_KEYS,
            rows,
        )

        first = {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "画面"}}
        written = tool(base, token, "agentcut.timeline_edit", edit_input(project_id, 0, first))
        check(
            "批命令写真涨了一个版本",
            written.get("committed") is True and written.get("project", {}).get("revision") == 1,
            written,
        )

        # dry-run 不许写：用一条**当下合法**的新命令试跑（同一条重放到已有轨道上
        # 会被 duplicate_id 抢先把红变成另一种红），试跑之后头仍停在 1
        second = {"op": "track.add", "track": {"id": "v2", "kind": "video", "name": "画面二"}}
        dry = tool(base, token, "agentcut.timeline_edit", edit_input(project_id, 1, second, True))
        check("dry_run 不写库", dry.get("committed") is False, dry)
        after = tool(base, token, "agentcut.project_get", {"id": project_id})
        check("试跑之后头还是 1", after.get("revision") == 1, after)

        # 乐观版本：拿写完那一版之前的那个头再写一次，必须被点名拒绝，而且写不进去
        conflict = tool(base, token, "agentcut.timeline_edit", edit_input(project_id, 0, second))
        check("旧版本号被拒且点名冲突", err_code(conflict) == "revision_conflict", conflict)
        head = tool(base, token, "agentcut.project_get", {"id": project_id})
        check("被拒那一手也没写进去", head.get("revision") == 1, head.get("revision"))

        # ⑦ 三类拒绝各有名字：不存在的工程、缺参数、没注册的工具
        missing = tool(base, token, "agentcut.project_get", {"id": "nonexistent"})
        check("查不到的工程回 not_found", err_code(missing) == "not_found", missing)
        bad = tool(base, token, "agentcut.project_get", {})
        check(
            "缺必填参数点名那一个",
            err_code(bad) == "bad_input" and "id" in str(bad.get("error", {}).get("message")),
            bad,
        )
        unknown = tool(base, token, "agentcut.nope", {})
        check(
            "没注册的工具列出可用的那几个",
            unknown.get("error", {}).get("code") == "unknown_tool"
            and len(unknown.get("error", {}).get("available", [])) == 6,
            unknown,
        )
        ghost = request(base, token, "/api/nope")[1]
        endpoints = ghost.get("error", {}).get("endpoints", [])
        check(
            "未知路径也说清有哪些出口",
            err_code(ghost) == "not_found" and len(endpoints) == 4,
            ghost,
        )

        # ⑧ 隔离：用户的真实库一个字节都没动
        real_after = real_db.stat().st_mtime_ns if real_db.exists() else None
        check("用户那个库没被碰", real_before == real_after, (real_before, real_after))
        made_db = (data_dir / "agentcut.sqlite3").exists()
        check("临时库里确实建了表", made_db, list(data_dir.iterdir()))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()

    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print(
        f"PASS: 标准 Agent API 六只工具真起真走 —— 版本 {APP_VERSION}、守卫三条都拒、"
        "转场名单与引擎同源、写涨版本、dry-run 与旧版本号都拒、用户的库没被碰"
    )


if __name__ == "__main__":
    main()
