"""1.314：`deliver_verify`——交付验收从调用方手里收回引擎，用的就是引擎自己那两台仪器。

以前「这条交付对不对」只有两处实现：本仓的两道门禁各自手抄了一份 `ffprobe` / `ebur128` 的读法，
调用方（另一个 agent）则得自己再抄第三份。引擎明明已经知道这个作业当时编出来的计划
（`plan_for` 就是 worker 要渲染的那一张），却只肯说一句 `output_checked`——那一句的意思只是
「有个探测在旁边认同这个文件读得开」。

四道，每一道都能红：
① 真交付之后验：verdict 为真，逐条交回实测数——长度对这个作业自己的计划、画幅与帧率对预设、
   响度用 FFmpeg 的 EBU R128 表量文件本身；配方最后那一格也必须真跑（偷偷跳过就红）；
①b 把交付换成另一条片子（3 秒 320x180 冒充 2 秒 1280x720）：verdict 转为假，假在长度与画幅，
   交回的实测数只能来自文件本身——计划里的数与文件里的数在这一道里是两个数；
② 目标响度点歪一个数（-30 对 -16）：verdict 转为假，`failed` 里就是 `loudness` 那一条，
   并且交回差了多少——不合格是一句答案，不是一次异常；
③ 文件被人删了：还是 200，verdict 假在 `file` 那一条，后面的量法明说无从下手（不掀桌）；
④ 契约面同源：`deliver_verify` 在 `TOOL_ENDPOINTS` 里、MCP 交出同一只，
   三条配方最后一步都是它——批量那一条也是一条一条读文件验，
   不给 `verify` 就不验，那一行会说清为什么。
"""
from __future__ import annotations

import asyncio
import shutil
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
PRESET = "h264-720p-web"
TOKEN = "deliverchk" + "f" * 53
FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:320]}")


def source(folder: Path) -> Path:
    target = folder / "talk.mp4"
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y", "-nostdin",
            "-f", "lavfi", "-i", "color=c=red:s=320x180:r=30:d=3",
            "-f", "lavfi", "-i", "sine=frequency=440:r=48000:d=3",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
            "-shortest", str(target),
        ],
        check=True, capture_output=True, timeout=600, creationflags=0x08000000,
    )
    return target


def client(folder: Path) -> TestClient:
    media = MediaService(folder / "dv-db.sqlite3", [folder], folder / "dv-cache",
                         FFMPEG, FFPROBE)
    jobs = JobRuntime(folder / "dv-api.sqlite3", FFMPEG, folder / "out", [folder / "out"])
    jobs.ensure_worker()
    app = create_app(folder / "dv-api.sqlite3", TOKEN, media=media, jobs=jobs)
    return TestClient(app, base_url="http://127.0.0.1",
                      headers={"Authorization": f"Bearer {TOKEN}"})


def one_delivery(hub: TestClient, folder: Path) -> dict:
    """一刀跑出那条交付，交回它的答案（含最后那一步的验收）。"""
    answer = hub.post(
        "/v1/agent/recipes/cut-from-media/run",
        json={
            "request_id": "dv-one",
            "name": "验一刀",
            "files": [str(source(folder))],
            "keep_ms": 2000,
            "min_silence_ms": 400,
            "loudness_target_lufs": -16.0,
            "preset_id": PRESET,
            "filename": "verified.mp4",
            "render": True,
            "wait_seconds": 90.0,
            "verify": True,
        },
    )
    check("一刀带着验收跑完", answer.status_code == 200, answer.text[:400])
    return answer.json() if answer.status_code == 200 else {}


