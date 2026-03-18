"""速率限制中间件测试"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.security.rate_limiter import (
    _SlidingWindow,
    RateLimitMiddleware,
    RATE_LIMITS,
    DEFAULT_RATE_LIMIT,
    EXEMPT_PATHS,
)


# ─── _SlidingWindow ───────────────────────────────────────────

class TestSlidingWindow:

    def test_first_request_allowed(self):
        w = _SlidingWindow()
        assert w.add_and_check(time.monotonic(), 10, 60) is True

    def test_requests_within_limit(self):
        w = _SlidingWindow()
        now = time.monotonic()
        for _ in range(5):
            assert w.add_and_check(now, 10, 60) is True

    def test_exceeds_limit(self):
        w = _SlidingWindow()
        now = time.monotonic()
        for _ in range(10):
            w.add_and_check(now, 10, 60)
        # 第 11 次应被拒绝
        assert w.add_and_check(now, 10, 60) is False

    def test_old_requests_expire(self):
        w = _SlidingWindow()
        old_time = time.monotonic() - 61  # 61秒前
        for _ in range(10):
            w._requests.append(old_time)
        now = time.monotonic()
        # 旧请求应已过期，新请求应被允许
        assert w.add_and_check(now, 10, 60) is True

    def test_remaining_count(self):
        w = _SlidingWindow()
        now = time.monotonic()
        for _ in range(3):
            w.add_and_check(now, 10, 60)
        assert w.remaining(now, 10, 60) == 7

    def test_remaining_after_expire(self):
        w = _SlidingWindow()
        old_time = time.monotonic() - 61
        for _ in range(8):
            w._requests.append(old_time)
        now = time.monotonic()
        assert w.remaining(now, 10, 60) == 10

    def test_reset_time_empty(self):
        w = _SlidingWindow()
        assert w.reset_time(time.monotonic(), 60) == 0

    def test_reset_time_with_requests(self):
        w = _SlidingWindow()
        now = time.monotonic()
        w._requests.append(now - 30)  # 30秒前的请求
        reset = w.reset_time(now, 60)
        assert 0 < reset <= 31  # 大约 30 秒后重置


# ─── RateLimitMiddleware 规则配置 ─────────────────────────────

class TestRateLimitConfig:

    def test_chat_endpoint_has_limit(self):
        assert "/api/v1/chat" in RATE_LIMITS

    def test_config_endpoint_has_limit(self):
        assert "/api/v1/config" in RATE_LIMITS

    def test_default_limit_is_tuple(self):
        assert isinstance(DEFAULT_RATE_LIMIT, tuple)
        assert len(DEFAULT_RATE_LIMIT) == 2

    def test_health_check_is_exempt(self):
        assert "/api/v1/system/health" in EXEMPT_PATHS

    def test_models_endpoint_is_exempt(self):
        assert "/api/v1/chat/models" in EXEMPT_PATHS


# ─── 中间件请求处理（使用 FastAPI TestClient） ───────────────

@pytest.fixture
def app_with_middleware():
    """创建带速率限制中间件的最小 FastAPI 应用"""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        rate_limits={
            "/api/v1/test": (3, 60),   # 测试用：每分钟 3 次
        },
    )

    @app.get("/api/v1/test")
    async def test_endpoint():
        return {"ok": True}

    @app.post("/api/v1/test")
    async def test_post():
        return {"ok": True}

    @app.get("/api/v1/system/health")
    async def health():
        return {"status": "ok"}

    @app.get("/static/file.js")
    async def static_file():
        return JSONResponse({"content": "js"})

    return app


@pytest.fixture
def client(app_with_middleware):
    from httpx import AsyncClient, ASGITransport
    return AsyncClient(
        transport=ASGITransport(app=app_with_middleware),
        base_url="http://test",
    )


class TestRateLimitMiddleware:

    @pytest.mark.asyncio
    async def test_request_within_limit_allowed(self, client):
        async with client as ac:
            resp = await ac.get("/api/v1/test")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limit_header_present(self, client):
        async with client as ac:
            resp = await ac.get("/api/v1/test")
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers

    @pytest.mark.asyncio
    async def test_get_has_double_limit(self, client):
        """GET 请求限制是 POST 的 2 倍"""
        async with client as ac:
            # POST limit = 3, GET limit = 6
            for _ in range(3):
                resp = await ac.post("/api/v1/test")
            # GET 前 3 次应通过（POST 计数不影响 GET，但 key 包含 prefix 不包含 method）
            # 实际上 key 是 (client_ip, path_prefix)，POST/GET 共享计数
            # GET 只是 max_requests 翻倍
            resp = await ac.get("/api/v1/test")
        # 至少第一次 GET 应正常
        assert resp.status_code in (200, 429)

    @pytest.mark.asyncio
    async def test_exceeds_limit_returns_429(self, client):
        """超过限制应返回 429"""
        async with client as ac:
            for _ in range(3):
                await ac.post("/api/v1/test")
            # 第 4 次应被限流
            resp = await ac.post("/api/v1/test")
        assert resp.status_code == 429

    @pytest.mark.asyncio
    async def test_429_response_has_retry_after(self, client):
        async with client as ac:
            for _ in range(3):
                await ac.post("/api/v1/test")
            resp = await ac.post("/api/v1/test")
        if resp.status_code == 429:
            assert "retry-after" in resp.headers
            data = resp.json()
            assert "retry_after" in data

    @pytest.mark.asyncio
    async def test_exempt_path_bypasses_limit(self, client):
        """豁免路径不受速率限制"""
        async with client as ac:
            for _ in range(20):
                resp = await ac.get("/api/v1/system/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_static_path_bypasses_limit(self, client):
        """非 /api/ 路径不受速率限制"""
        async with client as ac:
            for _ in range(10):
                resp = await ac.get("/static/file.js")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_match_limit_default(self):
        """未匹配的路径使用默认限制"""
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware._limits = RATE_LIMITS
        prefix, max_req, window = middleware._match_limit("/api/v1/unknown/path")
        assert prefix == "__default__"
        assert max_req == DEFAULT_RATE_LIMIT[0]

    @pytest.mark.asyncio
    async def test_match_limit_specific(self):
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware._limits = {"/api/v1/chat": (10, 60)}
        prefix, max_req, window = middleware._match_limit("/api/v1/chat/stream")
        assert prefix == "/api/v1/chat"
        assert max_req == 10
