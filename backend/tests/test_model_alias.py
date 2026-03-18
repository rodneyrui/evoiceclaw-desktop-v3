"""模型别名检测单元测试

覆盖：_build_model_aliases, _detect_explicit_model
"""

import pytest
from unittest.mock import MagicMock, patch

import app.services.model_alias as model_alias_module
from app.services.model_alias import (
    _build_model_aliases,
    _detect_explicit_model,
)


# ── 固定的测试用模型列表 ──────────────────────────────────────

_FAKE_MODELS = [
    {"id": "deepseek/deepseek-chat",     "name": "DeepSeek V3"},
    {"id": "deepseek/deepseek-reasoner", "name": "DeepSeek R1"},
    {"id": "minimax/MiniMax-M2.5",       "name": "MiniMax M2.5"},
    {"id": "qwen/qwen-max",              "name": "通义千问 Max"},
    {"id": "moonshot/moonshot-v1-128k",  "name": "Kimi"},
    {"id": "moonshot/kimi-k2.5",         "name": "Kimi K2.5"},
]


def _make_router_mock():
    """构造返回 _FAKE_MODELS 的 router mock"""
    router = MagicMock()
    router.get_available_models.return_value = _FAKE_MODELS
    return router


@pytest.fixture(autouse=True)
def reset_model_aliases():
    """每个测试前后重置全局别名缓存，避免测试间相互污染"""
    model_alias_module._MODEL_ALIASES = {}
    yield
    model_alias_module._MODEL_ALIASES = {}


# ── _build_model_aliases ─────────────────────────────────────

class TestBuildModelAliases:
    def _build(self):
        with patch("app.services.model_alias.get_router", return_value=_make_router_mock()):
            return _build_model_aliases({})

    def test_model_id本身作为小写别名(self):
        aliases = self._build()
        assert aliases.get("deepseek/deepseek-chat") == "deepseek/deepseek-chat"

    def test_slash后的短名作为别名(self):
        aliases = self._build()
        assert aliases.get("deepseek-chat") == "deepseek/deepseek-chat"

    def test_模型显示名作为别名(self):
        aliases = self._build()
        # "DeepSeek V3" → 小写 "deepseek v3"
        assert aliases.get("deepseek v3") == "deepseek/deepseek-chat"

    def test_手动别名deepseek(self):
        aliases = self._build()
        assert aliases.get("deepseek") == "deepseek/deepseek-chat"

    def test_手动别名r1(self):
        aliases = self._build()
        assert aliases.get("r1") == "deepseek/deepseek-reasoner"

    def test_手动别名kimi(self):
        aliases = self._build()
        assert aliases.get("kimi") == "moonshot/moonshot-v1-128k"

    def test_手动别名千问(self):
        aliases = self._build()
        assert aliases.get("千问") == "qwen/qwen-max"

    def test_手动别名通义千问(self):
        aliases = self._build()
        assert aliases.get("通义千问") == "qwen/qwen-max"

    def test_不可用模型的手动别名不加入(self):
        """kimi-k2.5 在列表中存在，对应别名应可用"""
        aliases = self._build()
        assert aliases.get("kimi k2.5") == "moonshot/kimi-k2.5"

    def test_不可用模型的手动别名被过滤(self):
        """如果 model 不在 available_ids 中，别名不应出现"""
        fake_models_no_minimax = [m for m in _FAKE_MODELS if "minimax" not in m["id"]]
        router = MagicMock()
        router.get_available_models.return_value = fake_models_no_minimax
        with patch("app.services.model_alias.get_router", return_value=router):
            aliases = _build_model_aliases({})
        assert "minimax" not in aliases
        assert "m2.5" not in aliases


# ── _detect_explicit_model ───────────────────────────────────

