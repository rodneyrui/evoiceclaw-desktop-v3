"""隐私管道各阶段测试

覆盖：
- CognitiveIsolator: 手机号/邮箱/身份证/密码检测与占位符替换
- ContextCompressor: token 预算截断、system 消息保留
- PrivacyRestorer: 占位符恢复、残留检查
- PrivacyPipeline: enabled=False 绕过、process_input 结果字段、restore_output
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.models import ChatMessage, MessageRole, RedactionEntry, SensitivityLevel
from app.pipeline.cognitive_isolator import CognitiveIsolator, IsolationResult
from app.pipeline.context_compressor import ContextCompressor, estimate_tokens
from app.pipeline.privacy_restorer import PrivacyRestorer
from app.pipeline.pipeline import PrivacyPipeline, PipelineResult
import app.pipeline.pipeline as _pipeline_module


# ─── CognitiveIsolator ────────────────────────────────────────────────────

class TestCognitiveIsolator:

    def test_手机号被检测并替换(self):
        isolator = CognitiveIsolator()
        result = isolator.isolate("请联系我，电话 13812345678")
        assert "13812345678" not in result.clean_text
        assert "__REDACTED_" in result.clean_text
        assert result.detected_count >= 1
        assert result.stats.get("PHONE", 0) >= 1

    def test_邮箱被检测并替换(self):
        isolator = CognitiveIsolator()
        result = isolator.isolate("我的邮箱是 user@example.com 请联系")
        assert "user@example.com" not in result.clean_text
        assert "__REDACTED_" in result.clean_text

    def test_密码被检测并替换(self):
        isolator = CognitiveIsolator()
        result = isolator.isolate("密码: mypassword123")
        assert "mypassword123" not in result.clean_text

    def test_无敏感数据时clean_text等于原文(self):
        isolator = CognitiveIsolator()
        text = "今天天气很好，我们去公园吧"
        result = isolator.isolate(text)
        assert result.clean_text == text
        assert result.detected_count == 0

    def test_disabled时直接返回原文(self):
        isolator = CognitiveIsolator(config={"enabled": False})
        text = "密码: secret123"
        result = isolator.isolate(text)
        assert result.clean_text == text
        assert result.detected_count == 0

    def test_空文本直接返回(self):
        isolator = CognitiveIsolator()
        result = isolator.isolate("")
        assert result.clean_text == ""
        assert result.detected_count == 0

    def test_空白文本直接返回(self):
        isolator = CognitiveIsolator()
        result = isolator.isolate("   ")
        assert result.detected_count == 0

    def test_redaction_map包含原始数据(self):
        isolator = CognitiveIsolator()
        result = isolator.isolate("联系方式：user@test.com")
        # 确认 redaction_map 中可以找到原始邮箱
        original_values = [e.original for e in result.redaction_map.values()]
        assert any("test.com" in v for v in original_values)

    def test_多个敏感项都被替换(self):
        isolator = CognitiveIsolator()
        result = isolator.isolate("手机 13812345678，邮箱 a@b.com")
        assert "13812345678" not in result.clean_text
        assert "a@b.com" not in result.clean_text
        assert result.detected_count >= 2

    def test_占位符格式正确(self):
        isolator = CognitiveIsolator()
        result = isolator.isolate("手机：13900001234")
        placeholders = list(result.redaction_map.keys())
        assert len(placeholders) >= 1
        for ph in placeholders:
            assert ph.startswith("__REDACTED_")
            assert ph.endswith("__")

    def test_set_anonymization_strategy设置策略(self):
        isolator = CognitiveIsolator()
        isolator.set_anonymization_strategy("contextual")
        assert isolator._strategy == "contextual"

    def test_仅critical级敏感度检测(self):
        config = {
            "sensitivity_levels": {"critical": True, "high": False}
        }
        isolator = CognitiveIsolator(config=config)
        result = isolator.isolate("手机 13812345678，密码: abc123456")
        # 手机是 HIGH，应该通过；密码是 CRITICAL，应该被替换
        assert "13812345678" in result.clean_text  # HIGH 未启用
        assert "abc123456" not in result.clean_text  # CRITICAL 已替换


# ─── ContextCompressor ────────────────────────────────────────────────────

class TestEstimateTokens:

    def test_空字符串返回0(self):
        assert estimate_tokens("") == 0

    def test_纯中文约为字数除以1_5(self):
        text = "你好世界"  # 4 个中文字符
        result = estimate_tokens(text)
        assert result == int(4 / 1.5)  # ≈ 2

    def test_纯英文约为字符数除以4(self):
        text = "hello world"  # 11 个字符
        result = estimate_tokens(text)
        assert result == int(11 / 4.0)  # ≈ 2


class TestContextCompressor:

    def _msg(self, role: str, content: str) -> ChatMessage:
        return ChatMessage(role=MessageRole(role), content=content)

    def test_空消息列表返回空结果(self):
        c = ContextCompressor()
        result = c.compress([])
        assert result.messages == []
        assert result.total_tokens_estimate == 0

    def test_system消息始终保留(self):
        c = ContextCompressor()
        msgs = [
            self._msg("system", "你是助手"),
            self._msg("user", "你好"),
            self._msg("assistant", "你好，有什么可以帮你的？"),
        ]
        result = c.compress(msgs)
        roles = [m.role for m in result.messages]
        assert MessageRole.SYSTEM in roles

    def test_超出预算时截断早期消息(self):
        c = ContextCompressor(config={"context_budget": 50})
        msgs = [self._msg("user", "x" * 200) for _ in range(10)]
        result = c.compress(msgs)
        assert result.compressed is True
        assert len(result.messages) < len(msgs)

    def test_未超出预算时保留全部消息(self):
        c = ContextCompressor(config={"context_budget": 10000})
        msgs = [
            self._msg("user", "短消息"),
            self._msg("assistant", "好的"),
        ]
        result = c.compress(msgs)
        assert result.retained_count == len(msgs)
        assert result.compressed is False

    def test_original_count记录原始消息数(self):
        c = ContextCompressor()
        msgs = [self._msg("user", "hello") for _ in range(5)]
        result = c.compress(msgs)
        assert result.original_count == 5

    def test_system消息超出预算时只保留system(self):
        c = ContextCompressor(config={"context_budget": 5})
        msgs = [
            self._msg("system", "x" * 100),
            self._msg("user", "hello"),
        ]
        result = c.compress(msgs)
        # budget 极小，压缩后只保留 system
        assert result.compressed is True


# ─── PrivacyRestorer ──────────────────────────────────────────────────────

class TestPrivacyRestorer:

    def _make_entry(self, original: str) -> RedactionEntry:
        return RedactionEntry(
            original=original,
            type="PHONE",
            sensitivity=SensitivityLevel.HIGH,
            placeholder="__REDACTED_placeholder__",
        )

    def test_占位符被恢复为原始数据(self):
        restorer = PrivacyRestorer()
        ph = "__REDACTED_aabbccddee12__"
        entry = RedactionEntry(
            original="13812345678",
            type="PHONE",
            sensitivity=SensitivityLevel.HIGH,
            placeholder=ph,
        )
        text = f"请联系 {ph} 获取帮助"
        result = restorer.restore(text, {ph: entry})
        assert "13812345678" in result
        assert ph not in result

    def test_空redaction_map直接返回原文(self):
        restorer = PrivacyRestorer()
        text = "Hello World"
        assert restorer.restore(text, {}) == text

    def test_空文本直接返回(self):
        restorer = PrivacyRestorer()
        assert restorer.restore("", {"ph": MagicMock()}) == ""

    def test_多个占位符都被恢复(self):
        restorer = PrivacyRestorer()
        ph1 = "__REDACTED_000000000001__"
        ph2 = "__REDACTED_000000000002__"
        entry1 = RedactionEntry(original="手机1", type="PHONE",
                                sensitivity=SensitivityLevel.HIGH, placeholder=ph1)
        entry2 = RedactionEntry(original="邮箱2", type="EMAIL",
                                sensitivity=SensitivityLevel.HIGH, placeholder=ph2)
        text = f"联系方式：{ph1} 或 {ph2}"
        result = restorer.restore(text, {ph1: entry1, ph2: entry2})
        assert "手机1" in result
        assert "邮箱2" in result
        assert ph1 not in result
        assert ph2 not in result

    def test_check_consistency返回空列表当无残留(self):
        restorer = PrivacyRestorer()
        text = "普通文本，没有占位符"
        issues = restorer.check_consistency(text, {})
        assert issues == []

    def test_check_consistency发现残留占位符(self):
        restorer = PrivacyRestorer()
        text = "文本中有 __REDACTED_aabbccddee12__ 未恢复"
        issues = restorer.check_consistency(text, {})
        assert len(issues) >= 1
        assert "残留" in issues[0]


# ─── PrivacyPipeline ──────────────────────────────────────────────────────

class TestPrivacyPipeline:

    def _make_pipeline(self, enabled=True) -> PrivacyPipeline:
        return PrivacyPipeline(config={"privacy": {"enabled": enabled}})

    @pytest.mark.asyncio
    async def test_disabled时process_input直接返回原文(self):
        pipeline = self._make_pipeline(enabled=False)
        result = await pipeline.process_input(
            message="手机：13812345678",
            messages=[],
        )
        assert result.clean_message == "手机：13812345678"

    @pytest.mark.asyncio
    async def test_enabled时输出clean_message(self):
        pipeline = self._make_pipeline(enabled=True)

        with patch.object(pipeline._memory_injector, "inject",
                          AsyncMock(return_value=MagicMock(
                              memory_text="", memories=[]))), \
             patch.object(pipeline._entity_mapper, "map_entities",
                          AsyncMock(return_value=MagicMock(
                              entities=[], entity_count=0))), \
             patch.object(pipeline._entity_mapper, "persist_entities",
                          AsyncMock()):
            result = await pipeline.process_input(
                message="纯净消息无敏感数据",
                messages=[],
            )

        assert isinstance(result, PipelineResult)
        assert result.trace_id != ""

    @pytest.mark.asyncio
    async def test_trace_id自动生成(self):
        pipeline = self._make_pipeline(enabled=False)
        result = await pipeline.process_input(message="hello", messages=[])
        assert result.trace_id != ""
        assert len(result.trace_id) <= 12

    @pytest.mark.asyncio
    async def test_trace_id可传入(self):
        pipeline = self._make_pipeline(enabled=False)
        result = await pipeline.process_input(
            message="hello", messages=[], trace_id="my-trace-123"
        )
        assert result.trace_id == "my-trace-123"

    def test_restore_output_disabled时直接返回原文(self):
        pipeline = self._make_pipeline(enabled=False)
        text = "含占位符的文本"
        result = pipeline.restore_output(text, {})
        assert result == text

    def test_restore_output空map时直接返回(self):
        pipeline = self._make_pipeline(enabled=True)
        text = "no placeholders here"
        result = pipeline.restore_output(text, {})
        assert result == text

    @pytest.mark.asyncio
    async def test_distill_session异常不抛出(self):
        pipeline = self._make_pipeline(enabled=True)
        with patch.object(pipeline._distiller, "distill",
                          AsyncMock(side_effect=RuntimeError("distill error"))):
            await pipeline.distill_session(messages=[], conversation_id="c1")
        # 不应抛出

    def test_get_pipeline未初始化时抛出RuntimeError(self):
        old = _pipeline_module._pipeline
        try:
            _pipeline_module._pipeline = None
            with pytest.raises(RuntimeError, match="未初始化"):
                from app.pipeline.pipeline import get_pipeline
                get_pipeline()
        finally:
            _pipeline_module._pipeline = old

    def test_init_pipeline设置全局单例(self):
        old = _pipeline_module._pipeline
        try:
            from app.pipeline.pipeline import init_pipeline, get_pipeline
            p = init_pipeline({})
            assert isinstance(p, PrivacyPipeline)
            assert get_pipeline() is p
        finally:
            _pipeline_module._pipeline = old
