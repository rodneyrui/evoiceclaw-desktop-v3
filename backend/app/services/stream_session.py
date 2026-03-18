"""流式会话缓冲区：支持断线恢复的流式会话管理"""

import asyncio
import logging
import time
import uuid

from app.domain.models import StreamChunk

logger = logging.getLogger("evoiceclaw.chat")


class StreamSession:
    """流式会话缓冲区

    后台任务运行 chat_stream，所有 chunk 同时写入：
    - buffered_payloads: 完整列表，用于断线恢复
    - queue: asyncio.Queue，用于实时 SSE 传输
    客户端断开时后台任务继续运行，前端重连后通过 recover 端点获取已缓冲内容。
    """
    __slots__ = (
        "conversation_id", "full_text", "active", "model", "provider",
        "started_at", "buffered_payloads", "queue",
    )

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.full_text = ""
        self.active = True
        self.model = ""
        self.provider = ""
        self.started_at = time.time()
        self.buffered_payloads: list[dict] = []
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=1000)


_stream_sessions: dict[str, StreamSession] = {}
_STREAM_SESSION_TTL = 300  # 已完成的 session 保留 5 分钟


def _chunk_to_payload(chunk: StreamChunk) -> dict:
    """StreamChunk → SSE JSON payload dict"""
    payload: dict = {
        "type": chunk.type.value if hasattr(chunk.type, "value") else chunk.type,
        "content": chunk.content,
    }
    if chunk.model:
        payload["model"] = chunk.model
    if chunk.provider:
        payload["provider"] = chunk.provider
    if chunk.usage:
        payload["usage"] = chunk.usage
    if chunk.tool_call:
        payload["tool_call"] = {
            "id": chunk.tool_call.id,
            "name": chunk.tool_call.name,
            "arguments": chunk.tool_call.arguments,
        }
    return payload


def start_stream_session(
    message: str,
    model_id: str,
    config: dict,
    conversation_id: str | None = None,
    system_prompt: str | None = None,
) -> StreamSession:
    """创建流式会话并在后台任务中运行，返回 session 对象"""
    conv_id = conversation_id or str(uuid.uuid4())

    # 如果已有同 conversation_id 的活跃 session，先终止
    old = _stream_sessions.get(conv_id)
    if old and old.active:
        old.active = False
        try:
            old.queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    session = StreamSession(conversation_id=conv_id)
    _stream_sessions[conv_id] = session

    asyncio.create_task(_run_stream_background(
        session, message, model_id, config, conv_id, system_prompt,
    ))

    return session


async def _run_stream_background(
    session: StreamSession,
    message: str,
    model_id: str,
    config: dict,
    conversation_id: str,
    system_prompt: str | None,
) -> None:
    """后台任务：运行 chat_stream，缓冲所有 chunk 到 session"""
    try:
        from app.services.chat_service import chat_stream

        async for chunk in chat_stream(
            message=message,
            model_id=model_id,
            config=config,
            conversation_id=conversation_id,
            system_prompt=system_prompt,
        ):
            payload = _chunk_to_payload(chunk)
            session.buffered_payloads.append(payload)

            if payload["type"] == "text":
                session.full_text += payload["content"]
                if payload.get("model"):
                    session.model = payload["model"]
                if payload.get("provider"):
                    session.provider = payload["provider"]

            try:
                session.queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # 客户端跟不上，只保留在 buffer 中
    except Exception as e:
        logger.error("[流式缓冲] 后台流异常: %s", e, exc_info=True)
        error_payload: dict = {"type": "error", "content": str(e)}
        session.buffered_payloads.append(error_payload)
        try:
            session.queue.put_nowait(error_payload)
        except asyncio.QueueFull:
            pass
    finally:
        session.active = False
        try:
            session.queue.put_nowait(None)  # 终止信号
        except asyncio.QueueFull:
            pass
        logger.info(
            "[流式缓冲] 完成: conv=%s chunks=%d text_len=%d",
            session.conversation_id, len(session.buffered_payloads), len(session.full_text),
        )
        # 延迟清理
        await asyncio.sleep(_STREAM_SESSION_TTL)
        _stream_sessions.pop(session.conversation_id, None)


def get_stream_recovery(conversation_id: str) -> dict | None:
    """获取流式会话恢复数据（供前端断线恢复）"""
    session = _stream_sessions.get(conversation_id)
    if not session:
        return None
    return {
        "conversation_id": session.conversation_id,
        "full_text": session.full_text,
        "active": session.active,
        "model": session.model,
        "provider": session.provider,
        "chunk_count": len(session.buffered_payloads),
    }
