"""实时日志 SSE 流：将后端日志推送到前端"""

import asyncio
import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

router = APIRouter()

# 内存缓存最近 200 条日志
_LOG_BUFFER: deque[str] = deque(maxlen=200)
_subscribers: list[asyncio.Queue[str]] = []

# 线程安全锁（SSELogHandler.emit 可能被任意线程调用）
_log_lock = threading.Lock()


class SSELogHandler(logging.Handler):
    """将日志行广播给所有 SSE 订阅者。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            with _log_lock:
                _LOG_BUFFER.append(line)
                dead: list[asyncio.Queue[str]] = []
                for q in _subscribers:
                    try:
                        q.put_nowait(line)
                    except asyncio.QueueFull:
                        dead.append(q)
                for q in dead:
                    _subscribers.remove(q)
        except Exception:
            # 日志处理器内不能再记录日志（避免递归），只能静默忽略
            pass


def install_log_handler():
    """安装 SSE 日志 handler 到 evoiceclaw logger。"""
    handler = SSELogHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    ))
    # 捕获所有 evoiceclaw.* 日志
    evoice = logging.getLogger("evoiceclaw")
    evoice.addHandler(handler)


@router.get("/logs/stream")
async def stream_logs():
    """SSE 端点：实时推送后端日志。"""
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
    with _log_lock:
        _subscribers.append(q)
        buffer_snapshot = list(_LOG_BUFFER)

    async def event_generator():
        try:
            # 先发送缓存的最近日志
            for line in buffer_snapshot:
                yield {"event": "log", "data": line}
            # 持续推送新日志
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=30)
                    yield {"event": "log", "data": line}
                except asyncio.TimeoutError:
                    # 发送心跳保持连接
                    yield {"event": "ping", "data": datetime.now(timezone.utc).isoformat()}
        finally:
            with _log_lock:
                if q in _subscribers:
                    _subscribers.remove(q)

    return EventSourceResponse(event_generator())