def verify_leg(hub: TestClient, made: dict) -> None:
    """① 与 ② 直接叫那一扇门：一条真的、一条把目标点歪。"""
    job_id = (made.get("job") or {}).get("id")
    if not job_id:
        check("先要有一条交付作业", False, made.get("job"))
        return
    answer = hub.get(f"/v1/jobs/{job_id}/verify", params={"target_lufs": -16.0})
    check("验交付这扇门答了", answer.status_code == 200, answer.text[:300])
    body = answer.json()
    rows = {row["name"]: row for row in body.get("checks") or []}
    check("verdict 为真", body.get("verdict") is True, body)
    check("逐条都量了",
          {"status", "file", "duration", "resolution", "frame_rate", "loudness"} <= set(rows),
          sorted(rows))
    loud = rows.get("loudness") or {}
    dur = rows.get("duration") or {}
    res = rows.get("resolution") or {}
    rate = rows.get("frame_rate") or {}
    check("响度量的就是这个文件本身",
          loud.get("measured") is not None and abs(float(loud["measured"]) + 16.0) <= 1.5,
          loud)
    check("长度对这个作业自己的计划",
          dur.get("expected") == (made.get("plan") or {}).get("plan", {})
          .get("duration_seconds"), (dur, made.get("plan")))
    check("画幅与帧率对的是预设要的那一张",
          res.get("measured") == "1280x720" and rate.get("measured") == "30/1", (res, rate))
    print(f"   验交付：verdict={body.get('verdict')}，实测响度 {loud.get('measured')} LUFS，"
          f"长度 {dur.get('measured')} s（计划 {dur.get('expected')} s）")

    skewed = hub.get(f"/v1/jobs/{job_id}/verify", params={"target_lufs": -30.0}).json()
    off = [str(row.get("name")) for row in skewed.get("checks") or [] if not row.get("ok")]
    check("目标点歪就转为假，并点名是哪一条",
          skewed.get("verdict") is False and "loudness" in off, (skewed.get("verdict"), off))
    gap = next((row for row in skewed.get("checks") or []
                if row.get("name") == "loudness"), {})
    check("假的那条说得出差多少",
          bool(gap) and gap.get("measured") is not None
          and abs(abs(float(gap["measured"]) - float(gap["expected"])) - 14.0) <= 1.5, gap)
    check("把答案说歪不是抛异常（同一扇门的第二条路）",
          hub.get(f"/v1/jobs/{job_id}/verify",
                  params={"target_lufs": -16.0}).status_code == 200,
          "second read")


def recipe_row_leg(made: dict) -> None:
    """配方里最后那一格：一刀之内引擎自己验了，且验的就是这一条作业。"""
    rows = {row["step"]: row for row in made.get("steps") or []}
    row = rows.get("deliver_verify") or {}
    check("配方最后一步真跑了（偷偷跳过就红在这里）",
          row.get("ran") is True and row.get("all_ok") is True, row)
    verdicts = row.get("verdicts") or []
    check("验的就是这一条交付作业，答案逐条交回",
          len(verdicts) == 1 and verdicts[0]["job_id"] == (made.get("job") or {}).get("id"),
          row)


def mismatch_leg(hub: TestClient, folder: Path, made: dict) -> None:
    """把交付换成另一条片子：不合格的数字必须来自文件本身，不是来自计划。"""
    job = made.get("job") or {}
    path = Path(job.get("output_path") or "")
    if not job.get("id") or not path.is_file():
        check("这一道要有一条真交付才换得动", False, str(path))
        return
    backup = path.with_suffix(".keep")
    path.rename(backup)
    try:
        shutil.copyfile(folder / "talk.mp4", path)
        body = hub.get(f"/v1/jobs/{job['id']}/verify").json()
        rows = {row["name"]: row for row in body.get("checks") or []}
        failed = {row["name"] for row in body.get("checks") or [] if not row["ok"]}
        check("换了片子就转为假", body.get("verdict") is False, body.get("verdict"))
        check("假的是长度与画幅这两条", {"duration", "resolution"} <= failed, sorted(failed))
        dur = rows.get("duration") or {}
        res = rows.get("resolution") or {}
        check("交回的实测数就是从那一片子里读出来的",
              dur.get("measured") is not None and abs(float(dur["measured"]) - 3.0) <= 0.1
              and res.get("measured") == "320x180", (dur, res))
        check("期望那一张仍是作业自己计划里的",
              dur.get("expected") == (made.get("plan") or {}).get("plan", {})
              .get("duration_seconds") and res.get("expected") == "1280x720", (dur, res))
        print(f"   换一条片子冒充交付：verdict={body.get('verdict')}，假在 {sorted(failed)}，"
              f"实测长度 {dur.get('measured')} s")
    finally:
        # 冒充的那一片还占着那个路径，Windows 的 rename 不肯覆盖——Path.replace 才会。
        backup.replace(path)


