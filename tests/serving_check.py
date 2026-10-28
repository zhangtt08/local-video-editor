"""1.318 服务化那一档：具名令牌、只读作用域、查得到的台账，和一条不许裸奔到网上的规则。

企业把剪辑交给 agent 流水线时，三件事缺一不可：**谁能调**（一枚枚发出去的令牌，能单独吊销）、
**只读的行不行**（给 BI 或审片用的令牌不该能改片子）、**谁做了什么**（引擎自己落的一本账）。
这一档五道，每道都能红：

① 现场发令牌：只读令牌读得动、写得拒（`SCOPE_DENIED` 点名是哪一只）；可写令牌写得成；
② 台账：每一次写与每一次被拒都落一行，`actor / method / path / status / request_id / project_id`
   齐备、`seq` 递增；纯读不落（桌面端一直在轮询，全记就把动作埋了）；
③ 吊销立刻生效：那只令牌下一手就 401，别人的照旧；
④ 未知令牌 401、不带令牌 401；桌面端那枚共享令牌也在表里、标 `local`、作用域齐全；
⑤ CLI 两面：`agentcut tokens --add-label` 只印一次密钥（存的是哈希）；`--host 0.0.0.0` 却没给
   `AGENTCUT_TOKEN` 时直接拒起来——自动生成的那枚只配听本机。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import scratch
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut import agent_contract  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.mcp_server import create_mcp  # noqa: E402
from agentcut.serving import AuditLog, TokenTable  # noqa: E402

SHARED = "shared1318" + "f" * 54
FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:320]}")


def issue(table: TokenTable, label: str, scopes: str) -> str:
    _row, secret = table.add(label, [scope for scope in ("read", "write") if scope in scopes])
    return secret


def cli(folder: Path, *args: str, extra_env: dict | None = None,
        wait: float = 60.0) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("AGENTCUT_TOKEN", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("ELECTRON_RUN_AS_NODE", None)
    if extra_env:
        env.update(extra_env)
    argv = [sys.executable, "-m", "agentcut", *args]
    proc = subprocess.Popen(
        argv, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=env,
    )
    try:
        out, err = proc.communicate(timeout=wait)
    except subprocess.TimeoutExpired:
        # 「该停下」那一手没停下 = 它真的起来了。交回一次 0 退出与一句话，让断言点名是哪一格，
        # 而不是让门禁抱一段 TimeoutExpired 走人（1.323 的刀就撞在这里：红了但没名字）。
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=60)
        try:
            out, err = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = "", ""
        err = (err or "") + f"\n这一手等了 {wait}s 还没退出（它起来了）"
        return subprocess.CompletedProcess(argv, 0, out, err)
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def tokens_and_ledger(folder: Path) -> tuple[TokenTable, AuditLog]:
    return TokenTable(folder / "tokens.json"), AuditLog(folder / "audit.jsonl")


def surface_legs(folder: Path) -> TestClient:
    table, ledger = tokens_and_ledger(folder)
    app = create_app(
        folder / "api.sqlite3", SHARED, tokens=table, audit=ledger,
    )
    return TestClient(app, base_url="http://127.0.0.1")


def identity_leg(folder: Path) -> None:
    """①②③④ 一次跑完：作用域、台账、吊销、未知令牌。"""
    table, ledger = tokens_and_ledger(folder)
    app = create_app(folder / "api.sqlite3", SHARED, tokens=table, audit=ledger)
    reader = issue(table, "review-desk", "read")
    writer = issue(table, "pipeline-a", "write")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        read_headers = {"Authorization": f"Bearer {reader}"}
        wrote_headers = {"Authorization": f"Bearer {writer}"}
        check("只读令牌读得动", client.get("/v1/projects", headers=read_headers).status_code == 200)
        refused = client.post("/v1/projects", headers=read_headers,
                              json={"request_id": "srv-deny", "name": "不该成"})
        body = refused.json().get("error") or {}
        check("只读令牌写被点名拒",
              refused.status_code == 403 and body.get("code") == "SCOPE_DENIED"
              and (body.get("details") or {}).get("actor") == "review-desk",
              (refused.status_code, body))
        made = client.post("/v1/projects", headers=wrote_headers,
                           json={"request_id": "srv-write", "name": "可写令牌那一手"})
        check("可写令牌写得成", made.status_code == 200, made.text[:200])
        project_id = ((made.json().get("project") or {}).get("id")
                      if made.status_code == 200 else None)
        listed = client.get("/v1/agent/audit", headers=read_headers)
        rows = (listed.json().get("events") or []) if listed.status_code == 200 else []
        check("台账把那两首都记下了",
              listed.status_code == 200
              and {row.get("status") for row in rows} >= {200, 403}, rows[:3])
        denied = next((row for row in rows if row.get("status") == 403), {})
        wrote = next((row for row in rows if row.get("request_id") == "srv-write"), {})
        check("被拒那一行说得出是谁、哪一手",
              denied.get("actor") == "review-desk" and denied.get("method") == "POST"
              and denied.get("path") == "/v1/projects", denied)
        check("写成那一行带着是谁做的与他的 request_id",
              wrote.get("actor") == "pipeline-a" and wrote.get("request_id") == "srv-write",
              wrote)
        # 工程 id 只有路径里带着它才记得到：建工程那一手的路径没有它，所以下面再落一次编辑。
        ids = client.post("/v1/ids?count=1", headers=wrote_headers).json()["ids"]
        edit = client.post(f"/v1/projects/{project_id}/edits?receipt=slim",
                           headers=wrote_headers,
                           json={"request_id": "srv-edit",
                                 "expected_revision": ((made.json().get("project") or {})
                                                       .get("revision") or 0),
                                 "commands": [{"op": "track.add",
                                               "track": {"id": ids[0], "kind": "video",
                                                         "name": "画面"}}]})
        check("可写令牌也改得动时间线", edit.status_code == 200, edit.text[:200])
        edited_row = next((row for row in
                           client.get("/v1/agent/audit?limit=10",
                                      headers=read_headers).json().get("events") or []
                           if row.get("request_id") == "srv-edit"), {})
        check("编辑那一行连工程都记下了",
              edited_row.get("project_id") == project_id
              and edited_row.get("actor") == "pipeline-a", (edited_row, project_id))
        check("seq 是递增的", [row["seq"] for row in rows] == sorted(
            row["seq"] for row in rows) and len({row["seq"] for row in rows}) == len(rows), rows)
        check("纯读不落台账（不然动作被心跳埋掉）",
              sum(1 for row in rows if row.get("method") == "GET"
                  and row.get("status") == 200) == 0, rows)
        revoked = table.revoke("pipeline-a")
        after = client.post("/v1/projects", headers=wrote_headers,
                            json={"request_id": "srv-after", "name": "吊销之后"})
        check("吊销立刻生效",
              revoked and after.status_code == 401,
              (revoked, after.status_code))
        still = client.get("/v1/projects", headers=read_headers)
        check("别人的令牌照旧能用", still.status_code == 200, still.status_code)
        anonymous = client.get("/v1/projects")
        stranger = client.get("/v1/projects",
                              headers={"Authorization": f"Bearer {'no' * 32}"})
        check("不带令牌与未知令牌都是 401",
              anonymous.status_code == 401 and stranger.status_code == 401,
              (anonymous.status_code, stranger.status_code))
        shared = client.get("/v1/projects",
                            headers={"Authorization": f"Bearer {SHARED}"})
        check("桌面端那枚共享令牌照旧能用", shared.status_code == 200, shared.status_code)
        labels = {row["label"]: row for row in table.summary()}
        check("共享令牌也在表里、标 local、作用域齐",
              labels.get("local", {}).get("scopes") == ["read", "write"], labels)
        stored = json.loads((folder / "tokens.json").read_text(encoding="utf-8"))
        hex64 = set("0123456789abcdef")
        check("表里存的是 64 位十六进制摘要，不是密钥本身",
              all(re.fullmatch(r"[0-9a-f]{64}", str(row.get("secret_sha256")))
                  and set(str(row.get("secret_sha256"))) <= hex64
                  for row in stored["tokens"]),
              [row.get("secret_sha256") for row in stored["tokens"][:1]])
        check("令牌文件里搜不到任何一只发出去的密钥",
              reader not in (folder / "tokens.json").read_text(encoding="utf-8")
              and writer not in (folder / "tokens.json").read_text(encoding="utf-8"),
              "secret stored in the clear")
        ledger_path = folder / "audit.jsonl"
        check("台账就是数据目录里那个文件，企业可以自己搬走",
              ledger_path.is_file() and listed.json().get("path") == str(ledger_path),
              listed.json().get("path"))


def contract_leg() -> None:
    """⑤ 三面同源：路由登记、MCP 那只、桥的派发。"""
    entry = dict(agent_contract.TOOL_ENDPOINTS).get("agent_audit")
    check("契约登记了台账这扇门", entry == ("GET", "/v1/agent/audit"), entry)
    import asyncio

    server = create_mcp("http://127.0.0.1:0", "shared1318" + "f" * 53)
    tools = {tool.name for tool in asyncio.run(server.list_tools())}
    check("MCP 也交出 agent_audit", "agent_audit" in tools, sorted(tools)[-6:])
    params = agent_contract.route_params(create_app(Path("unused.sqlite3"), SHARED))
    split = params.get(("GET", "/v1/agent/audit"))
    check("这条路由说清三个参数都在 query 上",
          split == {"path": [], "query": ["limit", "actor", "project_id"], "body": []}, split)


def cli_leg(folder: Path) -> None:
    """⑤ CLI：发令牌只印一次；没给令牌就不许绑到非本机地址。"""
    added = cli(folder, "tokens", "--data-dir", str(folder), "--add-label", "studio-b",
                "--scopes", "both")
    check("tokens --add-label 交回一只密钥", added.returncode == 0, added.stderr[-200:])
    issued = {}
    try:
        issued = json.loads(added.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        check("那一行是 JSON", False, added.stdout[-200:])
    check("只印一次密钥且带作用域",
          len(str(issued.get("token", ""))) >= 64 and issued.get("scopes") == ["read", "write"],
          issued)
    listed = cli(folder, "tokens", "--data-dir", str(folder))
    check("tokens 列表里能看到刚发的那只",
          "studio-b" in (listed.stdout or "") and "local" not in listed.stdout,
          listed.stdout[-200:])
    remote = cli(folder, "api", "--data-dir", str(folder / "remote"), "--host", "0.0.0.0",
                 "--port", "0")
    check("绑到非本机却没交令牌时，直接拒起来",
          remote.returncode != 0 and "AGENTCUT_TOKEN" in (remote.stderr + remote.stdout),
          (remote.returncode, (remote.stderr + remote.stdout)[-220:]))


def main() -> None:
    folder = scratch.make("agentcut-serving-")
    identity_leg(folder)
    contract_leg()
    cli_leg(scratch.make("agentcut-serving-cli-"))
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: 令牌有名字与作用域、台账记得住谁做了什么、没设防的地址起不来")


if __name__ == "__main__":
    main()
