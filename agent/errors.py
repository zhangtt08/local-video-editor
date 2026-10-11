"""Agent API 共享异常。tools.py 与 server.py 都必须从这里导入，否则 importlib 二次加载会产生
不同的类对象，导致 server 侧的 except 捕获不到 handler 抛出的错误。"""
from __future__ import annotations


class AgentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