def missing_file_leg(hub: TestClient, made: dict) -> None:
    """③ 文件不见了：还是 200，假在 `file` 那一条。"""
    job = made.get("job") or {}
    path = Path(job.get("output_path") or "")
    if not path.is_file():
        check("这一道要有那个文件才量得了", False, str(path))
        return
    backup = path.with_suffix(".bak")
    path.rename(backup)
    try:
        answer = hub.get(f"/v1/jobs/{job['id']}/verify")
        check("文件没了也不掀桌", answer.status_code == 200, answer.text[:300])
        body = answer.json()
        rows = {row["name"]: row for row in body.get("checks") or []}
        file_row = rows.get("file") or {}
        check("假在 file 那一条",
              body.get("verdict") is False and file_row.get("ok") is False, file_row)
        check("后面的量法明说无从下手", "container" in rows or "duration" not in rows,
              sorted(rows))
    finally:
        backup.rename(path)


def contract_leg() -> None:
    """④ 三面同源。"""
    entry = dict(agent_contract.TOOL_ENDPOINTS).get("deliver_verify")
    check("契约登记了这扇门", entry == ("GET", "/v1/jobs/{job_id}/verify"), entry)
    steps = {row["id"]: [s["tool"] for s in row["steps"]]
             for row in agent_contract.recipes()}
    check("三条配方最后一步都是它（批量那一条也一条一条验）",
          all(row[-1] == "deliver_verify" for row in steps.values()),
          {key: value[-1] for key, value in steps.items()})
    missing = [name for name in steps["cut-from-media"] if name not in recipe_run.RUNNERS]
    check("新增这一步有对应的人做", not missing, missing)
    server = create_mcp("http://127.0.0.1:0", "deliverchk" + "f" * 52)
    tools = {tool.name for tool in asyncio.run(server.list_tools())}
    check("MCP 也交出 deliver_verify", "deliver_verify" in tools, sorted(tools)[-6:])


def flag_leg(hub: TestClient, folder: Path) -> None:
    """`verify=false` 与 `render=false` 各说清自己没做。"""
    answer = hub.post(
        "/v1/agent/recipes/cut-from-media/run",
        json={
            "request_id": "dv-quiet",
            "name": "只到混音",
            "files": [str(folder / "talk.mp4")],
            "loudness_target_lufs": -18.0,
            "render": False,
            "verify": True,
        },
    )
    check("不排交付的这一刀也跑得完", answer.status_code == 200, answer.text[:400])
    if answer.status_code != 200:
        return
    rows = {row["step"]: row for row in (answer.json().get("steps") or [])}
    loud = rows.get("master_loudness") or {}
    verify_row = rows.get("deliver_verify") or {}
    check("混音那一步没被 render=false 顺手带走", loud.get("ran") is True, loud)
    check("没作业可验就明说",
          verify_row.get("ran") is False
          and "render=false" in str(verify_row.get("why")), verify_row)


def main() -> None:
    if not (FFMPEG.is_file() and FFPROBE.is_file()):
        raise SystemExit(f"缺随包二进制：{FFMPEG} / {FFPROBE}")
    folder = scratch.make("agentcut-deliver-")
    contract_leg()
    with client(folder) as hub:
        made = one_delivery(hub, folder)
        if made:
            recipe_row_leg(made)
            verify_leg(hub, made)
            mismatch_leg(hub, folder, made)
            missing_file_leg(hub, made)
        flag_leg(hub, folder)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: deliver_verify 用引擎自己的仪器验交付，不合格是一句带数字的答案")


if __name__ == "__main__":
    main()
