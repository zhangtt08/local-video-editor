"""门禁自己的临时地方——**用完必须还**。

为什么要有这一档：1.225 跑完发布账时量到，`%TEMP%` 里留着 110 个 `agentcut-*` 目录、
合计 24.7 MB（一天两趟全套的量）。验东西的那一手不该往用户的地方堆垃圾——
`tempfile.mkdtemp` 不清理，`TemporaryDirectory` 又要改一遍控制流；这里给一个
「建了就走 atexit 删」的口，调用点一行换一行，控制流不动。

删的时候 `ignore_errors=True`：Windows 上刚退出的子进程可能还攥着句柄，
为这一个目录把整趟门禁染红，报的就不是产品的问题了（量具的抖动不是缺陷）。
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path


def _reap(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def make(prefix: str) -> Path:
    """建一个临时目录，进程退出时删掉。"""
    named = prefix if prefix.startswith("agentcut-") else f"agentcut-{prefix}"
    path = tempfile.mkdtemp(prefix=named)
    atexit.register(_reap, path)
    return Path(path)


def make_str(prefix: str) -> str:
    """同上，交回字符串——给那些把路径当 `str` 用的调用点，不顺手改它们的类型。"""
    return str(make(prefix))
