"""智能路由测试

覆盖：_GREETING_KEYWORDS（类型 + 成员）
     _try_fast_path（问候命中 / 命令前缀 / 无匹配 / 超长 / available 为空）
     classify_intent（V3: predict_requirements → _derive_intent 流程）
     select_models_for_direct_chat（快速路径 / 无可用模型 / CLI 模型被过滤）
     select_model_for_direct_chat（无模型返回空 / 有模型返回第一个）
     select_model_with_intent（返回 tuple / 无模型 / 快速路径 intent=general）
     ALL_DIMS / _FALLBACK_REQUIREMENTS（15 维完整性验证）
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.kernel.router.smart_router import (
    _try_fast_path,
    _GREETING_KEYWORDS,
    _FALLBACK_REQUIREMENTS,
    ALL_DIMS,
    classify_intent,
    predict_requirements,
    select_models_for_direct_chat,
    select_model_for_direct_chat,
    select_model_with_intent,
)


# ─── _GREETING_KEYWORDS ────────────────────────────────────────────────────

class TestGreetingKeywords:

    def test_类型为frozenset(self):
        assert isinstance(_GREETING_KEYWORDS, frozenset)

    def test_包含中文问候词(self):
        assert "你好" in _GREETING_KEYWORDS
        assert "您好" in _GREETING_KEYWORDS
        assert "嗨" in _GREETING_KEYWORDS

    def test_包含英文问候词(self):
        assert "hi" in _GREETING_KEYWORDS
        assert "hello" in _GREETING_KEYWORDS
        assert "hey" in _GREETING_KEYWORDS

    def test_包含告别词(self):
        assert "再见" in _GREETING_KEYWORDS
        assert "bye" in _GREETING_KEYWORDS
        assert "晚安" in _GREETING_KEYWORDS

    def test_包含感谢词(self):
        assert "谢谢" in _GREETING_KEYWORDS
        assert "thanks" in _GREETING_KEYWORDS

    def test_包含OK类词(self):
        assert "ok" in _GREETING_KEYWORDS
        assert "好的" in _GREETING_KEYWORDS


# ─── _try_fast_path ────────────────────────────────────────────────────────

class TestTryFastPath:

    def test_问候词命中且在available中返回默认模型(self):
        result = _try_fast_path("你好", ["deepseek/deepseek-chat"], "deepseek/deepseek-chat")
        assert result == "deepseek/deepseek-chat"

    def test_问候词不在available_ids中返回None(self):
        result = _try_fast_path("你好", ["qwen/qwen-max"], "deepseek/deepseek-chat")
        assert result is None

    def test_斜杠命令触发快速路径(self):
        result = _try_fast_path("/help", ["deepseek/deepseek-chat"], "deepseek/deepseek-chat")
        assert result == "deepseek/deepseek-chat"

    def test_非问候词无命令前缀返回None(self):
        result = _try_fast_path(
            "帮我写一个快速排序算法",
            ["deepseek/deepseek-chat"],
            "deepseek/deepseek-chat",
        )
        assert result is None

    def test_超过10字符的问候词不触发快速路径(self):
        # "你好你好你好你好你好你好" 超过 10 字符
        result = _try_fast_path(
            "你好你好你好你好你好你好",
            ["deepseek/deepseek-chat"],
            "deepseek/deepseek-chat",
        )
        assert result is None

    def test_消息被strip和lower处理后匹配(self):
        # "  HI  " → strip → "hi" → lower → "hi" ∈ _GREETING_KEYWORDS
        result = _try_fast_path("  HI  ", ["deepseek/deepseek-chat"], "deepseek/deepseek-chat")
        assert result == "deepseek/deepseek-chat"

    def test_available_ids为空时返回None(self):
        result = _try_fast_path("你好", [], "deepseek/deepseek-chat")
        assert result is None

    def test_英文问候词触发快速路径(self):
        result = _try_fast_path("hello", ["deepseek/deepseek-chat"], "deepseek/deepseek-chat")
        assert result == "deepseek/deepseek-chat"

    def test_命令消息default_model不在available时返回None(self):
        result = _try_fast_path("/help", ["qwen/qwen-max"], "deepseek/deepseek-chat")
        assert result is None


# ─── classify_intent（V3：predict_requirements → _derive_intent）─────────

class TestClassifyIntent:
    """V3 的 classify_intent 通过 predict_requirements（JSON 解析）→ _derive_intent 工作"""

    @pytest.mark.asyncio
    async def test_get_router异常时使用兜底向量(self):
        with patch("app.kernel.router.smart_router.get_router",
                   side_effect=RuntimeError("router not initialized")):
            result = await classify_intent("帮我解方程", {})
        # 兜底向量 top_dim=chinese_writing:5 → 映射到 long_text
        assert result in ("general", "long_text")

    @pytest.mark.asyncio
    async def test_LLM返回coding高分时返回coding(self):
        """mock LLM 返回有效 JSON，coding 维度高分 → 意图为 coding"""
        coding_json = json.dumps({
            "math_reasoning": 2, "coding": 9, "long_context": 1,
            "chinese_writing": 1, "agent_tool_use": 5, "knowledge_tech": 7,
            "knowledge_business": 0, "knowledge_legal": 0, "knowledge_medical": 0,
            "logic": 3, "reasoning": 3, "instruction_following": 5,
            "cost_sensitivity": 3, "speed_priority": 4, "context_need": 1,
        })
        mock_router = MagicMock()
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router), \
             patch("app.kernel.router.llm_router.collect_stream_text",
                   AsyncMock(return_value=coding_json)):
            result = await classify_intent("写一个快速排序", {})
        assert result == "coding"

    @pytest.mark.asyncio
    async def test_LLM返回reasoning高分时返回reasoning(self):
        reasoning_json = json.dumps({
            "math_reasoning": 9, "coding": 2, "long_context": 1,
            "chinese_writing": 1, "agent_tool_use": 0, "knowledge_tech": 3,
            "knowledge_business": 0, "knowledge_legal": 0, "knowledge_medical": 0,
            "logic": 7, "reasoning": 8, "instruction_following": 4,
            "cost_sensitivity": 2, "speed_priority": 3, "context_need": 1,
        })
        mock_router = MagicMock()
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router), \
             patch("app.kernel.router.llm_router.collect_stream_text",
                   AsyncMock(return_value=reasoning_json)):
            result = await classify_intent("计算积分", {})
        assert result == "reasoning"

    @pytest.mark.asyncio
    async def test_LLM返回long_text高分时返回long_text(self):
        long_text_json = json.dumps({
            "math_reasoning": 0, "coding": 0, "long_context": 8,
            "chinese_writing": 9, "agent_tool_use": 1, "knowledge_tech": 2,
            "knowledge_business": 2, "knowledge_legal": 2, "knowledge_medical": 1,
            "logic": 2, "reasoning": 2, "instruction_following": 3,
            "cost_sensitivity": 3, "speed_priority": 2, "context_need": 7,
        })
        mock_router = MagicMock()
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router), \
             patch("app.kernel.router.llm_router.collect_stream_text",
                   AsyncMock(return_value=long_text_json)):
            result = await classify_intent("写一篇三千字报告", {})
        assert result == "long_text"

    @pytest.mark.asyncio
    async def test_LLM返回低分时意图为general(self):
        """所有维度 ≤ 4 时，_derive_intent 返回 general"""
        low_json = json.dumps({
            "math_reasoning": 2, "coding": 2, "long_context": 2,
            "chinese_writing": 3, "agent_tool_use": 3, "knowledge_tech": 2,
            "knowledge_business": 2, "knowledge_legal": 1, "knowledge_medical": 1,
            "logic": 3, "reasoning": 3, "instruction_following": 4,
            "cost_sensitivity": 2, "speed_priority": 3, "context_need": 2,
        })
        mock_router = MagicMock()
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router), \
             patch("app.kernel.router.llm_router.collect_stream_text",
                   AsyncMock(return_value=low_json)):
            result = await classify_intent("随便问个问题", {})
        assert result == "general"

    @pytest.mark.asyncio
    async def test_collect_stream_text异常时使用兜底向量(self):
        mock_router = MagicMock()
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router), \
             patch("app.kernel.router.llm_router.collect_stream_text",
                   AsyncMock(side_effect=Exception("LLM error"))):
            result = await classify_intent("测试", {})
        # 兜底向量 top_dim=chinese_writing:5 → 映射到 long_text
        assert result in ("general", "long_text")

    @pytest.mark.asyncio
    async def test_LLM返回非JSON时使用兜底向量(self):
        mock_router = MagicMock()
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router), \
             patch("app.kernel.router.llm_router.collect_stream_text",
                   AsyncMock(return_value="这不是JSON")):
            result = await classify_intent("测试消息", {})
        # 兜底向量工作正常，不崩溃
        assert isinstance(result, str)
        assert result in ("general", "coding", "reasoning", "long_text")


# ─── select_models_for_direct_chat ─────────────────────────────────────────

class TestSelectModelsForDirectChat:

    @pytest.mark.asyncio
    async def test_无可用API模型时返回空列表(self):
        mock_router = MagicMock()
        mock_router.get_available_models.return_value = []
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router):
            result = await select_models_for_direct_chat("test", {})
        assert result == []

    @pytest.mark.asyncio
    async def test_快速路径直接返回默认模型(self):
        mock_router = MagicMock()
        mock_router.get_available_models.return_value = [
            {"id": "deepseek/deepseek-chat", "type": "api"},
        ]
        config = {"llm": {"default_model": "deepseek/deepseek-chat"}}
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router):
            result = await select_models_for_direct_chat("你好", config)
        assert result == ["deepseek/deepseek-chat"]

    @pytest.mark.asyncio
    async def test_CLI模型被过滤不参与意图路由(self):
        mock_router = MagicMock()
        mock_router.get_available_models.return_value = [
            {"id": "cli:claude", "type": "cli"},
        ]
        config = {"llm": {"default_model": "cli:claude"}}
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router):
            result = await select_models_for_direct_chat("写代码", config)
        assert result == []

    @pytest.mark.asyncio
    async def test_返回不超过top_k个模型(self):
        mock_router = MagicMock()
        mock_router.get_available_models.return_value = [
            {"id": f"provider/model-{i}", "type": "api"} for i in range(5)
        ]
        config = {"llm": {"default_model": "provider/model-0"}}
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router), \
             patch("app.kernel.router.smart_router.classify_intent",
                   AsyncMock(return_value="general")), \
             patch("app.evaluation.matrix.model_matrix.get_matrix") as mock_m:
            mock_m.return_value.get_model_profile.return_value = None
            result = await select_models_for_direct_chat("问个问题", config, top_k=2)
        assert len(result) <= 2


# ─── select_model_for_direct_chat ──────────────────────────────────────────

class TestSelectModelForDirectChat:

    @pytest.mark.asyncio
    async def test_无可用模型时返回空字符串(self):
        mock_router = MagicMock()
        mock_router.get_available_models.return_value = []
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router):
            result = await select_model_for_direct_chat("test", {})
        assert result == ""

    @pytest.mark.asyncio
    async def test_有模型时快速路径返回默认模型(self):
        mock_router = MagicMock()
        mock_router.get_available_models.return_value = [
            {"id": "deepseek/deepseek-chat", "type": "api"},
        ]
        config = {"llm": {"default_model": "deepseek/deepseek-chat"}}
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router):
            result = await select_model_for_direct_chat("你好", config)
        assert result == "deepseek/deepseek-chat"


# ─── select_model_with_intent ──────────────────────────────────────────────

class TestSelectModelWithIntent:

    @pytest.mark.asyncio
    async def test_返回三元组(self):
        mock_router = MagicMock()
        mock_router.get_available_models.return_value = [
            {"id": "deepseek/deepseek-chat", "type": "api"},
        ]
        config = {"llm": {"default_model": "deepseek/deepseek-chat"}}
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router):
            result = await select_model_with_intent("你好", config)
        assert isinstance(result, tuple)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_无可用模型时返回空字符串和general(self):
        mock_router = MagicMock()
        mock_router.get_available_models.return_value = []
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router):
            model_id, intent, candidates = await select_model_with_intent("test", {})
        assert model_id == ""
        assert intent == "general"
        assert candidates == []

    @pytest.mark.asyncio
    async def test_快速路径返回general意图(self):
        mock_router = MagicMock()
        mock_router.get_available_models.return_value = [
            {"id": "deepseek/deepseek-chat", "type": "api"},
        ]
        config = {"llm": {"default_model": "deepseek/deepseek-chat"}}
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router):
            model_id, intent, candidates = await select_model_with_intent("hi", config)
        assert model_id == "deepseek/deepseek-chat"
        assert intent == "general"
        assert candidates == ["deepseek/deepseek-chat"]

    @pytest.mark.asyncio
    async def test_意图分类结果被保留在返回值中(self):
        """select_model_with_intent 内部调用 predict_requirements → _derive_intent"""
        coding_req = {
            "math_reasoning": 2, "coding": 9, "long_context": 1,
            "chinese_writing": 1, "agent_tool_use": 5, "knowledge_tech": 7,
            "knowledge_business": 0, "knowledge_legal": 0, "knowledge_medical": 0,
            "logic": 3, "reasoning": 3, "instruction_following": 5,
            "cost_sensitivity": 3, "speed_priority": 4, "context_need": 1,
        }
        mock_router = MagicMock()
        mock_router.get_available_models.return_value = [
            {"id": "deepseek/deepseek-chat", "type": "api"},
        ]
        config = {"llm": {"default_model": "deepseek/deepseek-chat"}}
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router), \
             patch("app.kernel.router.smart_router.predict_requirements",
                   AsyncMock(return_value=coding_req)), \
             patch("app.evaluation.matrix.model_matrix.get_matrix") as mock_m:
            mock_m.return_value.get_model_profile.return_value = None
            model_id, intent, candidates = await select_model_with_intent("写一个排序算法", config)
        assert intent == "coding"


# ─── ALL_DIMS / _FALLBACK_REQUIREMENTS 15 维完整性 ─────────────────────────

class TestAllDims15维:

    def test_ALL_DIMS包含15个维度(self):
        assert len(ALL_DIMS) == 15

    def test_ALL_DIMS包含12个能力维度(self):
        capability_dims = [
            "math_reasoning", "coding", "long_context", "chinese_writing",
            "agent_tool_use", "knowledge_tech", "knowledge_business",
            "knowledge_legal", "knowledge_medical", "logic", "reasoning",
            "instruction_following",
        ]
        for dim in capability_dims:
            assert dim in ALL_DIMS, f"缺少能力维度: {dim}"

    def test_ALL_DIMS包含3个规格需求维度(self):
        spec_dims = ["cost_sensitivity", "speed_priority", "context_need"]
        for dim in spec_dims:
            assert dim in ALL_DIMS, f"缺少规格维度: {dim}"

    def test_兜底向量包含全部15个维度(self):
        for dim in ALL_DIMS:
            assert dim in _FALLBACK_REQUIREMENTS, f"兜底向量缺少维度: {dim}"

    def test_兜底向量值范围0到10(self):
        for dim, val in _FALLBACK_REQUIREMENTS.items():
            assert 0 <= val <= 10, f"{dim}={val} 超出范围"

    def test_兜底向量规格维度有合理默认值(self):
        assert _FALLBACK_REQUIREMENTS["cost_sensitivity"] == 3
        assert _FALLBACK_REQUIREMENTS["speed_priority"] == 4
        assert _FALLBACK_REQUIREMENTS["context_need"] == 3


# ─── predict_requirements 15 维输出 ──────────────────────────────────────

class TestPredictRequirements15维:

    @pytest.mark.asyncio
    async def test_返回15维向量(self):
        """LLM 返回有效 JSON 时，输出包含全部 15 个维度"""
        full_json = json.dumps({
            "math_reasoning": 5, "coding": 3, "long_context": 2,
            "chinese_writing": 4, "agent_tool_use": 6, "knowledge_tech": 5,
            "knowledge_business": 1, "knowledge_legal": 0, "knowledge_medical": 0,
            "logic": 4, "reasoning": 5, "instruction_following": 6,
            "cost_sensitivity": 7, "speed_priority": 3, "context_need": 2,
        })
        mock_router = MagicMock()
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router), \
             patch("app.kernel.router.llm_router.collect_stream_text",
                   AsyncMock(return_value=full_json)):
            req = await predict_requirements("测试消息", {})
        assert len(req) == 15
        assert req["cost_sensitivity"] == 7
        assert req["speed_priority"] == 3
        assert req["context_need"] == 2

    @pytest.mark.asyncio
    async def test_LLM未返回规格维度时默认为0(self):
        """旧版 LLM 只返回 12 维时，新增的 3 维默认为 0"""
        old_json = json.dumps({
            "math_reasoning": 5, "coding": 8, "long_context": 2,
            "chinese_writing": 3, "agent_tool_use": 6, "knowledge_tech": 7,
            "knowledge_business": 0, "knowledge_legal": 0, "knowledge_medical": 0,
            "logic": 5, "reasoning": 4, "instruction_following": 7,
        })
        mock_router = MagicMock()
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router), \
             patch("app.kernel.router.llm_router.collect_stream_text",
                   AsyncMock(return_value=old_json)):
            req = await predict_requirements("写代码", {})
        assert len(req) == 15
        assert req["cost_sensitivity"] == 0
        assert req["speed_priority"] == 0
        assert req["context_need"] == 0
        # 能力维度正常保留
        assert req["coding"] == 8

    @pytest.mark.asyncio
    async def test_值超过10被截断(self):
        extreme_json = json.dumps({
            "math_reasoning": 15, "coding": -5, "long_context": 0,
            "chinese_writing": 0, "agent_tool_use": 0, "knowledge_tech": 0,
            "knowledge_business": 0, "knowledge_legal": 0, "knowledge_medical": 0,
            "logic": 0, "reasoning": 0, "instruction_following": 0,
            "cost_sensitivity": 20, "speed_priority": -1, "context_need": 0,
        })
        mock_router = MagicMock()
        with patch("app.kernel.router.smart_router.get_router", return_value=mock_router), \
             patch("app.kernel.router.llm_router.collect_stream_text",
                   AsyncMock(return_value=extreme_json)):
            req = await predict_requirements("测试", {})
        assert req["math_reasoning"] == 10  # 截断到 10
        assert req["coding"] == 0           # 截断到 0
        assert req["cost_sensitivity"] == 10  # 截断到 10
        assert req["speed_priority"] == 0     # 截断到 0
