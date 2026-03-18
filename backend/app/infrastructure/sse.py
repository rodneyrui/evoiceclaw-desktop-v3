"""SSE 事件队列

基于 asyncio.Queue 的服务端推送事件队列。
push_event() 推入 JSON 事件，subscribe() 作为异步生成器供 EventSourceResponse 消费。
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any


class TaskEventQueue:
    """SSE 事件队列"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._closed = False

    def push_event(self, event_type: str, data: dict[str, Any]) -> None:
        """推入一个事件"""
        if self._closed:
            return
        payload = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        self._queue.put_nowait(json.dumps(payload, ensure_ascii=False))

    def close(self) -> None:
        """关闭队列（发送 None 哨兵）"""
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(None)

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def subscribe(self) -> AsyncGenerator[dict[str, str], None]:
        """订阅事件流（供 EventSourceResponse 消费）"""
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield {"data": item}
