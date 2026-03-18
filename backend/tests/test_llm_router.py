"""LLM 路由器测试

覆盖：get_available_models（API 启用/禁用 + str/dict 模型 + CLI Agent）
     _is_retryable（关键词大小写不敏感）
     stream（cli: 前缀路由 / API 路由 / 代理未配置/未启用）
     stream_with_fallback（空候选 / 可重试跳过 / 全部失败 / 成功路径）
     collect_stream_text（只收集 text 类型）
     get_router 未初始化时抛 RuntimeError
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.models import ChatMessage, StreamChunk
from app.kernel.router.llm_router import (
    LLMRouter,
    collect_stream_text,
    get_router,
    init_router,
)
import app.kernel.router.llm_router as _lr


def _make_router() -> LLMRouter:
    """创建 LLMRouter，patch 掉真实 Provider 构造"""
    with patch("app.kernel.router.llm_router.APIProvider"), \
         patch("app.kernel.router.llm_router.CLIAgentProvider"):
        return LLMRouter()


# ─── get_available_models ──────────────────────────────────────────────────

class TestGetAvailableModels:

    def test_禁用provider被过滤(self):
        router = _make_router()
        config = {
            "providers": {
                "deepseek": {"enabled": False, "api_key": "k", "models": ["deepseek-chat"]},
            }
        }
        assert router.get_available_models(config) == []

    def test_无api_key的provider被过滤(self):
        router = _make_router()
        config = {
            "providers": {
                "deepseek": {"enabled": True, "api_key": "", "models": ["deepseek-chat"]},
            }
        }
        assert router.get_available_models(config) == []

    def test_字符串模型自动拼接provider前缀(self):
        router = _make_router()
        config = {
            "providers": {
                "deepseek": {"enabled": True, "api_key": "k", "models": ["deepseek-chat"]},
            }
        }
        result = router.get_available_models(config)
        assert len(result) == 1
        assert result[0]["id"] == "deepseek/deepseek-chat"
        assert result[0]["type"] == "api"
        assert result[0]["provider"] == "deepseek"

    def test_字符串模型已有前缀不重复添加(self):
        router = _make_router()
        config = {
            "providers": {
                "deepseek": {
                    "enabled": True, "api_key": "k",
                    "models": ["deepseek/deepseek-chat"],
                },
            }
        }
        result = router.get_available_models(config)
        assert result[0]["id"] == "deepseek/deepseek-chat"

    def test_字典模型格式正确解析(self):
        router = _make_router()
        config = {
            "providers": {
                "qwen": {
                    "enabled": True, "api_key": "k",
                    "models": [{"id": "qwen-max", "name": "Qwen Max", "mode": "analysis"}],
                }
            }
        }
        result = router.get_available_models(config)
        assert result[0]["id"] == "qwen/qwen-max"
        assert result[0]["name"] == "Qwen Max"
        assert result[0]["mode"] == "analysis"

    def test_字典模型无id字段被跳过(self):
        router = _make_router()
        config = {
            "providers": {
                "qwen": {
                    "enabled": True, "api_key": "k",
                    "models": [{"name": "No ID"}],
                }
            }
        }
        assert router.get_available_models(config) == []

    def test_非法模型类型被跳过(self):
        router = _make_router()
        config = {
            "providers": {
                "deepseek": {
                    "enabled": True, "api_key": "k",
                    "models": [12345],
                }
            }
        }
        assert router.get_available_models(config) == []

    def test_启用的cli_agent被包含(self):
        router = _make_router()
        config = {
            "providers": {},
            "cli_agents": {
                "claude_code": {"enabled": True, "name": "Claude Code"},
            }
        }
        result = router.get_available_models(config)
        assert len(result) == 1
        assert result[0]["id"] == "cli:claude_code"
        assert result[0]["type"] == "cli"
        assert result[0]["provider"] == "cli"

    def test_禁用cli_agent被过滤(self):
        router = _make_router()
        config = {
            "providers": {},
            "cli_agents": {
                "claude_code": {"enabled": False, "name": "Claude Code"},
            }
        }
        assert router.get_available_models(config) == []

    def test_api和cli同时返回(self):
        router = _make_router()
        config = {
            "providers": {
                "deepseek": {"enabled": True, "api_key": "k", "models": ["deepseek-chat"]},
            },
            "cli_agents": {
                "claude_code": {"enabled": True, "name": "CC"},
            }
        }
        result = router.get_available_models(config)
        types = {m["type"] for m in result}
        assert "api" in types
        assert "cli" in types


# ─── _is_retryable ─────────────────────────────────────────────────────────

class TestIsRetryable:

    def test_429可重试(self):
        assert LLMRouter._is_retryable("Error 429: rate limit exceeded") is True

    def test_rate关键词可重试(self):
        assert LLMRouter._is_retryable("Rate limit hit") is True

    def test_502可重试(self):
        assert LLMRouter._is_retryable("Bad gateway 502") is True

    def test_503可重试(self):
        assert LLMRouter._is_retryable("Service unavailable 503") is True

    def test_504可重试(self):
        assert LLMRouter._is_retryable("Gateway timeout 504") is True

    def test_timeout可重试(self):
        assert LLMRouter._is_retryable("Connection timeout") is True

    def test_connect关键词可重试(self):
        assert LLMRouter._is_retryable("Failed to connect to host") is True

    def test_普通认证错误不可重试(self):
        assert LLMRouter._is_retryable("Invalid API key") is False

    def test_内容策略错误不可重试(self):
        assert LLMRouter._is_retryable("Content policy violation") is False

    def test_大小写不敏感(self):
        assert LLMRouter._is_retryable("TIMEOUT ERROR") is True
        assert LLMRouter._is_retryable("RATE LIMIT") is True


# ─── stream ─────────────────────────────────────────────────────────────────

class TestStream:

    @pytest.mark.asyncio
    async def test_cli前缀路由到cli_provider(self):
        router = _make_router()
        messages = [ChatMessage(role="user", content="Hello")]
        config = {"cli_agents": {"claude_code": {"enabled": True, "name": "CC"}}}

        async def fake_cli_stream(*args, **kwargs):
            yield StreamChunk(type="text", content="cli response")

        router.cli_provider.stream = MagicMock(return_value=fake_cli_stream())

        chunks = []
        async for chunk in router.stream(messages, "cli:claude_code", config):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].content == "cli response"

    @pytest.mark.asyncio
    async def test_cli代理未配置yield错误chunk(self):
        router = _make_router()
        messages = [ChatMessage(role="user", content="Hello")]
        config = {"cli_agents": {}}

        chunks = []
        async for chunk in router.stream(messages, "cli:unknown_agent", config):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].type == "error"
        assert "未配置" in chunks[0].content

    @pytest.mark.asyncio
    async def test_cli代理未启用yield错误chunk(self):
        router = _make_router()
        messages = [ChatMessage(role="user", content="Hello")]
        config = {"cli_agents": {"claude_code": {"enabled": False, "name": "CC"}}}

        chunks = []
        async for chunk in router.stream(messages, "cli:claude_code", config):
            chunks.append(chunk)

        assert chunks[0].type == "error"
        assert "未启用" in chunks[0].content

    @pytest.mark.asyncio
    async def test_api路由到api_provider(self):
        router = _make_router()
        messages = [ChatMessage(role="user", content="Hello")]
        config = {"providers": {}}

        async def fake_api_stream(*args, **kwargs):
            yield StreamChunk(type="text", content="api response")

        router.api_provider.stream = MagicMock(return_value=fake_api_stream())

        chunks = []
        async for chunk in router.stream(messages, "deepseek/deepseek-chat", config):
            chunks.append(chunk)

        assert chunks[0].content == "api response"


# ─── stream_with_fallback ──────────────────────────────────────────────────

class TestStreamWithFallback:

    @pytest.mark.asyncio
    async def test_空候选列表yield错误(self):
        router = _make_router()
        chunks = []
        async for chunk in router.stream_with_fallback([], [], {}):
            chunks.append(chunk)
        assert len(chunks) == 1
        assert chunks[0].type == "error"
        assert "无可用候选" in chunks[0].content

    @pytest.mark.asyncio
    async def test_可重试错误跳过当前模型(self):
        router = _make_router()
        messages = [ChatMessage(role="user", content="test")]

        async def mixed_stream(msgs, model_id, cfg, tools=None, max_tokens=None):
            if model_id == "model-a":
                yield StreamChunk(type="error", content="429 rate limit exceeded")
            else:
                yield StreamChunk(type="text", content="success from model-b")
                yield StreamChunk(type="end", content="")

        router.stream = mixed_stream

        chunks = []
        async for chunk in router.stream_with_fallback(messages, ["model-a", "model-b"], {}):
            chunks.append(chunk)

        text_chunks = [c for c in chunks if c.type == "text"]
        assert len(text_chunks) == 1
        assert text_chunks[0].content == "success from model-b"

    @pytest.mark.asyncio
    async def test_所有候选失败yield最后错误(self):
        router = _make_router()
        messages = [ChatMessage(role="user", content="test")]

        async def always_fail(msgs, model_id, cfg, tools=None, max_tokens=None):
            yield StreamChunk(type="error", content="429 rate limit exceeded")

        router.stream = always_fail

        chunks = []
        async for chunk in router.stream_with_fallback(messages, ["m1", "m2"], {}):
            chunks.append(chunk)

        assert chunks[-1].type == "error"

    @pytest.mark.asyncio
    async def test_成功流完整转发所有chunk(self):
        router = _make_router()
        messages = [ChatMessage(role="user", content="test")]

        async def success_stream(msgs, model_id, cfg, tools=None, max_tokens=None):
            yield StreamChunk(type="text", content="Hello")
            yield StreamChunk(type="text", content=" World")
            yield StreamChunk(type="end", content="")

        router.stream = success_stream

        chunks = []
        async for chunk in router.stream_with_fallback(messages, ["model-a"], {}):
            chunks.append(chunk)

        contents = [c.content for c in chunks if c.type == "text"]
        assert contents == ["Hello", " World"]

    @pytest.mark.asyncio
    async def test_非可重试错误直接返回不继续尝试(self):
        router = _make_router()
        messages = [ChatMessage(role="user", content="test")]
        call_count = {"n": 0}

        async def non_retryable_error(msgs, model_id, cfg, tools=None, max_tokens=None):
            call_count["n"] += 1
            yield StreamChunk(type="error", content="Invalid API key")

        router.stream = non_retryable_error

        chunks = []
        async for chunk in router.stream_with_fallback(messages, ["m1", "m2"], {}):
            chunks.append(chunk)

        # 非可重试错误 → 第一个模型收到错误后直接返回，不尝试 m2
        assert call_count["n"] == 1
        assert chunks[0].type == "error"


# ─── collect_stream_text ───────────────────────────────────────────────────

class TestCollectStreamText:

    @pytest.mark.asyncio
    async def test_收集所有text类型chunk拼接(self):
        router = _make_router()
        messages = [ChatMessage(role="user", content="test")]

        async def fake_stream(msgs, model_id, cfg, tools=None, max_tokens=None):
            yield StreamChunk(type="text", content="Hello")
            yield StreamChunk(type="text", content=" World")
            yield StreamChunk(type="end", content="")

        router.stream = fake_stream
        result = await collect_stream_text(router, messages, "model-x", {})
        assert result == "Hello World"

    @pytest.mark.asyncio
    async def test_非text类型被忽略(self):
        router = _make_router()
        messages = [ChatMessage(role="user", content="test")]

        async def fake_stream(msgs, model_id, cfg, tools=None, max_tokens=None):
            yield StreamChunk(type="tool_call", content="ignored")
            yield StreamChunk(type="text", content="result")
            yield StreamChunk(type="end", content="")

        router.stream = fake_stream
        result = await collect_stream_text(router, messages, "model-x", {})
        assert result == "result"

    @pytest.mark.asyncio
    async def test_空流返回空字符串(self):
        router = _make_router()
        messages = [ChatMessage(role="user", content="test")]

        async def empty_stream(msgs, model_id, cfg, tools=None, max_tokens=None):
            return
            yield  # make it an async generator

        router.stream = empty_stream
        result = await collect_stream_text(router, messages, "model-x", {})
        assert result == ""


# ─── get_router 单例 ────────────────────────────────────────────────────────

class TestGetRouter:

    def test_未初始化时抛出RuntimeError(self):
        old = _lr._router
        try:
            _lr._router = None
            with pytest.raises(RuntimeError, match="未初始化"):
                get_router()
        finally:
            _lr._router = old

    def test_init_router设置全局单例(self):
        old = _lr._router
        try:
            with patch("app.kernel.router.llm_router.APIProvider"), \
                 patch("app.kernel.router.llm_router.CLIAgentProvider"):
                router = init_router()
            assert isinstance(router, LLMRouter)
            assert get_router() is router
        finally:
            _lr._router = old
