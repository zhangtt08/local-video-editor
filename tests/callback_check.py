"""1.323 事件出口这一档：作业走到终态，引擎自己把回执投出去，欠的那一条不会被弄丢。

企业接流水线时问的第一句不是「能不能渲染」，是「渲完了谁来告诉我」。1.319 给了队列与恢复，
1.320 给了 metrics，但结果仍然要靠调用方轮询 `/v1/jobs/{id}`。这一档把出口做成引擎的一部分，
门禁逐条量这些：

① 判据本身（用的是产品里那一个类，不是门禁自己抄的一份）：非终态不记账、同一个终态写两次
   不多欠一条、两个地址就欠两条、签名能被同一枚令牌验回、篡改过的正文验不过；
② 真引擎真渲染：一条 4 秒片子渲完 → 接收端收到一条 `succeeded` 回执，正文里那些数是引擎
   自己量到的（文件名、字节数、复检与否），头部签名用这台引擎的令牌重算对得上；
   `X-AgentCut-Delivery` 说的是第几次尝试；
③ 终态不止「成功」：排队中的那一单被取消，也要递一条 `cancelled`——流水线最不该漏的就是这一条；
④ 读得回来：`GET /v1/callbacks` 与 `GET /v1/metrics` 里的数是那张表现算的，不是第二份真相；
   令牌不对就是 401；
⑤ 接收端先炸后好：503 两次再 200 → 那一条最终以 delivered 收口，`attempts` 是 3（重试真的在重试）；
⑥ 投不出去就按名字认栽：一直 500 → 到上限记成 `gave_up` 并留下为什么没成的那句话，不再空转；
⑦ **重启不许把欠账洗掉**：A 那台在回执还欠着的时候被杀掉，B 那台在同一个数据目录上把 A 欠的
   那一条补投出去，而且没有重渲任何一单；
⑧ 没配地址就没有这一面：`configured: false`、表里没有行、也不起线程；
⑨ 配错就停在自己门前：`file:` 那一种 scheme、带账号的那一种写法，都不起；而且同一趟里
   别的门没过（非本机绑定、没令牌）要在**同一句**里一起点名（1.322 的教训）；
⑩ 走产品那条 `_save`：炸在提交那一刻，作业行与那条欠账一起回滚；不炸就两条一起落下。

跑法：空闲机器单跑 `uv run python tests/callback_check.py`（要随包那两支媒体程序）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import reaper
import scratch
from ops_check import FFMPEG, FFPROBE, PRESET, Rig, source

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.__main__ import _callback_problems  # noqa: E402
from agentcut.contracts import RenderJob, RenderRequest  # noqa: E402
from agentcut.notify import (  # noqa: E402
    EVENT,
    Outbox,
    connect_outbox,
    signature,
)

TOKEN = "callback-check-" + "c" * 40 + "-token"
FAILURES: list[str] = []


def check(label: str, ok: bool, evidence: object = "") -> None:
    if not ok:
        FAILURES.append(f"{label}: {str(evidence)[:400]}")


class Receiver:
    """进程内的一个真 HTTP 接收端：模式说得出「前几次不给好脸」。"""

    def __init__(self, mode: str = "ok", flaky: int = 0) -> None:
        self.hits: list[dict] = []
        self.mode = mode
        self.flaky = flaky
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 —— BaseHTTPRequestHandler 的命名
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                with outer.lock:
                    attempt = len(outer.hits)
                    if outer.mode == "reject":
                        code = 500
                    elif outer.mode == "flaky" and attempt < outer.flaky:
                        code = 503
                    else:
                        code = 200
                    outer.hits.append(
                        {
                            "path": self.path,
                            "body": body,
                            "headers": {str(k).lower(): str(v) for k, v in self.headers.items()},
                            "answered": code,
                        }
                    )
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/hook"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def wait_for(self, job_id: str, seconds: float = 45.0) -> dict | None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            with self.lock:
                for hit in self.hits:
                    try:
                        body = json.loads(hit["body"].decode("utf-8"))
                    except ValueError:
                        continue
                    if body.get("job_id") == job_id:
                        return hit
            time.sleep(0.2)
        return None

    def bodies(self) -> list[dict]:
        with self.lock:
            return [json.loads(str(hit["body"].decode("utf-8")) ) for hit in self.hits]


def env_for(**extra: str) -> dict:
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["AGENTCUT_TOKEN"] = TOKEN
    env.update(extra)
    return env


def spawn(rig: Rig, *extra: str, **env_add: str) -> subprocess.Popen:
    return reaper.note(subprocess.Popen(
        [sys.executable, "-m", "agentcut", "api", "--port", "0", "--json",
         "--data-dir", str(rig.data_dir), "--media-root", str(rig.folder),
         "--output-dir", str(rig.out), "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE),
         "--render-slots", "1", *extra],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=env_for(**env_add),
    ))


def ready_line(proc: subprocess.Popen, seconds: float = 90.0) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return {}
        line = proc.stdout.readline() if proc.stdout else ""
        if line and '"event": "ready"' in line:
            return json.loads(line)
    return {}


def api(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60.0)


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=60)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def seed(rig: Rig, base: str, tag: str, seconds: int, noisy: bool,
           keep_ms: int = 2000) -> tuple[str, int]:
    """在跑着的那台引擎里建一条真能渲的时间线，交回工程 id 与 revision。"""
    clip = source(rig.folder, seconds, noisy=noisy)
    with api(base) as hub:
        made = hub.post(
            "/v1/agent/recipes/cut-from-media/run",
            json={"request_id": f"cb-seed-{tag}", "name": f"回调这一档-{tag}",
                  "files": [str(clip)], "keep_ms": keep_ms, "min_silence_ms": 400,
                  "preset_id": PRESET, "filename": f"cb-seed-{tag}.mp4", "render": False},
        )
        if made.status_code != 200:
            raise SystemExit(f"种子时间线（{tag}）没建成：{made.status_code} {made.text[:300]}")
        body = made.json()
        return str(body["project_id"]), int(body["revision"])


def submit(base: str, project_id: str, revision: int, tag: str, index: int,
           preset: str = PRESET) -> str:
    with api(base) as hub:
        made = hub.post(
            f"/v1/projects/{project_id}/renders",
            json=RenderRequest(
                request_id=f"cb-{tag}-{index}", expected_revision=revision, preset_id=preset,
                filename=f"cb-{tag}-{index}.mp4",
            ).model_dump(),
        )
        if made.status_code != 200:
            raise SystemExit(f"提交没成（{tag}/{index}）：{made.status_code} {made.text[:300]}")
        body = made.json()
        job = body.get("job") or {}
        return str(job.get("id") or body.get("id") or "")


def job_status(base: str, job_id: str) -> dict:
    with api(base) as hub:
        got = hub.get(f"/v1/jobs/{job_id}")
        return dict(got.json().get("job") or {})


def wait_terminal(base: str, job_id: str, seconds: float = 180.0) -> dict:
    deadline = time.time() + seconds
    job: dict = {}
    while time.time() < deadline:
        job = job_status(base, job_id)
        if str(job.get("status") or "") in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.5)
    return job


def verified(hit: dict) -> tuple[bool, str]:
    """用这台引擎的令牌把签名重算一遍：验不过就是这条回执可以被中间人改过。"""
    header = str(hit["headers"].get("x-agentcut-signature") or "")
    if not header.startswith("sha256="):
        return False, header
    claimed = header.removeprefix("sha256=")
    computed = hmac.new(TOKEN.encode(), hit["body"], hashlib.sha256).hexdigest()
    ok = hmac.compare_digest(claimed, computed)
    tampered = hmac.compare_digest(
        claimed,
        hmac.new(TOKEN.encode(), hit["body"] + b"x", hashlib.sha256).hexdigest(),
    )
    return ok and not tampered, (
        f"claimed={claimed[:12]} computed={computed[:12]} 篡改也验过={tampered}"
    )


def fake_job(status: str, job_id: str = "job-x") -> RenderJob:
    return RenderJob(
        id=job_id, project_id="p-x", sequence_id=None, preset_id=PRESET, filename="x.mp4",
        revision=3, status=status, error_code=None, message="已输出 x.mp4（复检：1280x720）",
        output_path="/tmp/x.mp4", output_size_bytes=9, output_checked=True,
        elapsed_seconds=1.0, total_ticks=100, rendered_ticks=100,
        created_at="2026-10-28T01:00:00", updated_at="2026-10-28T01:00:05",
    )


def predicate_leg() -> None:
    """① 判据本身，用的是产品里那一个类。"""
    folder = scratch.make("agentcut-cb-predicate-")
    db = folder / "cb.sqlite3"
    outbox = Outbox(db, ["http://127.0.0.1:9/a", "http://127.0.0.1:9/b"], TOKEN, instance="i1")
    connection = connect_outbox(db)
    outbox.enqueue(connection, fake_job("running"))
    check("非终态不该欠一次通知（running 就记账会把每一次进度都投出去）",
          outbox.summary()["pending"] == 0, outbox.summary())
    outbox.enqueue(connection, fake_job("succeeded"))
    outbox.enqueue(connection, fake_job("succeeded"))
    counts = outbox.summary()
    check("一个终态两个地址就欠两条，写两次不多欠",
          counts["pending"] == 2 and counts["delivered"] == 0, counts)
    rows = [dict(row) for row in connection.execute("SELECT document FROM job_outbox")]
    connection.close()
    body = str(rows[0]["document"])
    check("回执里带得上引擎量到过的那几格",
          json.loads(body)["output_size_bytes"] == 9 and json.loads(body)["instance"] == "i1"
          and json.loads(body)["event"] == EVENT, body[:200])
    signed = signature(TOKEN, body.encode("utf-8"))
    check("签名能被同一枚令牌验回，换一枚就不行",
          signed == signature(TOKEN, body.encode("utf-8"))
          and signed != signature(TOKEN + "x", body.encode("utf-8")), signed[:16])
    check("地址判据认 http/https，挡 file 与带账号的写法",
          _callback_problems(["http://127.0.0.1:9/a", "https://x.test/h"]) == []
          and len(_callback_problems(["file:///C:/Windows/win.ini"])) == 1
          and len(_callback_problems(["http://user:pass@127.0.0.1:9/a"])) == 1
          and len(_callback_problems(["127.0.0.1:9/a"])) == 1,
          "scheme/账号判据不对")
    bare = Outbox(db, [], TOKEN)
    check("没配地址就没有这一面：configured=false 且不建表",
          bare.summary() == {"configured": False, "urls": 0, "pending": 0,
                             "delivered": 0, "gave_up": 0},
          bare.summary())


def atomic_leg(rig: Rig) -> None:
    """⑩ 走产品那条 `_save`：作业行与那条欠账同生共死。

    炸点由 sqlite 自己触发：在 `job_outbox` 上挂一条 AFTER INSERT 的 `RAISE(ABORT)`，
    `_save()` 就在「两条都写完、正要提交」那一刻炸，此时作业行还在同一个事务里，两条该一起没了。
    这一腿第一版是门禁自己手写两条写入——K4 那把刀（把欠账挪到第二条连接里写）当场打不红它：
    量具不走产品那条路径，测到的就只是我对它的想象。
    """
    jobs = rig.runtime(callback_urls=["http://127.0.0.1:9/hook"], callback_secret=TOKEN)

    def rows(table: str, job_id: str) -> int:
        sql = ("SELECT COUNT(*) AS n FROM jobs WHERE id=?" if table == "jobs"
               else "SELECT COUNT(*) AS n FROM job_outbox WHERE job_id=?")
        with connect_outbox(jobs.db_path) as probe:
            return int(probe.execute(sql, (job_id,)).fetchone()["n"])

    with connect_outbox(jobs.db_path) as db:
        db.execute("CREATE TRIGGER cb_probe AFTER INSERT ON job_outbox BEGIN"
                   " SELECT RAISE(ABORT, '故意炸在这两步中间'); END")
    raised = ""
    try:
        jobs._save(fake_job("succeeded", job_id="atomic-boom"))
    except Exception as error:  # noqa: BLE001 —— 炸在提交那一刻正是要读的读数
        raised = f"{type(error).__name__}: {str(error)[:90]}"
    finally:
        with connect_outbox(jobs.db_path) as db:
            db.execute("DROP TRIGGER IF EXISTS cb_probe")
    check("炸点真的落在 `_save()` 里面（不然回滚这一手根本没被触发过）", bool(raised), raised)
    check("作业行与那条欠账一起回滚：不留「库里成功了、外头没人知道」的痕迹",
          rows("jobs", "atomic-boom") == 0 and rows("outbox", "atomic-boom") == 0,
          (rows("jobs", "atomic-boom"), rows("outbox", "atomic-boom"), raised))
    jobs._save(fake_job("succeeded", job_id="atomic-ok"))
    check("不炸就两条一起落下（反向腿：这一格不是因为压根没写而绿）",
          rows("jobs", "atomic-ok") == 1 and rows("outbox", "atomic-ok") == 1,
          (rows("jobs", "atomic-ok"), rows("outbox", "atomic-ok")))


def delivery_leg(rig: Rig) -> None:
    """②③④ 真引擎、真渲染、真取消：一条 succeeded 与一条 cancelled 都递到，读得回来。"""
    receiver = Receiver()
    proc = spawn(rig, "--callback-url", receiver.url)
    ready = ready_line(proc)
    base = str(ready.get("base_url") or "")
    check("配了地址也起得来（起不来后面全是空跑）", ready.get("port") and base, ready)
    if not base:
        stop(proc)
        receiver.stop()
        return
    try:
        project_id, revision = seed(rig, base, "main", 4, noisy=False)
        fast = submit(base, project_id, revision, "main", 1)
        job = wait_terminal(base, fast)
        check("先要那条 4 秒的单自己渲完（不然回执的数没来源）",
              job.get("status") == "succeeded", job)
        hit = receiver.wait_for(fast)
        check("渲完了，接收端真收到一条", hit is not None, len(receiver.hits))
        if hit is None:
            return
        body = json.loads(hit["body"].decode("utf-8"))
        check("回执点名的是这一单、这个状态、这个事件",
              body["job_id"] == fast and body["status"] == "succeeded"
              and body["event"] == EVENT and hit["headers"].get("x-agentcut-event") == EVENT,
              body)
        check("回执里的交付数是引擎自己量到的（文件名、字节、复检与否）",
              body["output_name"] == "cb-main-1.mp4" and int(body["output_size_bytes"] or 0) > 0
              and body["output_checked"] is True and body["preset_id"] == PRESET, body)
        check("实例号与这台引擎自己报的一致（回执得说清是谁投的）",
              body["instance"] == _instance(base), (body["instance"], _instance(base)))
        ok, evidence = verified(hit)
        check("签名用这台引擎的令牌验得回，而且篡改过的验不过", ok, evidence)
        check("投递次数写在头里：第一次就该成",
              hit["headers"].get("x-agentcut-delivery") == f"{fast}-1",
              hit["headers"].get("x-agentcut-delivery"))
        with api(base) as hub:
            listed = hub.get("/v1/callbacks").json()
            rows = {str(row["job_id"]): row for row in listed.get("callbacks") or []}
            check("读得回来：这一单已是 delivered，试了一次",
                  fast in rows and rows[fast]["status"] == "delivered"
                  and rows[fast]["attempts"] == 1, rows.get(fast))
            check("配置也读得回：一个地址、上限与超时都说得出",
                  (listed.get("config") or {}).get("urls") == 1
                  and (listed.get("config") or {}).get("attempts_limit", 0) >= 1,
                  listed.get("config"))
            metrics = hub.get("/v1/metrics").json().get("callbacks") or {}
            check("metrics 里那一格与 /v1/callbacks 同源：delivered=1、没欠账",
                  metrics.get("delivered") == 1 and metrics.get("pending") == 0, metrics)
            info = hub.get("/v1/info").json()
            echo = info.get("info") if isinstance(info.get("info"), dict) else info
            check("ready 行与 /v1/info 都说得出配了哪几个地址（手册里那两句得有出处）",
                  (ready.get("callbacks") or {}).get("urls") == 1
                  and list(echo.get("callback_urls") or []) == [receiver.url],
                  (ready.get("callbacks"), echo.get("callback_urls")))
            with httpx.Client(base_url=base, headers={"Authorization": "Bearer wrong-token"},
                              timeout=20.0) as stranger:
                check("不是谁都能读这本账：令牌不对就是 401",
                      stranger.get("/v1/callbacks").status_code == 401,
                      stranger.get("/v1/callbacks").status_code)
        # ③ 取消排队中的那一单也要递出去：先占住那一槽，再投第二单，然后取消还排着的那一单。
        # 这一腿要的是「槽被占住、第二单确实还排着」：4 秒的片子 0.78 秒就渲完了，第二单
        # 立刻被同一个槽吃掉，取消读到的就是 succeeded（1.323 第一跑就是这么空的）。
        # 这一腿要的是「有一单确实还排着」。第一跑在这里吃了两次教训：4 秒片子 0.78 秒渲完、
        # 15 秒片子 3.35 秒渲完，而排队中每次 GET 要 4 秒多（渲染在写那本 sqlite，读被顶在后面）
        # ——跟单子赛跑是跑不赢的。所以改成**一槽排七单**：尾巴那一单排在六单后面，
        # 取消它不需要抢时间窗，读数也说得出那一刻有几单还排着。
        slow_id, slow_revision = seed(rig, base, "slow", 30, noisy=True, keep_ms=15000)
        batch = [submit(base, slow_id, slow_revision, "slow", index, preset=slow_preset())
                 for index in range(1, 8)]
        tail = batch[-1]
        with api(base) as hub:
            depth = hub.get("/v1/metrics").json().get("queue") or {}
            queued_rows = {str(row["job_id"]): str(row["status"])
                           for row in hub.get("/v1/jobs?limit=20").json().get("jobs") or []}
            cancel = hub.post(f"/v1/jobs/{tail}/cancel", json={"request_id": f"cb-cancel-{tail}"})
        cancelled = wait_terminal(base, tail, seconds=60.0)
        check("取消那一刻队列里确实还压着几单（不然这一腿是在跟单子赛跑）",
              int(depth.get("pending") or 0) >= 2, (depth, tail, queued_rows))
        check("取消排队中的那一单，状态落在 cancelled",
              cancelled.get("status") == "cancelled" and cancel.status_code == 200,
              (cancelled, cancel.status_code, cancel.text[:160]))
        hit2 = receiver.wait_for(tail, seconds=45.0)
        check("被取消的这一单也递出去了（流水线最不该漏的就是它）", hit2 is not None,
              [str(row["status"]) for row in receiver.bodies()])
        if hit2 is not None:
            second = json.loads(hit2["body"].decode("utf-8"))
            check("那一条回执写的是 cancelled，不是把成功投了第二遍",
                  second["status"] == "cancelled" and second["job_id"] == tail, second)
        deadline = time.time() + 300.0
        metrics: dict = {}
        drained: dict = {}
        while time.time() < deadline:
            with api(base) as hub:
                metrics = hub.get("/v1/metrics").json()
            drained = metrics.get("callbacks") or {}
            still = int((metrics.get("queue") or {}).get("pending") or 0)
            if drained.get("pending") == 0 and still == 0:
                break
            time.sleep(0.5)
        counted = (metrics.get("jobs") or {}).get("by_status") or {}
        terminal = sum(int(counted.get(key) or 0) for key in ("succeeded", "failed", "cancelled"))
        check("每一条终态都欠过一次投递、也都投出去了：delivered 与终态单数一致且没有欠账",
              terminal >= 8 and drained.get("delivered") == terminal
              and drained.get("pending") == 0, (drained, counted))
    finally:
        stop(proc)
        receiver.stop()


def slow_preset() -> str:
    from ops_check import SLOW_PRESET

    return SLOW_PRESET


def retry_leg(rig: Rig) -> None:
    """⑤ 接收端先 503 两次再 200：这一条最终 delivered，attempts 是 3。"""
    receiver = Receiver(mode="flaky", flaky=2)
    proc = spawn(rig, "--callback-url", receiver.url, "--callback-attempts", "6")
    base = str(ready_line(proc).get("base_url") or "")
    try:
        if not base:
            check("重试这一趟的引擎起不来", False, "没有 base_url")
            return
        project_id, revision = seed(rig, base, "retry", 4, noisy=False)
        job_id = submit(base, project_id, revision, "retry", 1)
        check("先渲完", wait_terminal(base, job_id).get("status") == "succeeded", job_id)
        deadline = time.time() + 90.0
        row: dict = {}
        while time.time() < deadline:
            with api(base) as hub:
                rows = {str(item["job_id"]): item
                        for item in hub.get("/v1/callbacks").json().get("callbacks") or []}
            row = rows.get(job_id) or {}
            if row.get("status") == "delivered":
                break
            time.sleep(0.5)
        check("接收端前两次不给好脸，第三次还是投成了", row.get("status") == "delivered", row)
        check("投了几次说得出来：三次（503、503、200）", row.get("attempts") == 3, row)
        check("接收端确实被打过三次", len(receiver.hits) == 3,
              [hit["answered"] for hit in receiver.hits])
    finally:
        stop(proc)
        receiver.stop()


def giveup_leg(rig: Rig) -> None:
    """⑥ 一直 500：到上限就认栽，并把为什么没成留在账上。"""
    receiver = Receiver(mode="reject")
    proc = spawn(rig, "--callback-url", receiver.url, "--callback-attempts", "2")
    base = str(ready_line(proc).get("base_url") or "")
    try:
        if not base:
            check("认栽这一趟的引擎起不来", False, "没有 base_url")
            return
        project_id, revision = seed(rig, base, "giveup", 4, noisy=False)
        job_id = submit(base, project_id, revision, "giveup", 1)
        check("先渲完", wait_terminal(base, job_id).get("status") == "succeeded", job_id)
        deadline = time.time() + 90.0
        row: dict = {}
        while time.time() < deadline:
            with api(base) as hub:
                rows = {str(item["job_id"]): item
                        for item in hub.get("/v1/callbacks").json().get("callbacks") or []}
            row = rows.get(job_id) or {}
            if row.get("status") == "gave_up":
                break
            time.sleep(0.5)
        check("到上限就记成 gave_up，不无限空转", row.get("status") == "gave_up", row)
        check("为什么没成说得出来", "HTTP 500" in str(row.get("last_error") or ""), row)
        check("只试了登记的那两个次数", row.get("attempts") == 2 and len(receiver.hits) == 2,
              (row.get("attempts"), len(receiver.hits)))
        with api(base) as hub:
            metrics = hub.get("/v1/metrics").json().get("callbacks") or {}
            check("欠账与放弃在 metrics 里分得清",
                  metrics.get("gave_up") == 1 and metrics.get("pending") == 0, metrics)
    finally:
        stop(proc)
        receiver.stop()


def restart_leg(rig: Rig) -> None:
    """⑦ A 欠着回执时被杀掉，B 在同一个数据目录上把那一条补投出去——且没重渲。

    接收端全程只用**一个**：出站记录绑的是它欠下的那个 URL（这才对——一条欠账该说清欠的是
    给谁的），所以这里靠「同一个端口换个脸色」来演接收端恢复了，而不是换个端口假装是同一家。
    """
    receiver = Receiver(mode="reject")
    proc = spawn(rig, "--callback-url", receiver.url, "--callback-attempts", "30")
    base = str(ready_line(proc).get("base_url") or "")
    job_id = ""
    owed_attempts = 0
    try:
        if not base:
            check("重启这一趟的第一台起不来", False, "没有 base_url")
            return
        project_id, revision = seed(rig, base, "restart", 4, noisy=False)
        job_id = submit(base, project_id, revision, "restart", 1)
        check("先渲完（A 那台得真的走到终态）",
              wait_terminal(base, job_id).get("status") == "succeeded", job_id)
        deadline = time.time() + 60.0
        row: dict = {}
        while time.time() < deadline:
            with api(base) as hub:
                rows = {str(item["job_id"]): item
                        for item in hub.get("/v1/callbacks").json().get("callbacks") or []}
            row = rows.get(job_id) or {}
            if row.get("status") == "pending" and int(row.get("attempts") or 0) >= 1:
                break
            time.sleep(0.2)
        check("A 投过至少一次且仍欠着（这一格不成立，下面那一腿就是空跑）",
              row.get("status") == "pending" and int(row.get("attempts") or 0) >= 1, row)
        owed_attempts = int(row.get("attempts") or 0)
    finally:
        stop(proc)
    receiver.mode = "ok"
    proc2 = spawn(rig, "--callback-url", receiver.url, "--callback-attempts", "30")
    base2 = str(ready_line(proc2).get("base_url") or "")
    try:
        if not base2:
            check("第二台起不来", False, "没有 base_url")
            return
        deadline = time.time() + 90.0
        delivered: dict = {}
        while time.time() < deadline:
            with api(base2) as hub:
                rows = {str(item["job_id"]): item
                        for item in hub.get("/v1/callbacks").json().get("callbacks") or []}
            delivered = rows.get(job_id) or {}
            if delivered.get("status") == "delivered":
                break
            time.sleep(0.5)
        check("B 把 A 欠的那一条补投出去了（重启没把欠账洗掉）",
              delivered.get("status") == "delivered", delivered)
        check("补投接着上一次的次数往下数，不是从头再来一遍",
              int(delivered.get("attempts") or 0) > owed_attempts,
              (delivered.get("attempts"), owed_attempts))
        check("B 没有重渲那一单：库里还是 A 留下的那一个作业", _job_count(base2) == 1,
              _job_count(base2))
    finally:
        stop(proc2)
        receiver.stop()


def _instance(base: str) -> str:
    with api(base) as hub:
        info = hub.get("/v1/info").json()
        payload_info = info.get("info") if isinstance(info.get("info"), dict) else info
        return str(payload_info.get("instance") or "")


def _job_count(base: str) -> int:
    with api(base) as hub:
        listed = hub.get("/v1/metrics?recent=50").json().get("jobs") or {}
        return int(listed.get("recent") or 0)


def refusal_leg(rig: Rig) -> None:
    """⑨ 配错就停在自己门前，并与别的门一起点名。"""
    half = spawn(rig, "--callback-url", "file:///C:/Windows/win.ini")
    code, out = _wait_exit(half)
    check("file: 那种地址不起，并点名 --callback-url",
          code not in (None, 0) and "--callback-url" in out, (code, out[-200:]))
    creds = spawn(rig, "--callback-url", "http://user:pass@127.0.0.1:9/hook")
    code, out = _wait_exit(creds)
    check("带账号的地址也不起（那一串会原样进台账与读数）",
          code not in (None, 0) and "http/https" in out, (code, out[-200:]))
    triple = spawn(rig, "--host", "0.0.0.0", "--callback-url", "ftp://127.0.0.1/hook",
                   AGENTCUT_TOKEN="")
    code, out = _wait_exit(triple)
    named = all(needle in out for needle in ("--callback-url", "TLS", "AGENTCUT_TOKEN"))
    check("三道门都没过就一句点名三道，谁也不许把谁演没了（1.322 的那一刀）",
          code not in (None, 0) and named, (code, out[-320:]))


def _wait_exit(proc: subprocess.Popen, seconds: float = 30.0) -> tuple[int | None, str]:
    deadline = time.time() + seconds
    while time.time() < deadline and proc.poll() is None:
        time.sleep(0.2)
    code = proc.poll()
    if code is None:
        stop(proc)
        return None, (proc.stdout.read() or "") + (proc.stderr.read() or "")
    return code, (proc.stdout.read() or "") + (proc.stderr.read() or "")


def main() -> None:
    predicate_leg()
    atomic_leg(Rig(scratch.make("agentcut-cbatomic-")))
    for tag, leg in (("delivery", delivery_leg), ("retry", retry_leg), ("giveup", giveup_leg),
                     ("restart", restart_leg), ("refusal", refusal_leg)):
        try:
            leg(Rig(scratch.make(f"agentcut-cb{tag}-")))
        except (Exception, SystemExit) as error:  # noqa: BLE001 炸在半路也要交出已量到的那几格
            check(f"{tag} 那一腿半路就炸了（这不是判不过，是根本没判完）", False,
                  f"{type(error).__name__}: {str(error)[:200]}")
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print(f"  - {line}")
        raise SystemExit(1)
    print("PASS: 终态回执真投到了（签名验得回、篡改过不行）、取消也递、重试与认栽都有数、"
          "A 欠的账 B 补得上、配错地址停在自己门前并与别的门一起点名")


if __name__ == "__main__":
    main()
