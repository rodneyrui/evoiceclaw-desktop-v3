"""运行时权限协商管理器

当 Agent 的工具调用遇到安全级别不足时（如 L1 下执行 python3），
PermissionBroker 负责：
1. 创建一个"待批准"的权限提升请求
2. 通过 SSE 事件通知前端
3. 等待用户在前端确认（asyncio.Event）
4. 将批准结果传递回工具执行层

通过 ContextVar 传递已批准的级别，避免修改 SkillProtocol 接口。
黑名单命令不可提升，只有"级别不足"类拒绝才触发协商。
"""

import asyncio
import contextvars
import logging
import time
from dataclasses import dataclass, field
from uuid import uuid4

logger = logging.getLogger("evoiceclaw.security.permission_broker")

# ── ContextVar：在工具执行期间传递已批准的提升级别 ──
# chat_service 批准后 set → shell.py 执行时 get
elevation_level: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "elevation_level", default=None,
)


@dataclass
class ElevationRequest:
    """一次权限提升请求"""
    request_id: str
    command: str
    cmd_name: str
    current_level: str
    required_level: str
    reason: str
    created_at: float = field(default_factory=time.monotonic)
    # asyncio.Event：等待用户决策
    event: asyncio.Event = field(default_factory=asyncio.Event)
    # 决策结果：None=待决 True=批准 False=拒绝
    approved: bool | None = None


# 标记字段：工具返回此 key 表示需要权限提升（非普通错误）
ELEVATION_MARKER = "__elevation_required__"


class PermissionBroker:
    """权限协商 Broker（单例）

    管理待批准的权限提升请求，协调前端与工具执行之间的交互。
    """

    def __init__(self) -> None:
        self._pending: dict[str, ElevationRequest] = {}
        # 清理间隔（秒）
        self._cleanup_interval = 300
        self._last_cleanup = time.monotonic()

    def create_request(
        self,
        command: str,
        cmd_name: str,
        current_level: str,
        required_level: str,
        reason: str,
    ) -> ElevationRequest:
        """创建一个权限提升请求

        Args:
            command: 完整命令字符串
            cmd_name: 命令名（如 python3）
            current_level: 当前安全级别（如 L1）
            required_level: 所需安全级别（如 L2）
            reason: 拒绝原因

        Returns:
            ElevationRequest 对象（包含 request_id 和 asyncio.Event）
        """
        self._maybe_cleanup()

        request_id = str(uuid4())[:8]
        req = ElevationRequest(
            request_id=request_id,
            command=command,
            cmd_name=cmd_name,
            current_level=current_level,
            required_level=required_level,
            reason=reason,
        )
        self._pending[request_id] = req

        logger.info(
            "[权限协商] 创建请求: id=%s cmd=%s 当前=%s 需要=%s",
            request_id, cmd_name, current_level, required_level,
        )
        return req

    async def wait_for_decision(
        self, request_id: str, timeout: float = 120,
    ) -> bool:
        """等待用户对权限请求的决策

        Args:
            request_id: 请求 ID
            timeout: 等待超时（秒），默认 120 秒

        Returns:
            True=批准 False=拒绝或超时
        """
        req = self._pending.get(request_id)
        if not req:
            logger.warning("[权限协商] 请求不存在: %s", request_id)
            return False

        try:
            await asyncio.wait_for(req.event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("[权限协商] 请求超时: %s (%.0fs)", request_id, timeout)
            req.approved = False
            self._pending.pop(request_id, None)
            return False

        result = req.approved or False
        self._pending.pop(request_id, None)

        logger.info(
            "[权限协商] 决策完成: id=%s 结果=%s",
            request_id, "批准" if result else "拒绝",
        )
        return result

    def approve(self, request_id: str) -> bool:
        """批准权限提升请求（由 API 端点调用）

        Returns:
            True=请求存在且已批准 False=请求不存在或已过期
        """
        req = self._pending.get(request_id)
        if not req:
            logger.warning("[权限协商] 批准失败，请求不存在: %s", request_id)
            return False

        req.approved = True
        req.event.set()
        logger.info("[权限协商] 用户批准: id=%s cmd=%s", request_id, req.cmd_name)
        return True

    def deny(self, request_id: str) -> bool:
        """拒绝权限提升请求（由 API 端点调用）

        Returns:
            True=请求存在且已拒绝 False=请求不存在或已过期
        """
        req = self._pending.get(request_id)
        if not req:
            logger.warning("[权限协商] 拒绝失败，请求不存在: %s", request_id)
            return False

        req.approved = False
        req.event.set()
        logger.info("[权限协商] 用户拒绝: id=%s cmd=%s", request_id, req.cmd_name)
        return True

    def get_request(self, request_id: str) -> ElevationRequest | None:
        """获取待处理的请求信息"""
        return self._pending.get(request_id)

    def _maybe_cleanup(self) -> None:
        """清理过期请求（超过 5 分钟未响应的）"""
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        expired = [
            rid for rid, req in self._pending.items()
            if now - req.created_at > self._cleanup_interval
        ]
        for rid in expired:
            req = self._pending.pop(rid, None)
            if req and not req.event.is_set():
                req.approved = False
                req.event.set()

        if expired:
            logger.info("[权限协商] 清理 %d 个过期请求", len(expired))
        self._last_cleanup = now


# ── 单例 ──

_broker: PermissionBroker | None = None


def get_permission_broker() -> PermissionBroker:
    """获取全局 PermissionBroker 单例"""
    global _broker
    if _broker is None:
        _broker = PermissionBroker()
    return _broker
