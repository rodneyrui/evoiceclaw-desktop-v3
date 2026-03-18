"""速率限制中间件 — 滑动窗口算法

按客户端 IP + 端点路径分组限流，防止意外的高频请求。
桌面应用场景，使用内存存储，无需 Redis。
"""

import time
import logging
from collections import defaultdict
from typing import Dict, List, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("evoiceclaw.security.rate_limiter")

# ─── 限流规则 ──────────────────────────────────────────────
# (最大请求数, 时间窗口秒数)
RATE_LIMITS: Dict[str, Tuple[int, int]] = {
    # 对话端点：LLM 调用成本高
    "/api/v1/chat": (10, 60),
    # 配置端点：写操作需限制
    "/api/v1/config": (20, 60),
    # Skill 安装/卸载
    "/api/v1/skills": (15, 60),
    # 评测触发
    "/api/v1/evaluation": (10, 60),
    # 审计查询
    "/api/v1/audit": (30, 60),
}

# 默认限制（未匹配到的端点）
DEFAULT_RATE_LIMIT: Tuple[int, int] = (60, 60)

# 不限流的路径前缀
EXEMPT_PATHS = {
    "/api/v1/system/health",
    "/api/v1/chat/models",
}


class _SlidingWindow:
    """滑动窗口计数器"""

    __slots__ = ("_requests",)

    def __init__(self) -> None:
        self._requests: List[float] = []

    def add_and_check(self, now: float, max_requests: int, window_seconds: int) -> bool:
        """记录请求并检查是否超限。返回 True 表示允许，False 表示拒绝。"""
        cutoff = now - window_seconds
        # 清理过期记录
        self._requests = [t for t in self._requests if t > cutoff]
        if len(self._requests) >= max_requests:
            return False
        self._requests.append(now)
        return True

    def remaining(self, now: float, max_requests: int, window_seconds: int) -> int:
        """剩余可用请求数"""
        cutoff = now - window_seconds
        active = sum(1 for t in self._requests if t > cutoff)
        return max(0, max_requests - active)

    def reset_time(self, now: float, window_seconds: int) -> int:
        """距离窗口重置的秒数"""
        cutoff = now - window_seconds
        active = [t for t in self._requests if t > cutoff]
        if not active:
            return 0
        return int(active[0] + window_seconds - now) + 1


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI 速率限制中间件"""

    def __init__(self, app, rate_limits: Dict[str, Tuple[int, int]] | None = None):
        super().__init__(app)
        self._limits = rate_limits or RATE_LIMITS
        # key: (client_ip, path_prefix) → SlidingWindow
        self._windows: Dict[Tuple[str, str], _SlidingWindow] = defaultdict(_SlidingWindow)
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 300  # 每 5 分钟清理过期窗口

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端 IP"""
        # 优先 X-Forwarded-For（反向代理场景）
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _match_limit(self, path: str) -> Tuple[str, int, int]:
        """匹配路径到限流规则，返回 (匹配的前缀, 最大请求数, 窗口秒数)"""
        for prefix, (max_req, window) in self._limits.items():
            if path.startswith(prefix):
                return prefix, max_req, window
        return "__default__", DEFAULT_RATE_LIMIT[0], DEFAULT_RATE_LIMIT[1]

    def _cleanup_expired(self, now: float) -> None:
        """清理长时间无活动的窗口，避免内存泄漏"""
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        max_window = max(
            (w for _, w in self._limits.values()),
            default=DEFAULT_RATE_LIMIT[1],
        )
        expired_keys = [
            key for key, window in self._windows.items()
            if not window._requests or (now - window._requests[-1]) > max_window * 2
        ]
        for key in expired_keys:
            del self._windows[key]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 豁免路径不限流
        for exempt in EXEMPT_PATHS:
            if path == exempt or path.startswith(exempt + "/"):
                return await call_next(request)

        # 非 API 路径不限流（前端静态资源）
        if not path.startswith("/api/"):
            return await call_next(request)

        # GET 请求更宽松（查询类）
        # POST/PUT/DELETE 使用标准限制
        client_ip = self._get_client_ip(request)
        prefix, max_requests, window_seconds = self._match_limit(path)

        # GET 请求放宽 2 倍
        if request.method == "GET":
            max_requests = max_requests * 2

        now = time.monotonic()
        self._cleanup_expired(now)

        key = (client_ip, prefix)
        window = self._windows[key]

        if not window.add_and_check(now, max_requests, window_seconds):
            remaining = 0
            reset = window.reset_time(now, window_seconds)
            logger.warning(
                "速率限制触发 | ip=%s path=%s limit=%d/%ds",
                client_ip, path, max_requests, window_seconds,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "请求频率过高，请稍后重试",
                    "detail": f"限制: {max_requests} 次/{window_seconds} 秒",
                    "retry_after": reset,
                },
                headers={
                    "Retry-After": str(reset),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset),
                },
            )

        # 正常请求，附加限流信息头
        response = await call_next(request)
        remaining = window.remaining(now, max_requests, window_seconds)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
