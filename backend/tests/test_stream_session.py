"""流式会话缓冲区单元测试

覆盖：StreamSession 初始化, _chunk_to_payload, get_stream_recovery
（start_stream_session / _run_stream_background 涉及 asyncio.create_task + chat_stream 集成，
 在 test_chat_api 层面通过 mock 覆盖，此处不重复测试。）
"""

import time
import pytest

from app.domain.models import StreamChunk, StreamChunkType, ToolCall
from app.services.stream_session import (
    StreamSession,
    _chunk_to_payload,
    get_stream_recovery,
    _stream_sessions,
)


# ── StreamSession 初始化 ──────────────────────────────────────

class TestStreamSession:
    def test_初始状态active为True(self):
        s = StreamSession("conv-1")
        assert s.active is True

    def test_初始full_text为空(self):
        s = StreamSession("conv-1")
        assert s.full_text == ""

    def test_conversation_id正确保存(self):
        s = StreamSession("my-conv-id")
        assert s.conversation_id == "my-conv-id"

    def test_初始buffered_payloads为空列表(self):
        s = StreamSession("conv-1")
        assert s.buffered_payloads == []

    def test_started_at接近当前时间(self):
        before = time.time()
        s = StreamSession("conv-1")
        after = time.time()
        assert before <= s.started_at <= after

    def test_queue容量为1000(self):
        s = StreamSession("conv-1")
        assert s.queue.maxsize == 1000


# ── _chunk_to_payload ─────────────────────────────────────────

class TestChunkToPayload:
    def test_text类型基本字段(self):
        chunk = StreamChunk(type=StreamChunkType.TEXT, content="你好")
        payload = _chunk_to_payload(chunk)
        assert payload["type"] == "text"
        assert payload["content"] == "你好"

    def test_end类型(self):
        chunk = StreamChunk(type=StreamChunkType.END, content="")
        payload = _chunk_to_payload(chunk)
        assert payload["type"] == "end"

    def test_error类型(self):
        chunk = StreamChunk(type=StreamChunkType.ERROR, content="出错了")
        payload = _chunk_to_payload(chunk)
        assert payload["type"] == "error"
        assert payload["content"] == "出错了"

    def test_有model字段时包含在payload中(self):
        chunk = StreamChunk(type=StreamChunkType.TEXT, content="hi", model="deepseek-chat")
        payload = _chunk_to_payload(chunk)
        assert payload["model"] == "deepseek-chat"

    def test_model为None时不包含在payload中(self):
        chunk = StreamChunk(type=StreamChunkType.TEXT, content="hi", model=None)
        payload = _chunk_to_payload(chunk)
        assert "model" not in payload

    def test_有provider字段时包含在payload中(self):
        chunk = StreamChunk(type=StreamChunkType.TEXT, content="hi", provider="deepseek")
        payload = _chunk_to_payload(chunk)
        assert payload["provider"] == "deepseek"

    def test_provider为None时不包含在payload中(self):
        chunk = StreamChunk(type=StreamChunkType.TEXT, content="hi", provider=None)
        payload = _chunk_to_payload(chunk)
        assert "provider" not in payload

    def test_有usage字段时包含在payload中(self):
        usage = {"prompt_tokens": 10, "completion_tokens": 20}
        chunk = StreamChunk(type=StreamChunkType.END, content="", usage=usage)
        payload = _chunk_to_payload(chunk)
        assert payload["usage"] == usage

    def test_usage为None时不包含在payload中(self):
        chunk = StreamChunk(type=StreamChunkType.END, content="", usage=None)
        payload = _chunk_to_payload(chunk)
        assert "usage" not in payload

    def test_有tool_call时包含结构化字段(self):
        tc = ToolCall(id="call-1", name="web_search", arguments={"query": "test"})
        chunk = StreamChunk(type=StreamChunkType.TOOL_CALL, content="", tool_call=tc)
        payload = _chunk_to_payload(chunk)
        assert "tool_call" in payload
        assert payload["tool_call"]["id"] == "call-1"
        assert payload["tool_call"]["name"] == "web_search"
        assert payload["tool_call"]["arguments"] == {"query": "test"}

    def test_tool_call为None时不包含在payload中(self):
        chunk = StreamChunk(type=StreamChunkType.TEXT, content="hi", tool_call=None)
        payload = _chunk_to_payload(chunk)
        assert "tool_call" not in payload

    def test_类型为Enum时取value(self):
        """StreamChunkType 是 str Enum，.value 应为字符串"""
        chunk = StreamChunk(type=StreamChunkType.TEXT, content="")
        payload = _chunk_to_payload(chunk)
        assert isinstance(payload["type"], str)
        assert payload["type"] == "text"


# ── get_stream_recovery ───────────────────────────────────────

class TestGetStreamRecovery:
    def setup_method(self):
        """每个测试前清空全局 session 字典"""
        _stream_sessions.clear()

    def teardown_method(self):
        _stream_sessions.clear()

    def test_不存在的conversation_id返回None(self):
        result = get_stream_recovery("nonexistent-id")
        assert result is None

    def test_存在时返回正确结构(self):
        s = StreamSession("conv-abc")
        s.full_text = "已生成的内容"
        s.active = False
        s.model = "deepseek-chat"
        s.provider = "deepseek"
        s.buffered_payloads = [{"type": "text", "content": "已生成的内容"}]
        _stream_sessions["conv-abc"] = s

        result = get_stream_recovery("conv-abc")
        assert result is not None
        assert result["conversation_id"] == "conv-abc"
        assert result["full_text"] == "已生成的内容"
        assert result["active"] is False
        assert result["model"] == "deepseek-chat"
        assert result["provider"] == "deepseek"
        assert result["chunk_count"] == 1

    def test_active为True时正确反映(self):
        s = StreamSession("conv-xyz")
        s.active = True
        _stream_sessions["conv-xyz"] = s

        result = get_stream_recovery("conv-xyz")
        assert result["active"] is True

    def test_chunk_count等于buffered_payloads长度(self):
        s = StreamSession("conv-cnt")
        s.buffered_payloads = [{"type": "text"}, {"type": "text"}, {"type": "end"}]
        _stream_sessions["conv-cnt"] = s

        result = get_stream_recovery("conv-cnt")
        assert result["chunk_count"] == 3

    def test_返回值包含所有预期字段(self):
        s = StreamSession("conv-fields")
        _stream_sessions["conv-fields"] = s

        result = get_stream_recovery("conv-fields")
        expected_keys = {"conversation_id", "full_text", "active", "model", "provider", "chunk_count"}
        assert set(result.keys()) == expected_keys
