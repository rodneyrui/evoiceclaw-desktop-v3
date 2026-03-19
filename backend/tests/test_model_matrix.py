"""动态模型能力矩阵测试

覆盖：ModelProfile 默认值
     score_model_for_requirement_dict（15 维需求向量，含规格维度动态权重）
     ModelMatrix 加载逻辑
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from app.evaluation.matrix.model_matrix import (
    ModelProfile,
    score_model_for_requirement_dict,
    select_models_by_requirements,
    ModelMatrix,
)


# ─── ModelProfile 默认值 ───────────────────────────────────────────────────

class TestModelProfile:

    def test_默认能力分数为60(self):
        p = ModelProfile(provider="test", model="m1", display_name="Test")
        assert p.math_reasoning == 60.0
        assert p.coding == 60.0
        assert p.reasoning == 60.0

    def test_默认not_measured_dims为空列表(self):
        p = ModelProfile(provider="test", model="m1", display_name="Test")
        assert p.not_measured_dims == []

    def test_默认mode为analysis(self):
        p = ModelProfile(provider="test", model="m1", display_name="Test")
        assert p.mode == "analysis"

    def test_默认cost_level为3(self):
        p = ModelProfile(provider="test", model="m1", display_name="Test")
        assert p.cost_level == 3

    def test_默认规格分数(self):
        p = ModelProfile(provider="test", model="m1", display_name="Test")
        assert p.cost_score == 50.0
        assert p.speed_score == 50.0
        assert p.context_score == 84.0

    def test_自定义字段可设置(self):
        p = ModelProfile(
            provider="deepseek", model="deepseek-chat", display_name="DS",
            coding=90.0, cost_level=1, mode="fast",
            cost_score=90.0, speed_score=80.0, context_score=95.0,
        )
        assert p.coding == 90.0
        assert p.cost_level == 1
        assert p.mode == "fast"
        assert p.cost_score == 90.0


# ─── ModelMatrix 加载逻辑 ──────────────────────────────────────────────────

class TestModelMatrixLoad:

    def test_初始状态未加载(self):
        m = ModelMatrix()
        assert m._loaded is False

    def test_预置文件不存在时缓存为空(self):
        m = ModelMatrix()
        with patch.object(type(m), '_load_preset', wraps=m._load_preset):
            with patch("app.evaluation.matrix.model_matrix.PRESET_DATA_PATH") as mock_path:
                mock_path.exists.return_value = False
                m._load_preset()
        assert m._cache == {}
        assert m._loaded is True

    def test_加载后get_model_profile返回画像(self, tmp_path):
        preset_data = {
            "version": "3.0",
            "models": [{
                "model_id": "test/model",
                "source": "preset",
                "dimension_scores": {"coding": 85},
                "avg_latency_ms": 300,
                "cost_input_per_m": 1.0,
                "cost_output_per_m": 2.0,
                "context_window": 128000,
            }]
        }
        preset_file = tmp_path / "preset_evaluations.json"
        preset_file.write_text(json.dumps(preset_data), encoding="utf-8")

        m = ModelMatrix()
        with patch("app.evaluation.matrix.model_matrix.PRESET_DATA_PATH", preset_file):
            m._load_preset()

        profile = m.get_model_profile("test/model")
        assert profile is not None
        assert profile.coding == 85.0

    def test_force_refresh重新加载(self):
        m = ModelMatrix()
        m._loaded = True
        m._cache = {"old": "data"}
        with patch("app.evaluation.matrix.model_matrix.PRESET_DATA_PATH") as mock_path:
            mock_path.exists.return_value = False
            m.force_refresh()
        assert m._cache == {}

    def test_ensure_loaded只加载一次(self):
        m = ModelMatrix()
        m._loaded = True
        m._cache = {"cached": "data"}
        m._ensure_loaded()
        # 已加载，不会重新加载，缓存不变
        assert m._cache == {"cached": "data"}


# ─── score_model_for_requirement_dict（15 维需求向量）─────────────────────

class TestScoreModelForRequirementDict:
    """测试 cost_score/speed_score/context_score 规格维度"""

    def test_全零需求时得分为0(self):
        profile = ModelProfile(provider="t", model="m", display_name="T")
        req = {dim: 0 for dim in [
            "math_reasoning", "coding", "long_context", "chinese_writing",
            "agent_tool_use", "knowledge_tech", "knowledge_business",
            "knowledge_legal", "knowledge_medical", "logic", "reasoning",
            "instruction_following", "cost_sensitivity", "speed_priority",
            "context_need",
        ]}
        score = score_model_for_requirement_dict(profile, req)
        assert score == 0.0

    def test_cost_sensitivity高分偏好低成本模型(self):
        cheap = ModelProfile(provider="t", model="c", display_name="Cheap", cost_score=90.0)
        expensive = ModelProfile(provider="t", model="e", display_name="Exp", cost_score=20.0)
        req = {"cost_sensitivity": 10}
        score_cheap = score_model_for_requirement_dict(cheap, req)
        score_exp = score_model_for_requirement_dict(expensive, req)
        assert score_cheap > score_exp

    def test_cost_sensitivity为0时成本无影响(self):
        cheap = ModelProfile(provider="t", model="c", display_name="Cheap", cost_score=90.0, coding=80.0)
        expensive = ModelProfile(provider="t", model="e", display_name="Exp", cost_score=20.0, coding=80.0)
        req = {"coding": 8, "cost_sensitivity": 0}
        score_cheap = score_model_for_requirement_dict(cheap, req)
        score_exp = score_model_for_requirement_dict(expensive, req)
        assert score_cheap == score_exp

    def test_speed_priority高分偏好快速模型(self):
        fast_model = ModelProfile(provider="t", model="f", display_name="Fast", speed_score=90.0)
        slow_model = ModelProfile(provider="t", model="s", display_name="Slow", speed_score=20.0)
        req = {"speed_priority": 10}
        score_fast = score_model_for_requirement_dict(fast_model, req)
        score_slow = score_model_for_requirement_dict(slow_model, req)
        assert score_fast > score_slow

    def test_speed_priority为0时速度无影响(self):
        fast_model = ModelProfile(provider="t", model="f", display_name="Fast", speed_score=90.0, coding=80.0)
        slow_model = ModelProfile(provider="t", model="s", display_name="Slow", speed_score=20.0, coding=80.0)
        req = {"coding": 8, "speed_priority": 0}
        score_fast = score_model_for_requirement_dict(fast_model, req)
        score_slow = score_model_for_requirement_dict(slow_model, req)
        assert score_fast == score_slow

    def test_context_need高分偏好大上下文模型(self):
        small_ctx = ModelProfile(provider="t", model="s", display_name="Small", context_score=30.0)
        big_ctx = ModelProfile(provider="t", model="b", display_name="Big", context_score=95.0)
        req = {"context_need": 10}
        score_small = score_model_for_requirement_dict(small_ctx, req)
        score_big = score_model_for_requirement_dict(big_ctx, req)
        assert score_big > score_small

    def test_context_need各档位评分递增(self):
        profiles = [
            ModelProfile(provider="t", model="8k", display_name="8K", context_score=36.0),
            ModelProfile(provider="t", model="32k", display_name="32K", context_score=60.0),
            ModelProfile(provider="t", model="128k", display_name="128K", context_score=84.0),
            ModelProfile(provider="t", model="200k", display_name="200K", context_score=92.0),
        ]
        req = {"context_need": 8}
        scores = [score_model_for_requirement_dict(p, req) for p in profiles]
        for i in range(len(scores) - 1):
            assert scores[i] < scores[i + 1], \
                f"{profiles[i].model} 应 < {profiles[i+1].model}"

    def test_能力维度与规格维度共同作用(self):
        cheap_good = ModelProfile(provider="t", model="c", display_name="Cheap", cost_score=90.0, coding=90.0)
        expensive_good = ModelProfile(provider="t", model="e", display_name="Exp", cost_score=20.0, coding=90.0)
        req = {"coding": 8, "cost_sensitivity": 8}
        score_cheap = score_model_for_requirement_dict(cheap_good, req)
        score_exp = score_model_for_requirement_dict(expensive_good, req)
        assert score_cheap > score_exp

    def test_不含规格维度的旧版需求向量仍可工作(self):
        profile = ModelProfile(provider="t", model="m", display_name="T", coding=80.0)
        req = {"coding": 8, "reasoning": 5}
        score = score_model_for_requirement_dict(profile, req)
        assert score > 0

    def test_无硬编码成本惩罚(self):
        """cost_sensitivity=0 时，高成本模型不被惩罚"""
        expensive = ModelProfile(provider="t", model="e", display_name="Exp", cost_score=10.0, coding=90.0)
        req = {"coding": 8, "cost_sensitivity": 0}
        score = score_model_for_requirement_dict(expensive, req)
        expected_coding_score = 8 * (90.0 / 20.0)
        assert abs(score - expected_coding_score) < 0.01

    def test_无硬编码mode加成(self):
        """speed_priority=0 时，不同速度模型得分相同"""
        fast_model = ModelProfile(provider="t", model="f", display_name="Fast", speed_score=90.0, coding=80.0)
        slow_model = ModelProfile(provider="t", model="s", display_name="Slow", speed_score=20.0, coding=80.0)
        req = {"coding": 8, "speed_priority": 0}
        score_fast = score_model_for_requirement_dict(fast_model, req)
        score_slow = score_model_for_requirement_dict(slow_model, req)
        assert score_fast == score_slow


# ─── 协作 bonus（parallel_tool_calls 升级）────────────────────────────────

class TestCollaborationBoost:
    """测试高协作需求时 parallel_tool_calls 模型获得 bonus"""

    def _build_matrix_with_models(self, profiles: list[ModelProfile]) -> ModelMatrix:
        """构造一个包含指定模型的 ModelMatrix"""
        m = ModelMatrix()
        m._cache = {p.display_name: p for p in profiles}
        m._loaded = True
        return m

    def test_高协作需求时并行模型排名上升(self):
        """agent_tool_use=8 时，parallel_tool_calls=True 的模型应获得 bonus"""
        # MiniMax：agent_tool_use 低但支持并行，coding 更强
        minimax = ModelProfile(
            provider="minimax", model="MiniMax-M2.5", display_name="minimax/MiniMax-M2.5",
            agent_tool_use=66.0, coding=90.0,
            parallel_tool_calls=True,
        )
        # 对照模型：agent_tool_use 高但不支持并行，coding 稍弱
        other = ModelProfile(
            provider="other", model="other-chat", display_name="other/other-chat",
            agent_tool_use=99.0, coding=80.0,
            parallel_tool_calls=False,
        )

        matrix = self._build_matrix_with_models([minimax, other])
        req = {"agent_tool_use": 8, "coding": 8}

        with patch("app.evaluation.matrix.model_matrix.get_matrix", return_value=matrix), \
             patch("app.evaluation.matrix.model_matrix.random.uniform", return_value=0.0):
            result = select_models_by_requirements(
                req,
                ["minimax/MiniMax-M2.5", "other/other-chat"],
                top_k=2,
            )

        # 15% bonus 弥补了 agent_tool_use 的分差，MiniMax 应排第一
        assert result[0] == "minimax/MiniMax-M2.5"

    def test_低协作需求时无bonus(self):
        """agent_tool_use=3 时，不应触发协作 bonus"""
        minimax = ModelProfile(
            provider="minimax", model="MiniMax-M2.5", display_name="minimax/MiniMax-M2.5",
            agent_tool_use=66.0, coding=85.0,
            parallel_tool_calls=True,
        )
        deepseek = ModelProfile(
            provider="deepseek", model="deepseek-chat", display_name="deepseek/deepseek-chat",
            agent_tool_use=99.0, coding=94.0,
            parallel_tool_calls=False,
        )

        matrix = self._build_matrix_with_models([minimax, deepseek])
        req = {"agent_tool_use": 3, "coding": 8}

        with patch("app.evaluation.matrix.model_matrix.get_matrix", return_value=matrix), \
             patch("app.evaluation.matrix.model_matrix.random.uniform", return_value=0.0):
            result = select_models_by_requirements(
                req,
                ["minimax/MiniMax-M2.5", "deepseek/deepseek-chat"],
                top_k=2,
            )

        # 无 bonus，DeepSeek 凭更高的 agent_tool_use 和 coding 分数胜出
        assert result[0] == "deepseek/deepseek-chat"

    def test_parallel_tool_calls默认为False(self):
        p = ModelProfile(provider="t", model="m", display_name="T")
        assert p.parallel_tool_calls is False

    def test_parallel_tool_calls可设置为True(self):
        p = ModelProfile(provider="t", model="m", display_name="T", parallel_tool_calls=True)
        assert p.parallel_tool_calls is True
