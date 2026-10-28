"""素材入口：盯住目录，把新落地的文件按**引擎自己那条导入路径**收下。

企业把片子交给自动流水线时，第一段路一直是人家的脚本：往共享目录里丢素材 → 外面有个 watcher
看到新文件 → 调 `media_import`。少这一段，就意味着「谁丢的文件、什么时候被看见、为什么没收」
全在那个人家写的脚本里，引擎一点都不知道。这一档把它挪进引擎。

为什么是轮询而不是 `ReadDirectoryChangesW`：事件订阅在无人值守的机器上会因句柄、共享权限与
休眠悄悄丢通知，而「丢了通知」的表现就是素材没进来——那是最难查的一类缺件。一次全量扫描的
成本是实测过的：1000 个已收过的文件一趟 **445 ms**（一个文件一条 sqlite 连接），整趟共用一条
连接之后是 **76 ms**（同一台机器、同一批文件），所以每两秒扫一趟在成千上万个文件的目录上也
站得住。真正的难点从来不是「知道文件出现了」，而是**知道它写完没有**，那一条只能靠连续两次
读数一致再加静默期，事件模式反而给不了。

收与不收只有一条路：`MediaService.import_file()`——与 HTTP 那扇 `media_import` 完全同一个函数。
第二条导入路径就会有两份「什么算可用的素材」，而这类分叉最后都变成「界面能收、自动收不进」
那种查不出来的差别。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from sqlite3 import Row, connect
from typing import Any

from .media import ALLOWED_SUFFIXES, MediaService

STATES = ("pending", "imported", "failed")
DEFAULT_INTERVAL_SECONDS = 2.0
DEFAULT_GRACE_SECONDS = 2.0


def connect_watch(db_path: Path) -> Any:
    db = connect(db_path, timeout=5, isolation_level=None)
    db.row_factory = Row
    return db


class Watcher:
    """一张 `watch_ledger` 表 + 一个扫描线程。没配目录就不建表、不起线程。"""

    def __init__(
        self,
        db_path: Path,
        media: MediaService,
        dirs: list[str],
        *,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        grace_seconds: float = DEFAULT_GRACE_SECONDS,
    ) -> None:
        self.db_path = db_path
        self.media = media
        self.dirs = [str(Path(item)).rstrip("\\/") for item in dirs if str(item).strip()]
        self.interval_seconds = max(0.2, float(interval_seconds))
        self.grace_seconds = max(0.0, float(grace_seconds))
        self.thread: threading.Thread | None = None
        self.stop_flag = threading.Event()
        self.last_scan = 0.0
        self.ignored = 0
        if self.dirs:
            with connect_watch(db_path) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS watch_ledger("
                    "path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime REAL NOT NULL,"
                    "state TEXT NOT NULL DEFAULT 'pending', probe_id TEXT, detail TEXT,"
                    "first_seen REAL NOT NULL, updated_at TEXT NOT NULL)"
                )

    # ---------- 账 ----------

    def _row(self, db: Any, path: Path) -> Row | None:
        return db.execute(
            "SELECT size,mtime,state,probe_id,first_seen FROM watch_ledger WHERE path=?",
            (str(path),),
        ).fetchone()

    def _write(
        self, db: Any, path: Path, size: int, mtime: float, state: str, probe_id: str,
        detail: str, first_seen: float,
    ) -> None:
        db.execute(
            "INSERT INTO watch_ledger(path,size,mtime,state,probe_id,detail,first_seen,"
            "updated_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,"
            " state=excluded.state, probe_id=excluded.probe_id, detail=excluded.detail,"
            " first_seen=excluded.first_seen, updated_at=excluded.updated_at",
            (str(path), size, mtime, state, probe_id or None, detail or None,
             first_seen, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )

    def _take(self, db: Any, path: Path, first_seen: float) -> None:
        """走那条唯一的导入路径。失败留下名字，不静默、不重试成第二个真相。"""
        try:
            probe = self.media.import_file(str(path))
        except Exception as error:  # noqa: BLE001 —— EditorError 的那个码就是读数
            stat = path.stat()
            self._write(db, path, stat.st_size, stat.st_mtime, "failed", "",
                        str(getattr(error, "code", type(error).__name__)), first_seen)
            return
        stat = path.stat()
        self._write(db, path, stat.st_size, stat.st_mtime, "imported", probe.id, "", first_seen)

    # ---------- 扫 ----------

    def scan_once(self) -> int:
        """扫一遍，交回这一趟**记了新账**的文件数（第一次看见与收编都算）。

        整趟只开**一条** sqlite 连接：一文件一连接时，1000 个已收过的文件一趟要 445 ms
        （实测），一条连接之后是同一个数量级的十几分之一——扫描线程每 2 秒起一趟，
        这个差别决定它是闲着还是常年占着一成 CPU。
        """
        touched = 0
        now = time.time()
        self.ignored = 0
        db = connect_watch(self.db_path)
        try:
            for directory in self.dirs:
                root = Path(directory)
                if not root.is_dir():
                    # 启动时判过一次；中途目录被删掉不该让这个线程炸，读数里说得出还在不在。
                    continue
                for path in sorted(item for item in root.rglob("*") if item.is_file()):
                    if path.suffix.lower() not in ALLOWED_SUFFIXES:
                        self.ignored += 1
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    row = self._row(db, path)
                    # 一个 0 字节的媒体文件也去试一次：`import_file` 会按名字拒（MEDIA_EMPTY），
                    # 那笔账比「一直 pending 着没人说为什么」有用得多。
                    stable = now - stat.st_mtime >= self.grace_seconds
                    same = row is not None and int(row["size"]) == stat.st_size and float(
                        row["mtime"]
                    ) == stat.st_mtime
                    if same and str(row["state"]) in ("imported", "failed"):
                        # 这一份已经收过（或已经按名字拒过），不重复收
                        continue
                    if not same:
                        # 第一次看见、或大小/时间戳变了：只记一笔观察。半拷的在这一步被挡下。
                        self._write(db, path, stat.st_size, stat.st_mtime, "pending", "",
                                    "", now)
                        touched += 1
                        continue
                    if not stable:
                        continue  # 静默期没过：等下一趟再看，别拿半截内容去探测
                    self._take(db, path, now)
                    touched += 1
        finally:
            db.close()
        self.last_scan = now
        return touched

    # ---------- 读数 ----------

    def summary(self) -> dict:
        if not self.dirs:
            return {"configured": False, "dirs": 0, "imported": 0, "pending": 0, "failed": 0}
        with connect_watch(self.db_path) as db:
            rows = db.execute(
                "SELECT state, COUNT(*) AS n FROM watch_ledger GROUP BY state"
            ).fetchall()
        counts = {str(row["state"]): int(row["n"]) for row in rows}
        return {
            "configured": True,
            "dirs": len(self.dirs),
            "missing_dirs": sum(1 for item in self.dirs if not Path(item).is_dir()),
            "imported": counts.get("imported", 0),
            "pending": counts.get("pending", 0),
            "failed": counts.get("failed", 0),
            "ignored_unsupported": self.ignored,
            "interval_seconds": self.interval_seconds,
            "grace_seconds": self.grace_seconds,
            "last_scan_age_seconds": (
                None if not self.last_scan
                else round(time.time() - self.last_scan, 2)
            ),
        }

    def recent(self, limit: int = 50) -> list[dict]:
        if not self.dirs:
            return []
        with connect_watch(self.db_path) as db:
            rows = db.execute(
                "SELECT path,size,mtime,state,probe_id,detail,updated_at FROM watch_ledger"
                " ORDER BY updated_at DESC, path ASC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [
            {
                "path": str(row["path"]),
                "name": Path(str(row["path"])).name,
                "size_bytes": int(row["size"]),
                "state": str(row["state"]),
                "probe_id": row["probe_id"],
                "detail": row["detail"],
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    # ---------- 线程 ----------

    def start(self) -> None:
        if not self.dirs or self.thread is not None:
            return

        def loop() -> None:
            while not self.stop_flag.wait(self.interval_seconds):
                try:
                    self.scan_once()
                except Exception:  # noqa: BLE001  扫描线程不该因为一趟炸了就静默退出
                    time.sleep(min(5.0, self.interval_seconds * 4))

        self.stop_flag.clear()
        self.thread = threading.Thread(target=loop, name="agentcut-watch", daemon=True)
        self.thread.start()

    def stop(self, join_seconds: float = 5.0) -> None:
        self.stop_flag.set()
        thread, self.thread = self.thread, None
        if thread is not None:
            thread.join(timeout=join_seconds)
