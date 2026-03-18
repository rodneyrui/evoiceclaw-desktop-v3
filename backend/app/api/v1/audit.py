"""Audit API：审计日志查询"""

import logging
from typing import Annotated

from fastapi import APIRouter, Query

from app.security.audit import query_audit

logger = logging.getLogger("evoiceclaw.api.audit")

router = APIRouter()


@router.get("")
async def get_audit_logs(
    trace_id: Annotated[str | None, Query(description="按 trace_id 过滤")] = None,
    component: Annotated[str | None, Query(description="按组件过滤（shell/gatekeeper/skill_service）")] = None,
    level: Annotated[str | None, Query(description="按级别过滤（INFO/WARN/ERROR）")] = None,
    time_from: Annotated[str | None, Query(description="起始时间（ISO 格式）")] = None,
    time_to: Annotated[str | None, Query(description="结束时间（ISO 格式）")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回条数")] = 100,
):
    """查询审计日志（支持多条件过滤）"""
    rows = query_audit(
        trace_id=trace_id,
        component=component,
        level=level,
        time_from=time_from,
        time_to=time_to,
        limit=limit,
    )
    return {"items": rows, "total": len(rows)}
