"""Chat API：流式对话 + 模型列表 + 断线恢复"""

import asyncio
import json
import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_config
from app.services import chat_service

logger = logging.getLogger("evoiceclaw.api.chat")

router = APIRouter()

# conversation_id 格式：字母数字 + 短横线 + 下划线，最长 64 字符
_CONV_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,64}$')


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=100000, description="用户消息")
    model: str = Field(
        default="auto",
        max_length=128,
        description="模型 ID，如 'deepseek/deepseek-chat' 或 'cli:claude' 或 'auto'",
    )
    conversation_id: str | None = Field(
        default=None,
        max_length=64,
        description="会话 ID，用于多轮对话。不传则创建新会话。",
    )
    system_prompt: str | None = Field(
        default=None,
        max_length=10000,
        description="系统提示词（仅新会话首次消息生效）",
    )

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, v: str | None) -> str | None:
        if v is not None and not _CONV_ID_RE.match(v):
            raise ValueError("conversation_id 格式无效：仅允许字母、数字、下划线和短横线")
        return v


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: str
    type: str   # "api" | "cli"
    mode: str   # "fast" | "analysis"


ConfigDep = Annotated[dict, Depends(get_config)]


@router.post("")
async def chat(body: ChatRequest, config: ConfigDep):
    """发送消息并以 SSE 流式返回 LLM 响应

    流式输出在后台任务中运行，客户端断开不会中断生成。
    断开后可通过 GET /{conversation_id}/recover 恢复已缓冲的内容。

    SSE 事件格式：
        data: {"type": "text", "content": "你好", "model": "deepseek-chat", "provider": "deepseek"}

    type 取值：
      - text: 文本块
      - thinking: 思考过程（推理模型）
      - error: 错误
      - end: 结束（包含 usage 统计）
      - tool_call: LLM 请求调用工具
      - tool_result: 工具执行结果
    """
    logger.info(
        "[Chat API] model=%s conv=%s",
        body.model, body.conversation_id or "(new)",
    )

    session = chat_service.start_stream_session(
        message=body.message,
        model_id=body.model,
        config=config,
        conversation_id=body.conversation_id,
        system_prompt=body.system_prompt,
    )

    async def event_generator():
        try:
            while True:
                # 等待下一个 chunk，使用短超时 + 心跳，防止长时间工具执行（如 OCR）断连
                try:
                    chunk = await asyncio.wait_for(session.queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    # 发送 SSE 注释心跳，保持连接活跃
                    yield {"data": json.dumps({"type": "keepalive"}, ensure_ascii=False)}
                    continue
                if chunk is None:  # 终止信号
                    break
                yield {"data": json.dumps(chunk, ensure_ascii=False)}
        except asyncio.TimeoutError:
            logger.warning("[Chat API] SSE 超时: conv=%s", session.conversation_id)
        except asyncio.CancelledError:
            # 客户端断开，后台任务继续运行
            logger.info("[Chat API] 客户端断开: conv=%s（后台继续生成）", session.conversation_id)

    return EventSourceResponse(event_generator())


@router.get("/{conversation_id}/recover")
async def recover_stream(conversation_id: str):
    """恢复断线的流式会话

    返回已缓冲的完整文本和流状态。前端刷新后调用此端点恢复丢失的内容。
    如果 active=true 表示流仍在进行，前端应每 1 秒轮询直到 active=false。
    """
    # SA-11: 路径参数格式校验，防止注入
    if not _CONV_ID_RE.match(conversation_id):
        raise HTTPException(status_code=400, detail="conversation_id 格式无效")

    recovery = chat_service.get_stream_recovery(conversation_id)
    if not recovery:
        return {"active": False, "full_text": "", "model": "", "provider": ""}
    return recovery


@router.get("/models", response_model=list[ModelInfo])
async def list_models(config: ConfigDep):
    """获取所有可用模型列表"""
    return chat_service.get_available_models(config)
