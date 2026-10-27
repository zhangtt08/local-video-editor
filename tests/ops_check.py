"""1.319 那一档：一次重启不许把流水线上的活丢掉，槽数与额度要说得出数。

企业把交付排成自动流水线之后，三件事必须有现场读数，而不是源码印象：

① **重启之后**：没开始过的那几单要接着排（它们一根手指都没动过，凭什么算失败），渲到一半的那一单
   才是真被打断——并且它的收据必须放开，同一个 `request_id` 重投要能渲出一个文件来。1.319 之前这两件
   事合成一句「都标 INTERRUPTED」，而收据还钉着那个死作业：一次重启，那条请求永远渲不出第二遍。
   开工前的量尺（`restartgap1319.py`）就是这么读的：六单全投进去、重启、再按同一批 `request_id` 重投
   ——六次 HTTP 200、六个 `same_dead_job`、零个新文件。
② **槽数**：`--render-slots` 说开几路就真有几条线程在拉活；0 与 99 这种数被夹回能用的范围。
③ **额度**：队列压满与被自己以前的单挡住，都在提交那一步按名字拒（`QUEUE_FULL`、`QUOTA_EXCEEDED`），
   点名还排几单、上限多少、这一趟要几单、是谁家的单子；**重放不占额度**——一次重试被队列挡回，
   调用方只会以为交付丢了；排空之后同一只手必须还投得进（反向腿）。
④ `GET /v1/info` 的 `queue` 那一格读的就是 runtime 自己那本数，不是文档里抄的第二份。
⑤ 那扇门不该因为「把 actor 传进 submit」就长出第二个 body 字段。

重启那一腿用的是**真重启**：起一支 `python -m agentcut api` 子进程、投三单、按 PID 连子树一起停掉，
再在同一个 sqlite 上按引擎开机的那条路重建 runtime。
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import scratch
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut import agent_contract  # noqa: E402
from agentcut.__main__ import database_path  # noqa: E402
from agentcut.contracts import RenderRequest  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import MAX_RENDER_SLOTS, JobRuntime  # noqa: E402
from agentcut.mcp_server import create_mcp  # noqa: E402
from agentcut.media import MediaService  # noqa: E402
from agentcut.projects import ProjectStore  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
PRESET = "h264-720p-web"
# 慢的那条腿要用得起「快照那一刻还有在跑的」：40 秒片子交竖屏那一档，一单要渲十几秒。
SLOW_PRESET = "h264-1080x1920-vertical"
TOKEN = "opscheck19" + "d" * 53
FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")


def source(folder: Path, seconds: int, noisy: bool = False) -> Path:
    """一条片子两种画法：纯色那一条渲得快，专门跑「排空之后还投得进」；带噪点那一条一单要渲十几秒，
    重启与额度那两腿要的就是「快照那一刻确实有在跑的、也有排队的」——纯色片在这台机器上 30 秒只渲
    四五秒，投完三单再读就已经全 succeeded 了（1.319 当场量到，所以才换成噪点）。"""
    target = folder / f"clip-{'noise' if noisy else 'flat'}-{seconds}.mp4"
    picture = f"color=c=green:s=1280x720:r=30:d={seconds}"
    if noisy:
        picture += ",noise=alls=35:allf=t"
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y", "-nostdin",
            "-f", "lavfi", "-i", picture,
            "-f", "lavfi", "-i", f"sine=frequency=440:r=48000:d={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-shortest", str(target),
        ],
        check=True, capture_output=True, timeout=600, creationflags=0x08000000,
    )
    return target


class Rig:
    """一个数据目录、一份 sqlite、若干台 runtime——额度腿与恢复腿共用同一本账。"""

    def __init__(self, folder: Path):
        self.folder = folder
        self.data_dir = folder / "engine"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.out = folder / "out"
        self.out.mkdir(parents=True, exist_ok=True)
        self.db = database_path(self.data_dir)
        self.media = MediaService(self.db, [folder], folder / "cache", FFMPEG, FFPROBE)
        self.store = ProjectStore(self.db, self.media)

    def runtime(self, **kwargs) -> JobRuntime:
        return JobRuntime(self.db, FFMPEG, self.out, [self.out], **kwargs)

    def request(self, index: int, revision: int, preset: str = PRESET,
                tag: str = "gen") -> RenderRequest:
        """每条腿用自己的 request_id 前缀：凭据表是整本库共享的，撞名就等于在重放别人的旧交付。

        这一条不是洁癖——1.319 写这条门禁时就让两条腿撞过 `ops-render-0`，结果「重启找回排队单」
        那一腿读到的 succeeded 其实是上一条腿留下的交付。
        """
        return RenderRequest(
            request_id=f"ops-{tag}-render-{index}",
            expected_revision=revision,
            preset_id=preset,
            filename=f"ops-{tag}-{index}.mp4",
        )


def seeded(rig: Rig, seconds: int, keep_ms: int, tag: str) -> tuple[str, int]:
    """建一条真能渲的时间线，交回工程 id 与 revision。

    两条片子是量出来的分工：`slow`（30 秒）一单要渲好几秒，重启与额度那两腿要的就是「快照那一刻
    确实有在跑的、也有排队的」；`fast`（4 秒）渲得快，专门用来跑「排空之后还投得进」那条反向腿。
    """
    jobs = rig.runtime()
    app = create_app(rig.db, TOKEN, media=rig.media, jobs=jobs)
    with TestClient(app, base_url="http://127.0.0.1",
                    headers={"Authorization": f"Bearer {TOKEN}"}) as hub:
        made = hub.post(
            "/v1/agent/recipes/cut-from-media/run",
            json={
                "request_id": f"ops-seed-{tag}", "name": f"额度这一档-{tag}",
                "files": [str(source(rig.folder, seconds, noisy=keep_ms >= 20000))],
                "keep_ms": keep_ms, "min_silence_ms": 400, "preset_id": PRESET,
                "filename": f"ops-seed-{tag}.mp4", "render": False,
            },
        )
        if made.status_code != 200:
            raise SystemExit(f"种子时间线（{tag}）就没建成：{made.status_code} {made.text[:300]}")
        body = made.json()
        return body["project_id"], body["revision"]


def drain(jobs: JobRuntime, seconds: float) -> bool:
    started = time.time()
    while time.time() - started < seconds:
        if jobs.pending_count() == 0:
            return True
        time.sleep(0.5)
    return jobs.pending_count() == 0


def wait_for(files: list[Path], seconds: float = 60.0) -> bool:
    started = time.time()
    while time.time() - started < seconds:
        if all(path.is_file() and path.stat().st_size > 0 for path in files):
            return True
        time.sleep(0.5)
    return False


def slots_leg(rig: Rig) -> None:
    """② 槽数：说几路就有几路，离谱的数夹回能用的范围。"""
    check("默认一槽（桌面端不该被顺手改成并发）", rig.runtime().slots == 1, "默认不是 1")
    check("槽数 0 夹回一", rig.runtime(slots=0).slots == 1, "0 没夹住")
    wide = rig.runtime(slots=99)
    check("槽数 99 夹到上限", wide.slots == MAX_RENDER_SLOTS, wide.slots)
    three = rig.runtime(slots=3)
    three.ensure_worker()
    names = sorted(thread.name for thread in three.workers if thread.is_alive())
    check("三槽真的起了三条线程", three.live_slots() == 3 and len(set(names)) == 3, names)
    check("线程名分得出是哪一路", all(n.startswith("agentcut-render-") for n in names), names)
    check("没起线程时 live_slots 说的是 0", rig.runtime(slots=2).live_slots() == 0, "虚报在跑")


def quota_leg(rig: Rig, slow: tuple[str, int], fast: tuple[str, int]) -> None:
    """③ 额度：压满与被自己挡住都按名字拒，排空之后必须还投得进。"""
    slow_id, slow_revision = slow
    fast_id, fast_revision = fast
    project = rig.store.get(slow_id)
    tight = rig.runtime(slots=1, max_pending=2)
    delivered: list[str] = []
    refused: Exception | None = None
    for index in range(3):
        try:
            job, _plan = tight.submit(
                project, rig.request(index, slow_revision, SLOW_PRESET, tag="tight"))
            delivered.append(job.id)
        except Exception as error:  # noqa: BLE001 —— 被拒就是要读的那一手
            refused = error
            break
    check("第三单被额度挡住", refused is not None, f"三单全排上了：{delivered}")
    if refused is not None:
        details = getattr(refused, "details", {}) or {}
        check("拒的那句点名还排几单、上限多少、这一趟要几单",
              getattr(refused, "code", "") == "QUEUE_FULL" and details.get("limit") == 2
              and details.get("incoming") == 1 and "pending" in details,
              (getattr(refused, "code", None), details))
        check("额度是 429 不是 500", getattr(refused, "status", None) == 429,
              getattr(refused, "status", None))
    emptied = drain(tight, 240.0)
    if refused is not None:
        # 队列压满的那一刻正是重试最容易撞上的时候：重放不许被额度挡住——被挡回的话调用方
        # 只会以为那一单交付丢了，而它其实好好地排在里面。
        try:
            again_full, _ = tight.submit(
                project, rig.request(0, slow_revision, SLOW_PRESET, tag="tight"))
            check("队列压满时重放照样拿回原来那一单", again_full.id == delivered[0],
                  (getattr(again_full, "id", None), delivered))
        except Exception as error:  # noqa: BLE001
            check("队列压满时重放被挡住了（重试不该占额度）", False,
                  (getattr(error, "code", None), getattr(error, "details", error)))
    check("先排的那几单渲完了（不然反向腿是空跑）", emptied,
          f"还有 {tight.pending_count()} 单没落")
    if emptied:
        # 反向腿用那条 4 秒的片子：额度是不是真会随交付落地而松开，只在一单渲完之后才看得出来。
        again, _ = tight.submit(rig.store.get(fast_id), rig.request(9, fast_revision, tag="tight"))
        check("排空之后同一只手还投得进", again.id not in delivered, again.id)
        check("额度那本数在 runtime 自己嘴里也一致", tight.pending_count() == 1,
              tight.pending_count())
        drain(tight, 240.0)

    shared = rig.runtime(slots=1, max_pending=8, pending_per_actor=1)
    a0, _ = shared.submit(project, rig.request(20, slow_revision, SLOW_PRESET, tag="actor"),
                       actor="pipeline-a")
    b0, _ = shared.submit(project, rig.request(21, slow_revision, SLOW_PRESET, tag="actor"),
                       actor="pipeline-b")
    check("别人家的单子不占这只令牌的名额", b0.id != a0.id, (a0.id, b0.id))
    blocked: Exception | None = None
    try:
        shared.submit(project, rig.request(22, slow_revision, SLOW_PRESET, tag="actor"),
                    actor="pipeline-a")
    except Exception as error:  # noqa: BLE001
        blocked = error
    details = getattr(blocked, "details", {}) or {}
    check("同一只令牌压第二单就被点名拒",
          getattr(blocked, "code", "") == "QUOTA_EXCEEDED" and details.get("actor") == "pipeline-a"
          and details.get("limit") == 1 and details.get("pending") == 1,
          (getattr(blocked, "code", None), details))
    replay = None
    try:
        replay, _ = shared.submit(project, rig.request(20, slow_revision, SLOW_PRESET, tag="actor"),
                                  actor="pipeline-a")
    except Exception as error:  # noqa: BLE001 —— 重放被额度挡住就是要报的那一手，不是让门禁崩
        check("重放被额度挡住了（重试不该占额度）", False,
              (getattr(error, "code", None), getattr(error, "details", error)))
    if replay is not None:
        check("重放不占额度：同一个 request_id 再投拿回的是原来那一单", replay.id == a0.id,
              (replay.id, a0.id))
    drain(shared, 240.0)


def start_engine(rig: Rig) -> tuple[subprocess.Popen, dict, str]:
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "agentcut", "api",
            "--data-dir", str(rig.data_dir), "--port", "0", "--json",
            "--render-slots", "1", "--max-queue", "8",
            "--media-root", str(rig.folder), "--output-dir", str(rig.out),
            "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE),
        ],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", env=env,
    )
    deadline = time.time() + 40.0
    ready: dict = {}
    while time.time() < deadline and not ready:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            if proc.poll() is not None:
                break
            continue
        if '"event": "ready"' in line:
            ready = json.loads(line)
    token = (rig.data_dir / "agentcut.token").read_text(encoding="utf-8").strip()
    return proc, ready, token


def stop_engine(proc: subprocess.Popen) -> None:
    """按 PID 连子树停掉——留在树上的那支 FFmpeg 会替我们把「重启」演成「没重启」。"""
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
        capture_output=True, timeout=30, creationflags=0x08000000,
    )
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=20)
    check("引擎进程真的停了", proc.poll() is not None, proc.poll())


def recovery_leg(rig: Rig, project_id: str, revision: int) -> None:
    """① 重启：没动过手的接着排，渲到一半的放开收据让人重投。

    两半各自都要**不靠时机**成立：A 半用一台不起线程的 runtime 把三单钉在 `queued`（这台 runtime 是
    测试侧的替身，产品代码一行没改），重启就该全部接回去并自己渲完；B 半用真子进程引擎，先等它真的
    进入 `running` 再投第二单、再当场按 PID 停掉——「在跑」是等来的，不是睡出来的。
    """
    silent = rig.runtime(slots=1)
    silent.ensure_worker = lambda: None
    queued_ids = [
        silent.submit(
            rig.store.get(project_id),
            rig.request(index, revision, SLOW_PRESET, tag="boot"),
        )[0].id
        for index in range(3)
    ]
    check("那三单都停在 queued（这台 runtime 故意不起线程）",
          {silent.get(job_id).status for job_id in queued_ids} == {"queued"},
          {job_id: silent.get(job_id).status for job_id in queued_ids})

    restarted = rig.runtime(slots=1)
    check("开机当场把三单交回队列", sorted(restarted.requeued) == sorted(queued_ids),
          (restarted.requeued, queued_ids))
    check("交回来的状态还是 queued，没被算成失败",
          all(restarted.get(job_id).status in ("queued", "running", "succeeded")
              for job_id in queued_ids),
          {job_id: restarted.get(job_id).status for job_id in queued_ids})
    check("三单没人再投也自己渲完了",
          wait_for([rig.out / f"ops-boot-{index}.mp4" for index in range(3)]),
          sorted(path.name for path in rig.out.glob("*.mp4")))

    proc, ready, token = start_engine(rig)
    check("子进程引擎起来了并交回 ready 行", ready.get("port"), ready)
    check("ready 行说得出槽数与额度",
          ready.get("slots") == 1 and ready.get("max_queue") == 8,
          {k: ready.get(k) for k in ("slots", "max_queue", "queue_per_token", "requeued")})
    with httpx.Client(base_url=ready.get("base_url", ""),
                      headers={"Authorization": f"Bearer {token}"}, timeout=30.0) as api:
        live = api.post(
            f"/v1/projects/{project_id}/renders",
            json={"request_id": "ops-live-1", "expected_revision": revision,
                  "preset_id": SLOW_PRESET, "filename": "ops-live-1.mp4"},
        )
        live_id = (live.json().get("job") or {}).get("id")
        deadline = time.time() + 30.0
        seen = ""
        while time.time() < deadline:
            seen = api.get(f"/v1/jobs/{live_id}").json().get("job", {}).get("status")
            if seen == "running":
                break
            time.sleep(0.1)
        check("先等到的确是在跑的那一单（等不到就别假装重启过）", seen == "running", seen)
        parked = api.post(
            f"/v1/projects/{project_id}/renders",
            json={"request_id": "ops-live-2", "expected_revision": revision,
                  "preset_id": SLOW_PRESET, "filename": "ops-live-2.mp4"},
        )
        parked_id = (parked.json().get("job") or {}).get("id")
        parked_state = api.get(f"/v1/jobs/{parked_id}").json().get("job", {}).get("status")
        check("第一单还在跑的时候，第二单确实排在后面", parked_state == "queued", parked_state)
    stop_engine(proc)

    revived = rig.runtime(slots=1)
    check("在跑那一单交回的就是 INTERRUPTED",
          (revived.get(live_id).status, revived.get(live_id).error_code)
          == ("failed", "INTERRUPTED"),
          (revived.get(live_id).status, revived.get(live_id).error_code))
    check("那一单的收据被放开（还钉着就永远渲不出第二遍）",
          revived._receipt_job_id("ops-live-1") is None, revived._receipt_job_id("ops-live-1"))
    check("排队那一单被重新入队", parked_id in revived.requeued, (parked_id, revived.requeued))
    replay = None
    try:
        replay = revived.submit(
            rig.store.get(project_id),
            RenderRequest(request_id="ops-live-1", expected_revision=revision,
                          preset_id=SLOW_PRESET, filename="ops-live-1-revived.mp4"))
    except Exception as error:  # noqa: BLE001 —— 收据没放开就是这个样子，得报出来而不是崩在这里
        check("重投被原来的凭据挡住（收据没放开就是这样）", False,
              (getattr(error, "code", None), getattr(error, "details", error)))
    if replay is not None:
        check("同一个 request_id 重投拿到的是新作业", replay[0].id != live_id,
              (replay[0].id, live_id))
        check("重投与找回的那两单都真渲出了文件",
              wait_for([rig.out / "ops-live-2.mp4", rig.out / "ops-live-1-revived.mp4"]),
              sorted(path.name for path in rig.out.glob("ops-live*.mp4")))
        check("重投这一单自己又写下了凭据",
              revived._receipt_job_id("ops-live-1") == replay[0].id,
              revived._receipt_job_id("ops-live-1"))
    drain(revived, 180.0)



def info_leg(rig: Rig, project_id: str, revision: int) -> None:
    """④ /v1/info 的 queue 那一格读的就是 runtime 自己那本数。"""
    jobs = rig.runtime(slots=2, max_pending=7, pending_per_actor=3)
    app = create_app(rig.db, TOKEN, media=rig.media, jobs=jobs)
    with TestClient(app, base_url="http://127.0.0.1",
                    headers={"Authorization": f"Bearer {TOKEN}"}) as hub:
        info = hub.get("/v1/info").json()
        queue = info.get("queue") or {}
        check("info 里有 queue 这一格", queue, sorted(info))
        check("槽数与额度与 runtime 自己的一致",
              queue.get("slots") == jobs.slots == 2 and queue.get("max_pending") == 7
              and queue.get("pending_per_actor") == 3
              and queue.get("pending") == jobs.pending_count(), (queue, jobs.slots))
        check("重启找回来的那几单也说得出数", queue.get("requeued") == len(jobs.requeued), queue)
        made = hub.post(
            f"/v1/projects/{project_id}/renders",
            json={"request_id": "ops-info-1", "expected_revision": revision,
                  "preset_id": SLOW_PRESET, "filename": "ops-info.mp4"},
        )
        check("经 HTTP 投单渲得动", made.status_code == 200, made.text[:200])
        after = hub.get("/v1/info").json().get("queue") or {}
        check("投完一眼再看，待渲数还是与 runtime 那本数一致",
              after.get("pending") == jobs.pending_count() and after.get("pending") >= 1,
              (after, jobs.pending_count()))
        check("经 HTTP 投的那单记在投单者名下",
              jobs.job_actor.get((made.json().get("job") or {}).get("id")) == "local",
              jobs.job_actor)
        drain(jobs, 180.0)


def contract_leg() -> None:
    """⑤ 那扇门不该因为多了个 actor 参数就长出新东西：参数表与 MCP 入参逐字照旧。"""
    params = agent_contract.route_params(create_app(Path("unused.sqlite3"), TOKEN))
    for route in ("/v1/projects/{project_id}/renders",
                  "/v1/projects/{project_id}/renders/batch"):
        split = params.get(("POST", route)) or {}
        check(f"{route} 的参数表还是「路径一条、载荷一份」",
              split == {"path": ["project_id"], "query": [], "body": ["request"]}, split)
    server = create_mcp("http://127.0.0.1:0", "opscheck19" + "d" * 52)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    schema = (tools["render_start"].inputSchema if "render_start" in tools else {}) or {}
    props = sorted(schema.get("properties") or {})
    check("render_start 的入参还是 project_id 与那一份载荷", props == ["project_id", "request"],
          props)


def main() -> None:
    folder = scratch.make("agentcut-ops-")
    rig = Rig(folder)
    slow = seeded(rig, 20, 20000, "slow")
    fast = seeded(rig, 4, 4000, "fast")
    slots_leg(rig)
    quota_leg(rig, slow, fast)
    recovery_leg(rig, slow[0], slow[1])
    info_leg(rig, slow[0], slow[1])
    contract_leg()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: 重启找回排队交付并放开中断那单的收据、槽数与额度都说得出数、投单按名字拒")


if __name__ == "__main__":
    main()
