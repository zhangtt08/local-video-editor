"""1.310：agent 排队交付之后不该一秒打一次——`job_wait` 一次调用等到终态。

这一手抄的是两台大家都用的服务的做法：Kubernetes 的 `watch=true` 与 `gh run watch`
把「等到它跑完」放在服务端。本仓库自己的门禁就是反例：`tests/alphamaster_check.py` 的
`wait()` 最多轮 1200 次才认输——连量具都在手写这个循环，agent 每次交付都得自己写一遍。

六道，每一道都能红：
① 契约面登记与派发：`job_wait` 在 `TOOL_ENDPOINTS` 里，`resolve()` 把 job_id 放进路径、
   timeout/poll 留在查询——放错地方这条就红；
② 一次真渲染：一次 `GET /v1/jobs/{id}/wait?timeout=90` 到 `succeeded`，交回同一份 job 文档
   （`job` + `plan` 两个键都在），输出文件真的在，ffprobe 量到的长度对上片段；
③ 超时不是错误：`timeout=0.05` 那一次说 `timed_out=true`，而作业没被影响——换一次长等仍到终态；
④ 不存在的 job 按 NOT_FOUND 拒（404），`timeout` 越界按 422 拒——不让人把服务端挂住；
⑤ MCP 那一侧同源：`create_mcp()` 交出的工具表里也有 `job_wait`，与 HTTP 同一份契约；
⑥ 配方指的就是它：三条剪辑配方里那一步现在写 `job_wait`，不再是让人自己轮。
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

from agentcut import agent_contract  # noqa: E402
from agentcut.contracts import TIMEBASE as T  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.mcp_server import create_mcp  # noqa: E402
from agentcut.media import MediaService  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TERMINAL = {"succeeded", "failed", "cancelled"}
FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:300]}")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def offline_surface() -> None:
    """① 契约登记与派发：路径参数与查询参数各就各位。"""
    table = dict(agent_contract.TOOL_ENDPOINTS.items())
    check("契约登记了 job_wait 的路由", table.get("job_wait") == ("GET", "/v1/jobs/{job_id}/wait"),
          table.get("job_wait"))
    method, path, query, body = ("", "", {}, None)
    try:
        method, path, query, body = agent_contract.resolve(
            "job_wait", {"job_id": "j01", "timeout": 12.5, "poll": 0.5}, {}
        )
    except KeyError as error:  # 没登记的那一只：报成断言，不掀桌
        check("job_wait 派得出路由（没登记就是这一条红）", False, repr(error))
    check("job_id 进路径", method == "GET" and path == "/v1/jobs/j01/wait", (method, path))
    check("timeout/poll 留在查询参数里", query == {"timeout": 12.5, "poll": 0.5}, query)
    check("wait 不带 body", body is None, body)


def mcp_surface() -> None:
    """⑤ MCP 那一侧同源：同一份契约，两只门面。"""
    server = create_mcp("http://127.0.0.1:0", "jobwaitchk" + "f" * 53)
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    jobs = sorted(name for name in names if name.startswith("job_"))
    check("MCP 也交出 job_wait", "job_wait" in names, jobs)


def recipes_point_at_it() -> None:
    """⑥ 配方不引用幽灵工具，也确有这一只。"""
    listed = {row["tool"] for recipe in agent_contract.recipes() for row in recipe["steps"]}
    check("配方那一步写的是 job_wait", "job_wait" in listed, sorted(listed))


def live(folder: Path) -> None:
    if not (FFMPEG.is_file() and FFPROBE.is_file()):
        check("随包 ffmpeg/ffprobe 在场才能量真交付", False, f"{FFMPEG} / {FFPROBE}")
        return
    service = MediaService(folder / "jw-db.sqlite3", [folder], folder / "jw-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(folder / "jw-api.sqlite3", FFMPEG, folder / "out", [folder / "out"])
    runtime.ensure_worker()
    token = "jobwaitchk" + "f" * 52
    app = create_app(folder / "jw-api.sqlite3", token, media=service, jobs=runtime)
    clip = folder / "waitsrc.mp4"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-nostdin", "-f", "lavfi",
         "-i", "testsrc2=size=320x180:rate=30:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)],
        check=True, capture_output=True, timeout=600, creationflags=0x08000000,
    )
    with TestClient(app, base_url="http://127.0.0.1",
                    headers={"Authorization": f"Bearer {token}"}) as client:
        verified = client.post("/v1/media/import", json={"path": str(clip)}).json()["verified"]
        made = client.post("/v1/projects",
                           json={"request_id": "jw-new", "name": "等一台交付"})
        pid = made.json()["project"]["id"]
        edited = client.post(f"/v1/projects/{pid}/edits", json={
            "request_id": "jw-seed", "expected_revision": 0,
            "commands": [
                {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
                {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "声音"}},
                {"op": "asset.import", "asset_id": "asset1", "label": "waitsrc",
                 "probe_id": verified["probe_id"], "verified": verified},
                {"op": "clip.add", "clip": {"id": "cv", "asset_id": "asset1", "track_id": "v",
                                            "position_ticks": 0, "source_in_ticks": 0,
                                            "duration_ticks": 2 * T}},
                {"op": "clip.add", "clip": {"id": "ca", "asset_id": "asset1", "track_id": "a",
                                            "position_ticks": 0, "source_in_ticks": 0,
                                            "duration_ticks": 2 * T}},
            ],
        }).json()
        revision = edited["project"]["revision"]
        presets = client.get("/v1/render-presets").json()["presets"]
        preset = next((row["id"] for row in presets if row["id"] == "h264-source-quality"),
                      presets[0]["id"])

        def start(tag: str) -> str:
            reply = client.post(f"/v1/projects/{pid}/renders", json={
                "request_id": tag, "expected_revision": revision,
                "preset_id": preset, "filename": tag + ".mp4"})
            check("排队交付被接了", reply.status_code == 200, reply.text[:300])
            return str((reply.json().get("job") or {}).get("id", ""))

        # ② 一次调用等到终态，交回的还是同一份 job 文档。
        job_id = start("jw-wait")
        answer = client.get(f"/v1/jobs/{job_id}/wait", params={"timeout": 90}).json()
        job = answer.get("job") or {}
        check("一次 wait 就到终态", job.get("status") == "succeeded", answer)
        check("到了就别说超时", answer.get("timed_out") is False, answer.get("timed_out"))
        waited = answer.get("waited_ms")
        check("量得出等了多久", isinstance(waited, int) and waited >= 0, waited)
        check("plan 这一格没丢（在飞的作业带着计划）", "plan" in answer, sorted(answer))
        check("输出自己核过", job.get("output_checked") is True, job)
        out = Path(job.get("output_path") or "")
        if out.is_file():
            seconds = probe_duration(out)
            check("交付的长度就是片段那 2 秒", 1.7 <= seconds <= 2.3, seconds)
        else:
            check("交付文件在盘上", False, str(out))

        # ③ 超时不是错误：那一次说 timed_out，作业本身不受影响。
        second = start("jw-timeout")
        quick = client.get(f"/v1/jobs/{second}/wait", params={"timeout": 0.05, "poll": 0.05}).json()
        check("等不到就说 timed_out，不装作失败",
              quick.get("timed_out") is True and quick["job"]["status"] in {"queued", "running"},
              quick)
        again = client.get(f"/v1/jobs/{second}/wait", params={"timeout": 90}).json()
        check("再等一次仍到终态（等不影响作业）", again["job"]["status"] in TERMINAL, again)

        # ④ 两条拒绝：不存在的 job，与想把服务端挂住的越界 timeout。
        missing = client.get("/v1/jobs/doesnotexist/wait", params={"timeout": 1})
        missing_code = (missing.json().get("error") or {}).get("code")
        check("查不到的 job 按 NOT_FOUND 拒",
              missing.status_code == 404 and missing_code == "NOT_FOUND", missing.text[:200])
        greedy = client.get(f"/v1/jobs/{job_id}/wait", params={"timeout": 99999})
        check("timeout 越界被 422 拒", greedy.status_code == 422, greedy.text[:200])


def main() -> None:
    offline_surface()
    mcp_surface()
    recipes_point_at_it()
    live(scratch.make("agentcut-jobwait-"))
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: job_wait 一只工具、三面同源；一次调用等到交付终态，超时说 timed_out，越界被拒")


if __name__ == "__main__":
    main()
