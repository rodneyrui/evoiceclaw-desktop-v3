"""Sessions API：对话历史列表 + 消息加载 + 删除"""

import logging
import re

from fastapi import APIRouter, HTTPException, Query

from app.infrastructure import db

logger = logging.getLogger("evoiceclaw.api.sessions")

router = APIRouter()

_SESSION_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,64}$')


@router.get("")
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """获取对话列表（按更新时间倒序，含消息数）"""
    return db.list_sessions(user_id="default", limit=limit, offset=offset)


@router.get("/{session_id}/messages")
async def get_session_messages(session_id: str, limit: int = Query(default=200, ge=1, le=1000)):
    """获取指定会话的历史消息"""
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="session_id 格式无效")
    return db.load_session_messages(session_id, limit=limit)


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话（CASCADE 自动清理消息）"""
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="session_id 格式无效")
    db.delete_session(session_id)
    return {"ok": True}
