"""1.312：三条配方都能一把跑完——`recipe_run` 走完契约里那三张步骤表。

配方此前只能被**读**：另一个 agent 读完步骤自己发请求、自己串 expected_revision。1.311 开了
`cut-from-media`，这一版把另两条也接上，而且没有第二套规则：每一步都是引擎用自己的路由表、
同一条 bearer 令牌，从进程内的门再叫一次同一批路由，reducer、revision 校验、素材根授权与幂等
凭据一步都绕不开。「剪哪几行」这类判断仍归调用方——它作为**数据**进来（命中词、停顿长度），
选出来的段仍是引擎那份文稿视图交回的那几段。

六道，每一道都能红：
① 契约面：`recipe_run` 登记了路由；三条配方的每一步都有执行步（配方文本与执行表漂移就红）；
   每条配方 `params` 那段话点名的必填参数，与 `required_fields()` 算出来的一字不差；
② `cut-from-media` 真一刀：两份 4 秒源 → 一次调用 → 探测、建工程、落库、静音剪、镜头粗剪、
   排队交付、等到终态，交付比源短，PNG 那两步明写没跑；
③ `speech-to-captions` 真一刀：Windows 语音合成出**真中文口播**（两句之间空一秒）→ 一次调用
   出字幕、读文稿、按 `cut_gap_ms` 剪掉那句间静音、交回 SRT 字数、排队交付并等到终态；
④ `imitate-imported-edit` 真一刀：把 ② 那条工程的**引擎自己导出的 OTIO** 原文再读进来 →
   一批落库、核对 revision、三份交换格式各交回一份、一次排两条交付并都等到终态；
⑤ 重放与三条拒绝：同一个 request_id 拿回同一个工程与同一个作业；缺参数按 RECIPE_PARAM_MISSING
   点名缺哪一样；不存在的配方 404；素材越界停在那一步并把门名交回；
⑥ MCP 与桥同源：`create_mcp()` 交出 `recipe_run(recipe_id, request)`，三条 prompt 都指得到这一刀；
   用这台 app 自己的 `route_params()` 走 `resolve()`，path/query/body 各就各位。
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
sys.path.insert(0, str(ROOT / "tests"))

import asr_check  # noqa: E402

from agentcut import agent_contract, recipe_run  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.mcp_server import create_mcp  # noqa: E402
from agentcut.media import MediaService  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
MODELS = ROOT / "desktop/resources/asr"
PRESET = "h264-720p-web"
FAILURES: list[str] = []

STEP_COUNTS = {"cut-from-media": 13, "speech-to-captions": 15, "imitate-imported-edit": 16}


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:320]}")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def offline_surface() -> None:
    """① 契约登记、派发、每一步都有人做，以及参数那句话与执行表一字不差。"""
    entry = dict(agent_contract.TOOL_ENDPOINTS).get("recipe_run")
    check("契约登记了 recipe_run 的路由",
          entry == ("POST", "/v1/agent/recipes/{recipe_id}/run"), entry)
    request = {"request_id": "r1", "name": "一刀", "files": ["a.mp4"],
               "preset_id": PRESET, "filename": "out.mp4"}
    method, path, query, body = "", "", {}, None
    try:
        method, path, query, body = agent_contract.resolve(
            "recipe_run", {"recipe_id": "cut-from-media", "request": request}, {}
        )
    except KeyError as error:  # 没登记的那一只：报成断言，不掀桌
        check("recipe_run 派得出路由（没登记就是这一条红）", False, repr(error))
    check("recipe_id 进路径",
          method == "POST" and path == "/v1/agent/recipes/cut-from-media/run", (method, path))
    check("request 留在 body 里，query 空", body == {"request": request} and query == {},
          (query, body))

    declared_all: set[str] = set()
    for recipe_id, expected in STEP_COUNTS.items():
        declared = recipe_run.declared_steps(recipe_id)
        declared_all.update(declared)
        check(f"{recipe_id} 的步骤数是 {expected}", len(declared) == expected, declared)
        missing = [name for name in declared if name not in recipe_run.RUNNERS]
        check(f"{recipe_id} 的每一步都有执行步（缺一个人就红）", not missing, missing)
    check("执行表没有多余的步",
          set(recipe_run.RUNNERS) == declared_all,
          sorted(set(recipe_run.RUNNERS) ^ declared_all))

    rows = {row["id"]: row for row in agent_contract.recipes()}
    check("三条配方都开了这一刀",
          all(row["runnable"] is True for row in rows.values()),
          [(row["id"], row["runnable"]) for row in rows.values()])
    check("开不通的原因文本不再挂在契约上（都开了就不许留旧说法）",
          all("why_not" not in row for row in rows.values()), sorted(rows))

    sample = recipe_run.RecipeRun(request_id="x", name="n", files=["a"])
    for recipe_id, row in rows.items():
        needed = recipe_run.required_fields(recipe_id, sample)
        if recipe_id == "imitate-imported-edit":
            needed = recipe_run.required_fields(recipe_id, recipe_run.RecipeRun(
                request_id="x", name="n", interchange_document="{}"))
        silent = [name for name in needed if name not in row["params"]]
        check(f"{recipe_id} 的参数那句话点名了每个必填项", not silent, (needed, silent))
        text = agent_contract.render_recipe(row)
        check(f"{recipe_id} 的 prompt 指得到这一刀", "recipe_run" in text, text[-200:])
        check(f"{recipe_id} 的 prompt 不再说不通则明写不能一把跑完",
              "不能一把跑完" not in text, text[-160:])


def build_source(folder: Path, index: int, colour: str, tone: float) -> Path:
    """Four seconds: two seconds of sound then two of silence, one flat colour the whole way."""
    target = folder / f"src{index}.mp4"
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y", "-nostdin",
            "-f", "lavfi", "-i", f"color=c={colour}:s=320x180:r=30:d=4",
            "-f", "lavfi", "-i", f"sine=frequency={tone}:r=48000:d=2",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=2",
            "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
            "-shortest", str(target),
        ],
        check=True, capture_output=True, timeout=600, creationflags=0x08000000,
    )
    return target


def new_client(folder: Path) -> TestClient:
    token = "recrunchk" + "f" * 53
    service = MediaService(folder / "rr-db.sqlite3", [folder], folder / "rr-cache",
                           FFMPEG, FFPROBE, asr_dirs=[MODELS])
    runtime = JobRuntime(folder / "rr-api.sqlite3", FFMPEG, folder / "out", [folder / "out"])
    runtime.ensure_worker()
    app = create_app(folder / "rr-api.sqlite3", token, media=service, jobs=runtime)
    return TestClient(app, base_url="http://127.0.0.1",
                      headers={"Authorization": f"Bearer {token}"})


def shape_of(client: TestClient, made: dict) -> dict:
    return {row["step"]: row for row in made["steps"]}


def cut_from_media(client: TestClient, folder: Path) -> dict:
    """② 一条真片子：从两个原始文件一刀走到交付。"""
    sources = [build_source(folder, 0, "red", 440), build_source(folder, 1, "green", 660)]
    payload = {
        "request_id": "rr-one-cut",
        "name": "一刀跑完",
        "files": [str(item) for item in sources],
        "threshold_db": -40.0,
        "min_silence_ms": 500,
        "keep_ms": 500,
        "preset_id": PRESET,
        "filename": "cut.mp4",
        "render": True,
        "wait_seconds": 90.0,
    }
    first = client.post("/v1/agent/recipes/cut-from-media/run", json=payload)
    check("cut-from-media 一次调用跑完", first.status_code == 200, first.text[:400])
    if first.status_code != 200:
        return {}
    made = first.json()
    rows = shape_of(client, made)
    check("步骤顺序就是配方那 13 步",
          [row["step"] for row in made["steps"]] == recipe_run.declared_steps("cut-from-media"),
          [row["step"] for row in made["steps"]])
    check("PNG 那两步明写没跑，且给了名字",
          rows["timeline_overview"]["ran"] is False
          and "timeline_overview" in rows["timeline_overview"]["why"], rows["timeline_overview"])
    check("每一步都留下叫的是哪扇门",
          all("called" in row for row in made["steps"] if row["ran"]),
          [row["step"] for row in made["steps"] if row["ran"] and "called" not in row])
    check("导了两个文件", rows["media_import"]["files"] == 2, rows["media_import"])
    check("静音那一刀剪掉了东西", rows["track_silence"]["removed_ticks"] > 0,
          rows["track_silence"])
    check("镜头粗剪动了命令", rows["track_rough_cut"]["commands"] > 0, rows["track_rough_cut"])
    plan = made.get("plan") or {}
    check("render_plan 交回了编译好的计划与 argv",
          (plan.get("plan") or {}).get("duration_seconds") is not None
          and rows["render_plan"].get("argv", 0) > 2, (sorted(plan), rows["render_plan"]))
    check("两刀之后 revision 至少 3", int(made["revision"]) >= 3, made["revision"])
    job = made.get("job") or {}
    check("等到终态是 succeeded", job.get("status") == "succeeded", job)
    out = Path(job.get("output_path") or "")
    if out.is_file():
        seconds = probe_duration(out)
        planned = float((plan.get("plan") or {}).get("duration_seconds") or 0)
        check("交付比源短", 0.3 <= seconds < 4.0, seconds)
        check("计划说的长度就是交付出来的长度", abs(planned - seconds) <= 0.25,
              (planned, seconds))
        print(f"   一刀跑完：2 段素材 → revision {made['revision']}，交付 {seconds:.2f} s"
              f"（计划 {planned:.2f} s），等了 {made['waited_ms']} ms")
    else:
        check("交付文件在盘上", False, str(out))
    return made


def speech_to_captions(client: TestClient, folder: Path) -> None:
    """③ 真口播：两句中文之间空一秒，字幕落库、按停顿剪、SRT 交回字数。"""
    source = asr_check.speech_fixture(folder)
    seconds = probe_duration(source)
    payload = {
        "request_id": "rr-speech",
        "name": "口播一刀",
        "files": [str(source)],
        "filler_patterns": ["这一版夹具里不可能出现的词"],
        "cut_gap_ms": 600,
        "preset_id": PRESET,
        "filename": "speech-cut.mp4",
        "render": True,
        "wait_seconds": 100.0,
    }
    answer = client.post("/v1/agent/recipes/speech-to-captions/run", json=payload)
    check("speech-to-captions 一次调用跑完", answer.status_code == 200, answer.text[:500])
    if answer.status_code != 200:
        return
    made = answer.json()
    rows = shape_of(client, made)
    check("口播这一刀的步骤就是配方那 15 步",
          [row["step"] for row in made["steps"]]
          == recipe_run.declared_steps("speech-to-captions"),
          [row["step"] for row in made["steps"]])
    check("字幕轨落成了（cue 不止一条）",
          rows["captions_auto"]["ran"] is True and rows["captions_auto"]["cues"] >= 2,
          rows["captions_auto"])
    check("文稿读回了句间静音", rows["timeline_transcript"]["silences"] >= 1,
          rows["timeline_transcript"])
    check("按 cut_gap_ms 选出的那一段剪掉了",
          rows["transcript_cut_plan"]["ran"] is True
          and rows["transcript_cut_plan"]["spans"] >= 1
          and rows["transcript_cut_plan"]["commands"] > 0,
          rows["transcript_cut_plan"])
    check("SRT 交回了字数", rows["captions_export"]["srt_chars"] > 0, rows["captions_export"])
    check("回执默认不带 SRT 全文（长文本要就 include_text）",
          "srt" not in rows["captions_export"], sorted(rows["captions_export"]))
    job = made.get("job") or {}
    check("口播这一刀也等到终态", job.get("status") == "succeeded", job)
    out = Path(job.get("output_path") or "")
    if out.is_file():
        delivered = probe_duration(out)
        check("剪掉那句间静音之后确实短了", delivered < seconds - 0.4, (seconds, delivered))
        cues = rows["captions_auto"]["cues"]
        chars = rows["captions_export"]["srt_chars"]
        print(f"   口播一刀：源 {seconds:.2f} s → 交付 {delivered:.2f} s，cue {cues} 条、"
              f"SRT {chars} 字")
    else:
        check("口播的交付文件在盘上", False, str(out))


def imitate_imported(client: TestClient, folder: Path, document: str, sources: list) -> None:
    """④ 搬别人剪好的一刀：那份文档就是引擎自己导出的 FCPXML，素材照旧要点名。"""
    payload = {
        "request_id": "rr-imitate",
        "name": "搬一刀再交付",
        "interchange_document": document,
        "files": [str(item) for item in sources],
        "deliver_items": [
            {"preset_id": PRESET, "filename": "borrowed-web.mp4"},
            {"preset_id": "h264-1080p", "filename": "borrowed-hd.mp4"},
        ],
        "render": True,
        "wait_seconds": 100.0,
    }
    answer = client.post("/v1/agent/recipes/imitate-imported-edit/run", json=payload)
    check("imitate-imported-edit 一次调用跑完", answer.status_code == 200, answer.text[:500])
    if answer.status_code != 200:
        return
    made = answer.json()
    rows = shape_of(client, made)
    edits = [row for row in made["steps"] if row["step"] == "timeline_edit"]
    check("搬一刀的步骤就是配方那 16 步",
          [row["step"] for row in made["steps"]]
          == recipe_run.declared_steps("imitate-imported-edit"),
          [row["step"] for row in made["steps"]])
    check("读第一遍之前先把素材登记成这个工程的",
          [row.get("source") for row in edits][:1] == ["assets"], [row.get("source")
                                                                   for row in edits])
    check("格式是引擎自己认的",
          rows["interchange_import_plan"].get("needs_tracks")
          or rows["interchange_import_plan"].get("format") == "fcpxml",
          rows["interchange_import_plan"])
    check("落库那一批走的是 timeline_edit",
          edits[-1].get("source") == "import" and edits[-1].get("commands") > 0, edits[-1])
    check("project_get 核对出了轨道与片段",
          rows["project_get"]["tracks"] >= 1 and rows["project_get"]["clips"] >= 1,
          rows["project_get"])
    for tool in ("project_otio", "project_xmeml", "project_jianying"):
        check(f"{tool} 交回了东西（按字节数）",
              rows[tool]["ran"] is True and rows[tool]["bytes"] > 64, rows[tool])
    check("一次排了两条交付", rows["render_batch"]["jobs"] == 2, rows["render_batch"])
    jobs = made.get("jobs") or []
    check("两条交付都等到终态", len(jobs) == 2 and all(job.get("status") == "succeeded"
                                                  for job in jobs),
          [(job.get("filename"), job.get("status")) for job in jobs])
    for job in jobs:
        if not Path(job.get("output_path") or "").is_file():
            check("交付文件在盘上", False, str(job.get("output_path")))
    present = [Path(job["output_path"]).stat().st_size for job in jobs
               if Path(job.get("output_path") or "").is_file()]
    if len(present) == 2:
        print(f"   搬一刀：落库 {edits[-1]['commands']} 条命令，"
              f"两份交付 {present[0]} / {present[1]} B，等了 {made['waited_ms']} ms")


def refusals_and_replay(client: TestClient, folder: Path, made: dict) -> None:
    """⑤ 重放与三条拒绝。"""
    payload = {
        "request_id": "rr-one-cut",
        "name": "一刀跑完",
        "files": [str(folder / "src0.mp4"), str(folder / "src1.mp4")],
        "threshold_db": -40.0,
        "min_silence_ms": 500,
        "keep_ms": 500,
        "preset_id": PRESET,
        "filename": "cut.mp4",
        "render": True,
        "wait_seconds": 90.0,
    }
    second = client.post("/v1/agent/recipes/cut-from-media/run", json=payload)
    check("重放这一刀不报错", second.status_code == 200, second.text[:300])
    again = second.json()
    check("重放说清这是重放", again.get("replayed") is True, sorted(again))
    check("重放拿回同一个工程", again.get("project_id") == made.get("project_id"),
          (again.get("project_id"), made.get("project_id")))
    rows = {row.get("step"): row for row in again.get("steps") or []}
    check("重放不再写第二遍",
          (rows.get("timeline_edit") or {}).get("ran") is False
          and "已经跑过" in str((rows.get("timeline_edit") or {}).get("why")),
          rows.get("timeline_edit"))
    check("重放的 revision 是工程现在的那一个",
          again.get("revision") == made.get("revision"),
          (again.get("revision"), made.get("revision")))
    listed = client.get("/v1/projects").json()["projects"]
    check("工程列表里没有新增（重放与拒绝都不该留半个）", len(listed) == 3,
          [item["id"] for item in listed])

    ghost = client.post("/v1/agent/recipes/no-such-recipe/run", json=payload)
    ghost_body = ghost.json().get("error") or {}
    ghost_details = ghost_body.get("details") or {}
    check("不存在的配方按 NOT_FOUND 拒，并列出有哪些",
          ghost.status_code == 404 and ghost_body.get("code") == "NOT_FOUND"
          and len(ghost_details.get("recipes") or []) == 3, ghost.text[:300])

    gap_payload = dict(payload)
    gap_payload["request_id"] = "rr-no-preset"
    gap_payload.pop("preset_id")
    refused = client.post("/v1/agent/recipes/cut-from-media/run", json=gap_payload)
    refused_body = refused.json().get("error") or {}
    details = refused_body.get("details") or {}
    check("缺参数在建工程之前就点名拒，不留下半个工程",
          refused.status_code == 422
          and refused_body.get("code") == "RECIPE_PARAM_MISSING"
          and details.get("missing") == ["preset_id"], refused.text[:300])

    outside = scratch.make("agentcut-recrun-outside-")
    stray_source = build_source(outside, 0, "blue", 880)
    stray_payload = dict(payload)
    stray_payload["request_id"] = "rr-outside"
    stray_payload["files"] = [str(stray_source)]
    answer = client.post("/v1/agent/recipes/cut-from-media/run", json=stray_payload)
    body = answer.json().get("error") or {}
    nested = body.get("details") or {}
    check("素材越界时停在那一步，并说清是哪一步",
          answer.status_code >= 400 and "media/import" in str(nested.get("called")),
          (answer.status_code, body.get("code"), nested))
    after = client.get("/v1/projects").json()["projects"]
    check("越界那一刀没留下半个工程（探测在建工程之前）", len(after) == len(listed),
          [item["id"] for item in after])


def mcp_surface() -> None:
    """⑥ MCP 那一侧同源，参数形状是 recipe_id + request。"""
    server = create_mcp("http://127.0.0.1:0", "recrunchk" + "f" * 52)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    check("MCP 也交出 recipe_run", "recipe_run" in tools, sorted(tools)[-8:])
    if "recipe_run" in tools:
        props = set((tools["recipe_run"].inputSchema or {}).get("properties") or {})
        check("MCP 那一只的参数是 recipe_id 与 request", props == {"recipe_id", "request"}, props)


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
            {"recipe_id": "cut-from-media", "request": {"request_id": "x", "name": "n",
                                                        "files": ["a.mp4"],
                                                        "preset_id": PRESET,
                                                        "filename": "o.mp4"}},
            params,
        )
    except KeyError as error:  # 桥派不出去的这一只：报成断言，不掀桌
        check("⑥ 这一只在桥的表上（没登记就红在这里）", False, repr(error))
    check("桥按这张表派得出这一刀",
          method == "POST" and path == "/v1/agent/recipes/cut-from-media/run" and query == {}
          and isinstance(body, dict) and body.get("name") == "n", (method, path, query, body))


def main() -> None:
    if not (FFMPEG.is_file() and FFPROBE.is_file()):
        print("缺随包 ffmpeg/ffprobe，这一档量不了真交付")
        raise SystemExit(1)
    offline_surface()
    folder = scratch.make("agentcut-recrun-")
    (folder / "stray").mkdir()
    with new_client(folder) as client:
        made = cut_from_media(client, folder)
        if made:
            listed = client.get(f"/v1/projects/{made['project_id']}/fcpxml").json()
            document = str(listed.get("xml") or "")
            check("②那条工程导得出 FCPXML（④的输入就是它）", len(document) > 200,
                  (sorted(listed), len(document)))
            imitate_imported(client, folder, document,
                             [folder / "src0.mp4", folder / "src1.mp4"])
        speech_to_captions(client, folder)
        refusals_and_replay(client, folder, made)
    mcp_surface()
    bridge_dispatch(folder)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: 三条配方都能一把跑完——步骤表就是执行表，重放不重复，缺参数在建工程之前就点名拒")


if __name__ == "__main__":
    main()
