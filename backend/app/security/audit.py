"""全链路审计日志服务

写入 audit.db 的 audit_log 表（表结构已在 infrastructure/db.py 的 init_audit_tables() 中创建）。
所有安全相关操作（Shell 执行、Skill 安装、守门员审查等）都通过此模块记录。

trace_id 串联同一请求链路的所有日志条目。
"""

import logging
import uuid
from datetime import datetime

from app.infrastructure.db import get_connection, AUDIT_DB

logger = logging.getLogger("evoiceclaw.security.audit")

# 日志级别常量
LEVEL_INFO = "INFO"
LEVEL_WARN = "WARN"
LEVEL_ERROR = "ERROR"


def new_trace_id() -> str:
    """生成唯一链路追踪 ID"""
    return str(uuid.uuid4())


def init_audit() -> None:
    """审计服务初始化（当前为空操作，表已由 db.init_audit_tables() 创建）"""
    logger.info("[审计] 审计服务就绪")


def log_event(
    *,
    component: str,
    action: str,
    trace_id: str | None = None,
    detail: str = "",
    level: str = LEVEL_INFO,
    duration_ms: int | None = None,
    user_id: str = "default",
    workspace_id: str = "global",
) -> None:
    """写入一条审计日志

    Args:
        component: 组件名（如 "shell", "gatekeeper", "skill_service"）
        action: 动作名（如 "COMMAND_ALLOW", "INSTALL_OK"）
        trace_id: 链路追踪 ID（可选，不传则自动生成）
        detail: 详细信息（JSON 字符串或普通文本）
        level: 日志级别（INFO / WARN / ERROR）
        duration_ms: 耗时毫秒（可选）
        user_id: 用户 ID（R3 多用户隔离预留）
        workspace_id: 工作区 ID（用于按工作区隔离审计日志，默认 "global"）
    """
    if not trace_id:
        trace_id = new_trace_id()

    row_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat(timespec="seconds") + "Z"

    try:
        conn = get_connection(AUDIT_DB)
        conn.execute(
            """INSERT INTO audit_log (id, trace_id, timestamp, level, component, action, detail, duration_ms, user_id, workspace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row_id, trace_id, timestamp, level, component, action, detail, duration_ms, user_id, workspace_id),
        )
        conn.commit()
    except Exception as e:
        # 审计写入失败不应阻塞业务流程，仅记录日志
        logger.error("[审计] 写入失败: %s — %s", action, e)

    # 同时输出到标准日志（方便开发调试）
    log_level = getattr(logging, level, logging.INFO)
    logger.log(
        log_level,
        "[审计] [%s] %s.%s %s%s",
        trace_id,
        component,
        action,
        detail[:200] if detail else "",
        f" ({duration_ms}ms)" if duration_ms else "",
    )


def query_audit(
    *,
    trace_id: str | None = None,
    component: str | None = None,
    level: str | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
    workspace_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """查询审计日志

    Args:
        trace_id: 按 trace_id 过滤
        component: 按组件名过滤
        level: 按级别过滤
        time_from: 起始时间（ISO 格式）
        time_to: 结束时间（ISO 格式）
        workspace_id: 按工作区 ID 过滤（不传则返回所有工作区的日志）
        limit: 最大返回条数

    Returns:
        审计日志条目列表（dict）
    """
    conn = get_connection(AUDIT_DB)
    conditions: list[str] = []
    params: list = []

    if trace_id:
        conditions.append("trace_id = ?")
        params.append(trace_id)
    if component:
        conditions.append("component = ?")
        params.append(component)
    if level:
        conditions.append("level = ?")
        params.append(level)
    if time_from:
        conditions.append("timestamp >= ?")
        params.append(time_from)
    if time_to:
        conditions.append("timestamp <= ?")
        params.append(time_to)
    if workspace_id:
        conditions.append("workspace_id = ?")
        params.append(workspace_id)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"SELECT * FROM audit_log WHERE {where_clause} ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()
    return [dict(row) for row in rows]
