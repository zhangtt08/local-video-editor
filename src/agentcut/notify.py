"""作业终态的出口：引擎把「这一单渲完了 / 失败了 / 被取消了」推出去，而不是等人来问。

企业把剪辑接进流水线时，1.319 之后有了队列、槽数与恢复，却还要调用方自己轮询
`/v1/jobs/{id}`——一次交付的完成时刻只有引擎知道，让每一方按自己的节奏去问，等于把
「什么时候能拿这一条片子去发」这件事拆成了 N 份轮询代码。这一档给一个事件出口：
POST 一份带签名的回执，失败按上限重试，投不出去的结果留在库里给人看，而不是丢进日志。

出站记录与作业状态写在**同一个事务**里（`JobRuntime._save` 把自己的连接交进来）。
这不是讲究：分两步的话，进程正好死在两步之间就会出现「作业成功了但没人知道」——那种
事故查无可查，因为库里那一条已经是终态，而外头没有任何一处记得欠一次通知。写在一起，
重启后欠的那几条还在表里，泵线程照样补投。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from sqlite3 import Row, connect
from typing import Any

EVENT = "agentcut.job.terminal"
TERMINAL = ("succeeded", "failed", "cancelled")
# 第 N 次投不出去之后歇多久再试；用完还不成就认栽（gave_up），由门禁与读数说清。
BACKOFF_SECONDS = (1.0, 5.0, 20.0)
DEFAULT_ATTEMPTS = len(BACKOFF_SECONDS) + 1
DEFAULT_TIMEOUT_SECONDS = 5.0
SIGNATURE_HEADER = "X-AgentCut-Signature"
EVENT_HEADER = "X-AgentCut-Event"
DELIVERY_HEADER = "X-AgentCut-Delivery"


def connect_outbox(db_path: Path) -> Any:
    db = connect(db_path, timeout=5, isolation_level=None)
    db.row_factory = Row
    return db


def signature(secret: str, body: bytes) -> str:
    """整条 HMAC-SHA256，不截断。

    `http_api.signature()` 那一只截到 32 位，够用因为它签的是一个短的 URL 资源名、
    活几十秒；这里的对象是回执正文，接收方拿同一枚令牌重算就能判断有没有被改过，
    所以给完整摘要。
    """
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def payload(job: Any, instance: str) -> dict:
    """回执里只放引擎**量到过**的东西；没量过的字段是缺席，不是编一个像样的值。

    `request_id` 不在这里：那一格活在 `render_receipts` 里，不属于作业文档，
    回执里放一个查不到的字段比不放更糟。对账用 `job_id`。
    """
    output = str(job.output_path or "")
    return {
        "event": EVENT,
        "instance": instance,
        "job_id": job.id,
        "project_id": job.project_id,
        "sequence_id": job.sequence_id,
        "preset_id": job.preset_id,
        "filename": job.filename,
        "revision": job.revision,
        "status": job.status,
        "error_code": job.error_code,
        "message": job.message,
        "output_name": Path(output).name if output else None,
        "output_dir": Path(output).parent.name if output else None,
        "output_size_bytes": job.output_size_bytes,
        "output_checked": job.output_checked,
        "elapsed_seconds": job.elapsed_seconds,
        "total_ticks": job.total_ticks,
        "rendered_ticks": job.rendered_ticks,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def canonical(body: dict) -> bytes:
    return json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")


class Outbox:
    """一张 `job_outbox` 表 + 一个投送线程。没配地址就不建表、不起线程。"""

    def __init__(
        self,
        db_path: Path,
        urls: list[str],
        secret: str,
        *,
        instance: str = "",
        attempts: int = DEFAULT_ATTEMPTS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        poll_seconds: float = 0.4,
    ) -> None:
        self.db_path = db_path
        self.urls = [str(url).strip() for url in urls if str(url).strip()]
        self.secret = secret
        self.instance = instance
        self.attempts = max(1, int(attempts))
        self.timeout_seconds = max(0.5, float(timeout_seconds))
        self.poll_seconds = max(0.05, float(poll_seconds))
        self.thread: threading.Thread | None = None
        self.stop_flag = threading.Event()
        if self.urls:
            with connect_outbox(db_path) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS job_outbox("
                    "job_id TEXT NOT NULL, url TEXT NOT NULL, document TEXT NOT NULL,"
                    "status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,"
                    "last_error TEXT, next_attempt_at REAL NOT NULL,"
                    "created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
                    "PRIMARY KEY(job_id, url))"
                )

    # ---------- 写侧（与作业状态同一个事务） ----------

    def enqueue(self, db: Any, job: Any) -> None:
        """终态才记账；不是终态就什么都不做。`db` 是调用方那一条连接，不开第二条。"""
        if not self.urls or job.status not in TERMINAL:
            return
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        epoch = time.time()
        body = canonical(payload(job, self.instance)).decode("utf-8")
        for url in self.urls:
            db.execute(
                "INSERT OR IGNORE INTO job_outbox(job_id,url,document,status,attempts,"
                "next_attempt_at,created_at,updated_at) VALUES(?,?,?,'pending',0,?,?,?)",
                (job.id, url, body, epoch, now, now),
            )

    # ---------- 读侧 ----------

    def summary(self) -> dict:
        if not self.urls:
            return {"configured": False, "urls": 0, "pending": 0, "delivered": 0, "gave_up": 0}
        with connect_outbox(self.db_path) as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS n FROM job_outbox GROUP BY status"
            ).fetchall()
        counts = {str(row["status"]): int(row["n"]) for row in rows}
        return {
            "configured": True,
            "urls": len(self.urls),
            "pending": counts.get("pending", 0),
            "delivered": counts.get("delivered", 0),
            "gave_up": counts.get("gave_up", 0),
            "attempts_limit": self.attempts,
            "timeout_seconds": self.timeout_seconds,
        }

    def recent(self, limit: int = 50) -> list[dict]:
        if not self.urls:
            return []
        with connect_outbox(self.db_path) as db:
            rows = db.execute(
                "SELECT job_id,url,document,status,attempts,last_error,created_at,updated_at"
                " FROM job_outbox ORDER BY created_at DESC, job_id DESC, url ASC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            try:
                body = json.loads(str(row["document"]))
            except ValueError:
                body = {}
            out.append(
                {
                    "job_id": str(row["job_id"]),
                    "url": str(row["url"]),
                    "status": str(row["status"]),
                    "attempts": int(row["attempts"]),
                    "last_error": row["last_error"],
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                    "job_status": body.get("status"),
                    "error_code": body.get("error_code"),
                    "output_name": body.get("output_name"),
                }
            )
        return out

    # ---------- 投送 ----------

    def _due(self, now: float) -> list[Row]:
        with connect_outbox(self.db_path) as db:
            return db.execute(
                "SELECT job_id,url,document,attempts FROM job_outbox"
                " WHERE status='pending' AND next_attempt_at<=? ORDER BY next_attempt_at"
                " LIMIT 20",
                (now,),
            ).fetchall()

    def _post(self, url: str, body: bytes, job_id: str, attempt: int) -> int:
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"agentcut/{self.instance or 'engine'}",
                EVENT_HEADER: EVENT,
                SIGNATURE_HEADER: "sha256=" + signature(self.secret, body),
                DELIVERY_HEADER: f"{job_id}-{attempt}",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as answer:
            return int(answer.status)

    def _settle(self, job_id: str, url: str, *, delivered: bool, attempts: int, error: str) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if delivered:
            state = "delivered"
            delay = 0.0
        elif attempts >= self.attempts:
            state = "gave_up"
            delay = 0.0
        else:
            state = "pending"
            delay = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
        with connect_outbox(self.db_path) as db:
            db.execute(
                "UPDATE job_outbox SET status=?, attempts=?, last_error=?, updated_at=?,"
                " next_attempt_at=? WHERE job_id=? AND url=?",
                (state, attempts, None if delivered else error, now, time.time() + delay,
                 job_id, url),
            )

    def pump_once(self) -> int:
        """跑一轮到期的记录，交回这一轮动了几条。测试与线程都走这一手。"""
        did = 0
        for row in self._due(time.time()):
            job_id, url = str(row["job_id"]), str(row["url"])
            body = str(row["document"]).encode("utf-8")
            attempts = int(row["attempts"]) + 1
            did += 1
            try:
                status = self._post(url, body, job_id, attempts)
                delivered, error = 200 <= status < 300, f"HTTP {status}"
            except urllib.error.HTTPError as problem:
                # 先接 HTTPError：它是 URLError 的子类，反过来写会把 404 读成「连不上」。
                delivered, error = False, f"HTTP {problem.code}"
            except (urllib.error.URLError, OSError, ValueError) as problem:
                delivered, error = False, f"{type(problem).__name__}: {str(problem)[:120]}"
            self._settle(job_id, url, delivered=delivered, attempts=attempts, error=error)
        return did

    def start(self) -> None:
        if not self.urls or self.thread is not None:
            return
        self.stop_flag.clear()

        def loop() -> None:
            while not self.stop_flag.wait(self.poll_seconds):
                try:
                    self.pump_once()
                except Exception:  # noqa: BLE001  投送线程不该因为一轮炸了就静默退出
                    time.sleep(min(2.0, self.poll_seconds * 4))

        self.thread = threading.Thread(target=loop, name="agentcut-callbacks", daemon=True)
        self.thread.start()

    def stop(self, join_seconds: float = 5.0) -> None:
        self.stop_flag.set()
        thread, self.thread = self.thread, None
        if thread is not None:
            thread.join(timeout=join_seconds)

    def wait_for_idle(self, seconds: float = 20.0) -> bool:
        """等到没有 pending 为止；超时交回 False（门禁要靠这一手把「投完了」变成读数）。"""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.summary()["pending"] == 0:
                return True
            time.sleep(0.2)
        return self.summary()["pending"] == 0