class TestDetectExplicitModel:
    def _detect(self, message: str) -> tuple[str | None, str]:
        with patch("app.services.model_alias.get_router", return_value=_make_router_mock()):
            return _detect_explicit_model(message, {})

    # ── 策略1：正则匹配 ──

    def test_让X来做_匹配deepseek(self):
        model_id, _ = self._detect("让deepseek来帮我写一段代码")
        assert model_id == "deepseek/deepseek-chat"

    def test_用X来做_匹配r1(self):
        model_id, _ = self._detect("请用r1来分析这个问题")
        assert model_id == "deepseek/deepseek-reasoner"

    def test_使用X来做_匹配kimi(self):
        model_id, _ = self._detect("请使用kimi来回答")
        assert model_id == "moonshot/moonshot-v1-128k"

    def test_X请帮我_句首模型名(self):
        model_id, _ = self._detect("deepseek，请帮我写一封邮件")
        assert model_id == "deepseek/deepseek-chat"

    def test_at符号指定模型(self):
        model_id, _ = self._detect("@r1 请分析这份报告")
        assert model_id == "deepseek/deepseek-reasoner"

    def test_原始消息原样返回(self):
        msg = "让deepseek来分析"
        _, returned_msg = self._detect(msg)
        assert returned_msg == msg

    # ── 策略2：兜底前缀匹配 ──

    def test_消息开头是别名加空格_匹配(self):
        model_id, _ = self._detect("deepseek 请帮我总结")
        assert model_id == "deepseek/deepseek-chat"

    def test_消息开头是别名加冒号_匹配(self):
        model_id, _ = self._detect("r1:分析这个问题")
        assert model_id == "deepseek/deepseek-reasoner"

    def test_消息开头是别名加中文逗号_匹配(self):
        model_id, _ = self._detect("千问，请解释一下")
        assert model_id == "qwen/qwen-max"

    def test_消息开头是别名加请字_匹配(self):
        model_id, _ = self._detect("kimi请帮我翻译")
        assert model_id == "moonshot/moonshot-v1-128k"

    def test_长别名优先于短别名_deepseek_r1(self):
        """'deepseek r1' 应匹配 deepseek-reasoner 而非 deepseek-chat"""
        model_id, _ = self._detect("deepseek r1 请分析这个问题")
        assert model_id == "deepseek/deepseek-reasoner"

    def test_别名后无分隔符_不匹配(self):
        """deepseekpro 不应被识别为 deepseek"""
        model_id, _ = self._detect("deepseekpro很好用")
        assert model_id is None

    # ── 未命中场景 ──

    def test_普通消息无模型指定_返回None(self):
        model_id, _ = self._detect("今天天气怎么样？")
        assert model_id is None

    def test_空字符串_返回None(self):
        model_id, _ = self._detect("")
        assert model_id is None

    def test_别名出现在句中但不匹配句式_策略2兜底也不匹配(self):
        """'我用了deepseek很久了' 中 deepseek 不在句首，且不匹配句式"""
        model_id, _ = self._detect("我用了deepseek很久了，觉得不错")
        # 策略1 中 '用了deepseek很久了' 可能被 '用...做' 正则捕获，
        # 但候选词是 'deepseek很久了'，不在别名表中，所以应返回 None
        # 策略2 兜底要求消息开头，也不匹配
        assert model_id is None

    # ── 别名缓存懒加载 ──

    def test_第一次调用会构建缓存(self):
        assert model_alias_module._MODEL_ALIASES == {}
        with patch("app.services.model_alias.get_router", return_value=_make_router_mock()):
            _detect_explicit_model("普通消息", {})
        assert model_alias_module._MODEL_ALIASES != {}

    def test_第二次调用复用缓存不重复构建(self):
        with patch("app.services.model_alias.get_router", return_value=_make_router_mock()) as mock_get_router:
            _detect_explicit_model("消息1", {})
            _detect_explicit_model("消息2", {})
        # get_router 只在第一次调用时被使用（构建别名时）
        assert mock_get_router.call_count == 1
