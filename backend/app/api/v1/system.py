"""系统端点：健康检查 / 统计 / 审计日志查询"""

import logging

from fastapi import APIRouter

logger = logging.getLogger("evoiceclaw.api.system")

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
async def health_check():
    """健康检查端点。"""
    return {"status": "ok", "version": "3.0.0"}
