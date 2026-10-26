"""1.311：`recipe_run`——把一条剪辑配方在引擎里一把跑完，走的还是 agent 自己那批门。

`cut-from-media` 那 13 步此前只能被**读**：另一个 agent 读完配方，自己发 13 次请求、自己
把 expected_revision 一步接一步串起来。这一版让引擎自己走这张表，但**没有第二套规则**：
每一步都是同一批路由、同一条 bearer 令牌、同一个 reducer，交回的步骤名就是契约里的工具名。

六道，每一道都能红：
① 契约面：`recipe_run` 登记了路由，`resolve()` 把 recipe_id 放进路径、request 放进 body；
   配方的每一步都有对应执行步（配方文本与执行表漂移就红），不可跑的配方带着原因说；
② 真的一刀：两份真素材 → 一次调用 → 先探测导入、再建工程落库、静音剪、镜头粗剪、
   排队交付、等到终态，输出文件在盘上，ffprobe 量到的长度短于源（证明真的剪了），
   PNG 那两步明写没跑；
③ 重放不重复：同一个 request_id 叫两次拿回同一个工程、同一个作业与同一个 revision，
   后面的写步明确说「已经跑过」，工程列表不新增；
④ 三条拒绝：不存在的配方（404 NOT_FOUND）、开不通的配方（422 带原因）、
   素材不在授权根目录（错误里带着是哪一步停的）；
⑤ MCP 同源：`create_mcp()` 交出的工具表里也有 `recipe_run`，参数是 recipe_id + request；
⑥ 桥的派发：用这台 app 自己的 `route_params()` 走一遍 `resolve()`，路径/查询/body 各就各位。
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import scratch
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut import agent_contract, recipe_run  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.mcp_server import create_mcp  # noqa: E402
from agentcut.media import MediaService  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
RECIPE = "cut-from-media"
FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:300]}")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def build_source(folder: Path, index: int, colour: str, tone: float) -> Path:
    """Four seconds: two seconds of sound then two of silence, one flat colour the whole way.

    The quiet half is what `track_silence` cuts and the colour is what `track_rough_cut` keeps
    a head of, so a run that skipped either step would show up as a file that is still 4 s.
    """
    target = folder / f"src{index}.mp4"
    argv = [
        str(FFMPEG), "-v", "error", "-y", "-nostdin",
        "-f", "lavfi", "-i", f"color=c={colour}:s=320x180:r=30:d=4",
        "-f", "lavfi", "-i", f"sine=frequency={tone}:r=48000:d=2",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=2",
        "-filter_complex",
        "[1:a][2:a]concat=n=2:v=0:a=1[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
        "-shortest", str(target),
    ]
    subprocess.run(argv, check=True, capture_output=True, timeout=600, creationflags=0x08000000)
    return target


def offline_surface() -> None:
    """① 契约登记、派发与「每一步都有人做」。

    离线 resolve() 没有路由签名可读，只把没进路径的键原样包成 body；真正按 path/query/body
    拆开的是 ⑥ 那一道——它拿这台 app 自己的 route_params() 走同一段代码。
    """
    entry = dict(agent_contract.TOOL_ENDPOINTS).get("recipe_run")
    check("契约登记了 recipe_run 的路由",
          entry == ("POST", "/v1/agent/recipes/{recipe_id}/run"), entry)
    request = {"request_id": "r1", "name": "一刀", "files": ["a.mp4"],
               "preset_id": "h264-720p-web", "filename": "out.mp4"}
    method, path, query, body = "", "", {}, None
    try:
        method, path, query, body = agent_contract.resolve(
            "recipe_run", {"recipe_id": RECIPE, "request": request}, {}
        )
    except KeyError as error:  # 没登记的那一只：报成断言，不掀桌
        check("recipe_run 派得出路由（没登记就是这一条红）", False, repr(error))
    check("recipe_id 进路径", method == "POST" and path == f"/v1/agent/recipes/{RECIPE}/run",
          (method, path))
    check("request 留在 body 里，query 空", body == {"request": request} and query == {},
          (query, body))

    declared = recipe_run.declared_steps(RECIPE)
    missing = [name for name in declared if name not in recipe_run.RUNNERS]
    check("配方的每一步都有执行步（缺一个人就红）", not missing, missing)
    check("执行表没有多余的步",
          set(recipe_run.RUNNERS) == set(declared),
          sorted(set(recipe_run.RUNNERS) ^ set(declared)))
    check("1.311 的配方是 13 步", len(declared) == 13, declared)

    rows = {row["id"]: row for row in agent_contract.recipes()}
    check("能跑的那条标了 runnable", rows[RECIPE]["runnable"] is True, rows[RECIPE])
    others = [row for name, row in rows.items() if name != RECIPE]
    flags = [(row["id"], row["runnable"]) for row in others]
    check("另外两条明确说不能一把跑完",
          all(row["runnable"] is False for row in others), flags)
    check("不能跑的都带着原因",
          all((row.get("why_not") or "").strip() for row in others),
          [(r["id"], r.get("why_not")) for r in others])
    text_run = agent_contract.render_recipe(rows[RECIPE])
    text_stop = agent_contract.render_recipe(others[0])
    check("能跑的配方文案指得到这一刀", "recipe_run" in text_run, text_run[-260:])
    check("不能跑的配方文案说清不能", "不能一把跑完" in text_stop, text_stop[-200:])


def live_run(folder: Path) -> None:
    """②③④ 真的一刀、重放与三条拒绝。"""
    if not (FFMPEG.is_file() and FFPROBE.is_file()):
        check("随包 ffmpeg/ffprobe 在场才能量这一刀", False, f"{FFMPEG} / {FFPROBE}")
        return
    outside = scratch.make("agentcut-recrun-outside-")
    sources = [
        build_source(folder, 0, "red", 440),
        build_source(folder, 1, "green", 660),
    ]
    stray = build_source(outside, 0, "blue", 880)
    service = MediaService(folder / "rr-db.sqlite3", [folder], folder / "rr-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(folder / "rr-api.sqlite3", FFMPEG, folder / "out", [folder / "out"])
    runtime.ensure_worker()
    token = "recrunchk" + "f" * 53
    app = create_app(folder / "rr-api.sqlite3", token, media=service, jobs=runtime)
    payload = {
        "request_id": "rr-one-cut",
        "name": "一刀跑完",
        "files": [str(item) for item in sources],
        "threshold_db": -40.0,
        "min_silence_ms": 500,
        "keep_ms": 500,
        "preset_id": "h264-720p-web",
        "filename": "cut.mp4",
        "render": True,
        "wait_seconds": 90.0,
    }
    with TestClient(app, base_url="http://127.0.0.1",
                    headers={"Authorization": f"Bearer {token}"}) as client:
        first = client.post(f"/v1/agent/recipes/{RECIPE}/run", json=payload)
        check("一次调用跑完整条配方", first.status_code == 200, first.text[:400])
        if first.status_code != 200:
            return
        made = first.json()
        rows = made["steps"]
        check("步骤行数与顺序就是配方那 13 步",
              [row["step"] for row in rows] == recipe_run.declared_steps(RECIPE),
              [row["step"] for row in rows])
        ran = {row["step"]: row for row in rows}
        check("PNG 那两步明写没跑，且给了名字",
              ran["timeline_overview"]["ran"] is False
              and "timeline_overview" in ran["timeline_overview"]["why"],
              ran["timeline_overview"])
        check("每一步都留下叫的是哪扇门",
              all("called" in row for row in rows if row["ran"]),
              [row["step"] for row in rows if row["ran"] and "called" not in row])
        check("导了两个文件", ran["media_import"]["files"] == 2, ran["media_import"])
        check("静音那一刀剪掉了东西",
              ran["track_silence"]["removed_ticks"] > 0, ran["track_silence"])
        check("镜头粗剪动了命令",
              ran["track_rough_cut"]["commands"] > 0, ran["track_rough_cut"])
        plan = made.get("plan") or {}
        check("render_plan 交回了编译好的计划与 argv",
              (plan.get("plan") or {}).get("duration_seconds") is not None
              and ran["render_plan"].get("argv", 0) > 2, (sorted(plan), ran["render_plan"]))
        check("两刀之后 revision 至少 3", int(made["revision"]) >= 3, made["revision"])

        job = made.get("job") or {}
        check("等到终态是 succeeded", job.get("status") == "succeeded", job)
        check("等到的不说超时", made.get("timed_out") is False, made.get("timed_out"))
        check("量得出等了多久", isinstance(made.get("waited_ms"), int), made.get("waited_ms"))
        out = Path(job.get("output_path") or "")
        if out.is_file():
            seconds = probe_duration(out)
            check("交付比源短（两段 4 秒源，剪到了 4 秒以内）", 0.3 <= seconds < 4.0, seconds)
            planned = float((plan.get("plan") or {}).get("duration_seconds") or 0)
            check("计划说的长度就是交付出来的长度", abs(planned - seconds) <= 0.25,
                  (planned, seconds))
            print(f"   一刀跑完：{made['clips']} 段素材 → revision {made['revision']}，"
                  f"计划 {planned:.2f} s，交付 {seconds:.2f} s，等了 {made['waited_ms']} ms")
        else:
            check("交付文件在盘上", False, str(out))

        # ③ 同一个 request_id 再来一次：同一个工程、同一个作业，工程列表不新增。
        second = client.post(f"/v1/agent/recipes/{RECIPE}/run", json=payload)
        check("重放这一刀不报错", second.status_code == 200, second.text[:300])
        again = second.json()
        check("重放说清这是重放", again.get("replayed") is True, sorted(again))
        check("重放拿回同一个工程", again.get("project_id") == made["project_id"],
              (again.get("project_id"), made["project_id"]))
        replayed = {row.get("step"): row for row in again.get("steps") or []}
        check("重放那一步自己承认是重放",
              (replayed.get("project_create") or {}).get("replayed") is True,
              replayed.get("project_create"))
        check("重放不再写第二遍",
              (replayed.get("timeline_edit") or {}).get("ran") is False
              and "已经跑过" in str((replayed.get("timeline_edit") or {}).get("why")),
              replayed.get("timeline_edit"))
        check("重放的 revision 是工程现在的那一个",
              again.get("revision") == made["revision"], (again.get("revision"),
                                                          made["revision"]))
        check("重放拿回同一个作业",
              (again.get("job") or {}).get("id") == job.get("id"),
              ((again.get("job") or {}).get("id"), job.get("id")))
        listed = client.get("/v1/projects").json()["projects"]
        check("工程列表里没有第二个", len(listed) == 1, [p["id"] for p in listed])

        # ④ 三条拒绝。
        ghost = client.post("/v1/agent/recipes/no-such-recipe/run", json=payload)
        ghost_body = ghost.json().get("error") or {}
        ghost_details = ghost_body.get("details") or {}
        check("不存在的配方按 NOT_FOUND 拒，并列出有哪些",
              ghost.status_code == 404 and ghost_body.get("code") == "NOT_FOUND"
              and len(ghost_details.get("recipes") or []) == 3, ghost.text[:300])
        stalled = client.post("/v1/agent/recipes/speech-to-captions/run", json=payload)
        stalled_body = stalled.json().get("error") or {}
        check("开不通的配方带着原因拒",
              stalled.status_code == 422 and stalled_body.get("code") == "RECIPE_NOT_RUNNABLE"
              and "字幕" in str(stalled_body.get("message")), stalled.text[:300])

        stray_payload = dict(payload)
        stray_payload["request_id"] = "rr-outside"
        stray_payload["files"] = [str(stray)]
        refused = client.post(f"/v1/agent/recipes/{RECIPE}/run", json=stray_payload)
        refused_body = refused.json().get("error") or {}
        details = refused_body.get("details") or {}
        check("素材越界时停在那一步，并说清是哪一步",
              refused.status_code >= 400 and "media/import" in str(details.get("called")),
              (refused.status_code, refused_body.get("code"), details))
        after = client.get("/v1/projects").json()["projects"]
        check("越界那一刀没有留下第二个工程", len(after) == 1, [p["id"] for p in after])


def mcp_surface() -> None:
    """⑤ MCP 那一侧同源，参数形状是 recipe_id + request。"""
    server = create_mcp("http://127.0.0.1:0", "recrunchk" + "f" * 52)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    check("MCP 也交出 recipe_run", "recipe_run" in tools, sorted(tools)[-8:])
    if "recipe_run" in tools:
        props = set((tools["recipe_run"].inputSchema or {}).get("properties") or {})
        check("MCP 那一只的参数是 recipe_id 与 request",
              props == {"recipe_id", "request"}, props)


def bridge_dispatch(app_folder: Path) -> None:
    """⑥ 桥派发的口径：用这台 app 自己的 route_params 走一遍 resolve()。"""
    app = create_app(app_folder / "rr-offline.sqlite3", "recrunchk" + "f" * 52)
    params = agent_contract.route_params(app)
    split = params.get(("POST", "/v1/agent/recipes/{recipe_id}/run"))
    check("这条路由自己说的是 recipe_id 走路径、request 走 body",
          split == {"path": ["recipe_id"], "query": [], "body": ["request"]}, split)
    method, path, query, body = "", "", {}, None
    try:
        method, path, query, body = agent_contract.resolve(
            "recipe_run",
            {"recipe_id": RECIPE, "request": {"request_id": "x", "name": "n", "files": ["a.mp4"],
                                              "preset_id": "p", "filename": "o.mp4"}},
            params,
        )
    except KeyError as error:  # 桥派不出去的这一只：报成断言，不掀桌
        check("⑥ 这一只在桥的表上（没登记就红在这里）", False, repr(error))
    check("桥按这张表派得出这一刀",
          method == "POST" and path == f"/v1/agent/recipes/{RECIPE}/run"
          and query == {} and isinstance(body, dict) and body.get("name") == "n",
          (method, path, query, body))


def main() -> None:
    offline_surface()
    folder = scratch.make("agentcut-recrun-")
    live_run(folder)
    mcp_surface()
    bridge_dispatch(folder)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: recipe_run 一把跑完 13 步、走的是同一批门，重放不重复，开不通的带着原因拒")


if __name__ == "__main__":
    main()
