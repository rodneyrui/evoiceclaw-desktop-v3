"""权限协商 API：接收前端的权限提升批准/拒绝决策"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.security.permission_broker import get_permission_broker

logger = logging.getLogger("evoiceclaw.api.permissions")

router = APIRouter()


class ElevationResponse(BaseModel):
    approved: bool


class ElevationResult(BaseModel):
    success: bool
    message: str


@router.post(
    "/{request_id}/respond",
    response_model=ElevationResult,
    summary="响应权限提升请求",
)
async def respond_to_elevation(request_id: str, body: ElevationResponse):
    """前端调用此端点来批准或拒绝权限提升请求

    当后端 SSE 流发送 permission_request 事件后，
    前端应显示确认对话框，用户决策后调用此端点。

    Args:
        request_id: 权限请求 ID（来自 permission_request 事件）
        body: {"approved": true} 或 {"approved": false}
    """
    broker = get_permission_broker()
    req = broker.get_request(request_id)

    if not req:
        raise HTTPException(
            status_code=404,
            detail=f"权限请求不存在或已过期: {request_id}",
        )

    if body.approved:
        success = broker.approve(request_id)
        action = "批准"
    else:
        success = broker.deny(request_id)
        action = "拒绝"

    if not success:
        raise HTTPException(
            status_code=409,
            detail=f"权限请求处理失败（可能已被响应）: {request_id}",
        )

    logger.info("[权限API] %s 权限提升: request_id=%s", action, request_id)
    return ElevationResult(
        success=True,
        message=f"已{action}权限提升请求",
    )


@router.get(
    "/{request_id}",
    summary="查询权限请求状态",
)
async def get_elevation_status(request_id: str):
    """查询权限提升请求的当前状态（用于前端轮询或调试）"""
    broker = get_permission_broker()
    req = broker.get_request(request_id)

    if not req:
        raise HTTPException(
            status_code=404,
            detail=f"权限请求不存在或已过期: {request_id}",
        )

    return {
        "request_id": req.request_id,
        "command": req.command,
        "cmd_name": req.cmd_name,
        "current_level": req.current_level,
        "required_level": req.required_level,
        "approved": req.approved,
        "pending": not req.event.is_set(),
    }
