"""门禁自己拉起的子进程——**崩了也要收掉**。

为什么要有这一档：1.320 量到一台半途崩掉的 `lease_check` 在机器上留下 4 个还在服务的引擎
（venv 那个壳 + 真在服务的解释器各两台），它们的 `--data-dir` 指着已经被 atexit 删掉的临时
目录，自己不会退。临时目录会还，进程不会还——无人值守跑验收的那台机器要的是后者。

口径只有两条：`survivors()` 交回「还在活的」，`sweep(stop)` 用调用方自己的停法收掉它们。
停法不在这里定（各档要连子树一起收掉的那一支 FFmpeg 各不相同），这一档只管别留活口。
"""

from __future__ import annotations

import subprocess
from typing import Callable

PROCS: list[subprocess.Popen] = []


def note(proc: subprocess.Popen) -> subprocess.Popen:
    """记下拉起的那一个，交回同一个对象（调用点的形状不动）。"""
    PROCS.append(proc)
    return proc


def survivors() -> list[int]:
    return [proc.pid for proc in PROCS if proc.poll() is None]


def sweep(stop: Callable[[subprocess.Popen], None]) -> list[int]:
    """收掉还活着的，交回收不掉的 PID——收不掉才是真缺陷，忘了记一笔不是。"""
    for proc in list(PROCS):
        if proc.poll() is None:
            stop(proc)
    return survivors()