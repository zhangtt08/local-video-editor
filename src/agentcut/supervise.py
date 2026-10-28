"""无人值守的看门人：这台引擎崩了，有人接着把它拉起来，而且说得出拉了几次。

为什么要有这一档：桌面外壳会重拉引擎，但它在第 5 次之后**永久放弃**，前提还是「有人坐在这台
机器前」。企业把引擎放到服务器上、agent 走 HTTP 调它时，这条路上什么都没有——进程死了就是死了。
1.324 之后这件事更危险：watch folder 会继续把素材收进一个没人服务的目录，回执也不会投，
现场表现是「片子上架了但没剪」，没有一行错误。

做法与边界：
- 子进程就是同一个 `python -m agentcut api …`，带 `--exit-with-parent`（看门人死了它自己走，
  不留孤儿引擎占着数据目录）；
- 退避 1 / 2 / 5 / 30 秒；60 秒内崩三次以上按最长那一档等——**不是放弃**：一台无人值守的机器
  宁可每 30 秒试一次，也不该在第三次之后安静地躺着；
- `<data-dir>/supervisor.json` 一行一态：第几次重启、上一次退出码、上次活了多久、下一次等多久；
- `<data-dir>/server.log` 收子进程的 stdout/stderr（崩之前那几行是唯一的现场），同时照抄到
  我们自己的 stdout——运维脚本读 ready 行那一套一个字都不用改；
- `<data-dir>/supervisor.stop` 一出现就干净收摊：停子进程、写 `stopped`、退出 0。
  为什么用文件而不是信号：Windows 上给别的进程发 Ctrl-C 没有可靠写法，而「放一个文件」在服务、
  计划任务与容器里都成立。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_BACKOFF = (1.0, 2.0, 5.0, 30.0)
STORM_WINDOW_SECONDS = 60.0
STORM_LIMIT = 3
MODES = ("api", "desktop", "mcp")


def _data_dir(args: list[str]) -> Path:
    for index, item in enumerate(args):
        if item == "--data-dir" and index + 1 < len(args):
            return Path(args[index + 1])
    return Path("data")


class Supervisor:
    def __init__(
        self,
        child_args: list[str],
        data_dir: Path,
        *,
        backoff: tuple[float, ...] = DEFAULT_BACKOFF,
        python: str | None = None,
        poll_seconds: float = 0.2,
    ) -> None:
        self.child_args = list(child_args)
        while self.child_args and self.child_args[0] == "--":
            self.child_args.pop(0)
        self.data_dir = Path(data_dir)
        self.backoff = tuple(backoff) or DEFAULT_BACKOFF
        self.python = python or sys.executable
        self.poll_seconds = max(0.05, poll_seconds)
        self.state_path = self.data_dir / "supervisor.json"
        self.stop_path = self.data_dir / "supervisor.stop"
        self.log_path = self.data_dir / "server.log"
        self.restarts = 0
        self.state = "starting"
        self.last_exit: int | None = None
        self.last_uptime: float | None = None
        self.next_delay = 0.0

    # ---------- 账 ----------

    def _record(self, **fields: Any) -> dict:
        payload: dict[str, Any] = {
            "configured": True,
            "state": self.state,
            "supervisor_pid": os.getpid(),
            "child_pid": None,
            "restarts": self.restarts,
            "last_exit_code": self.last_exit,
            "last_uptime_seconds": self.last_uptime,
            "next_delay_seconds": self.next_delay,
            "backoff_seconds": list(self.backoff),
            "storm_window_seconds": STORM_WINDOW_SECONDS,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        payload.update(fields)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.state_path)
        return payload

    # ---------- 子进程 ----------

    def _command(self) -> list[str]:
        args = list(self.child_args)
        mode = args[0] if args and args[0] in MODES else "api"
        rest = args[1:] if args and args[0] in MODES else args
        return [self.python, "-m", "agentcut", mode, *rest,
                "--exit-with-parent", str(os.getpid())]

    def _pump(self, proc: subprocess.Popen) -> None:
        """把子进程的输出照抄到我们的 stdout，同时落一份盘——崩之前的几行只在盘上留得住。"""
        with self.log_path.open("a", encoding="utf-8", errors="replace") as log:
            stream = proc.stdout
            if stream is None:
                return
            for line in stream:
                log.write(line)
                log.flush()
                sys.stdout.write(line)
                sys.stdout.flush()

    def _terminate(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=60)
        else:  # pragma: no cover - 这台机器是 Windows
            proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()

    # ---------- 主循环 ----------

    def run(self) -> int:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.stop_path.exists():
            self.stop_path.unlink()
        crashes: list[float] = []
        proc: subprocess.Popen | None = None
        try:
            while True:
                if self.stop_path.exists():
                    break
                self.state = "running"
                started = time.time()
                proc = subprocess.Popen(
                    self._command(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                )
                self._record(child_pid=proc.pid, started_at=time.strftime(
                    "%Y-%m-%dT%H:%M:%S"))
                threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
                # 子进程活着的时候也要看得见 stop 文件：`proc.wait()` 一阻塞，收摊就只能等到
                # 引擎自己退出——那正是运维最不想要的「放了一个文件却停不下来」。
                code: int | None = None
                while code is None:
                    code = proc.poll()
                    if code is not None:
                        break
                    if self.stop_path.exists():
                        break
                    time.sleep(self.poll_seconds)
                if code is None:
                    break
                uptime = time.time() - started
                if self.stop_path.exists():
                    self.last_exit = code
                    self.last_uptime = round(uptime, 1)
                    break
                self.restarts += 1
                self.last_exit = code
                self.last_uptime = round(uptime, 1)
                now = time.time()
                crashes = [stamp for stamp in crashes if now - stamp < STORM_WINDOW_SECONDS]
                crashes.append(now)
                self.next_delay = self.backoff[min(len(crashes) - 1, len(self.backoff) - 1)]
                self.state = "restarting"
                self._record(
                    child_pid=proc.pid,
                    storm=len(crashes) >= STORM_LIMIT,
                    crashes_in_window=len(crashes),
                )
                deadline = time.time() + self.next_delay
                while time.time() < deadline:
                    if self.stop_path.exists():
                        break
                    time.sleep(self.poll_seconds)
                if self.stop_path.exists():
                    break
        except KeyboardInterrupt:  # pragma: no cover - 由门禁的 stop 文件那条路覆盖
            self.state = "stopped"
            self._record(child_pid=getattr(proc, "pid", None), reason="signal")
            return 0
        finally:
            if proc is not None:
                self._terminate(proc)
        self.state = "stopped"
        self.next_delay = 0.0
        self._record(child_pid=None, reason="stop-file")
        return 0


def main(args: list[str]) -> int:
    supervisor = Supervisor(args, _data_dir(args))
    return supervisor.run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
