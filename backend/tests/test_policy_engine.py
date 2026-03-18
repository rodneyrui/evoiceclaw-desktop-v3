"""PolicyEngine 单元测试"""

from app.kernel.router.policy_engine import (
    PolicyConstraint,
    PolicyEngine,
    init_policy_engine,
    get_policy_engine,
)


class TestPolicyConstraint:
    """PolicyConstraint 数据类测试"""

    def test_defaults(self):
        c = PolicyConstraint()
        assert c.exclude_providers == set()
        assert c.exclude_models == set()
        assert c.require_tool_support is False


class TestPolicyEngineFilter:
    """filter_models 筛选逻辑测试"""

    def test_no_constraints_passes_all(self):
        engine = PolicyEngine()
        candidates = ["deepseek/deepseek-chat", "openai/gpt-4o", "kimi/moonshot-v1"]
        result = engine.filter_models(candidates)
        assert result == candidates

    def test_exclude_providers(self):
        engine = PolicyEngine()
        engine._constraints = PolicyConstraint(exclude_providers={"openai"})
        candidates = ["deepseek/deepseek-chat", "openai/gpt-4o", "openai/gpt-4o-mini", "kimi/moonshot-v1"]
        result = engine.filter_models(candidates)
        assert result == ["deepseek/deepseek-chat", "kimi/moonshot-v1"]

    def test_exclude_models(self):
        engine = PolicyEngine()
        engine._constraints = PolicyConstraint(exclude_models={"deepseek/deepseek-reasoner"})
        candidates = ["deepseek/deepseek-chat", "deepseek/deepseek-reasoner", "kimi/moonshot-v1"]
        result = engine.filter_models(candidates)
        assert result == ["deepseek/deepseek-chat", "kimi/moonshot-v1"]

    def test_all_excluded_fallback(self):
        """全部排除时应回退原始列表"""
        engine = PolicyEngine()
        engine._constraints = PolicyConstraint(exclude_providers={"deepseek", "openai"})
        candidates = ["deepseek/deepseek-chat", "openai/gpt-4o"]
        result = engine.filter_models(candidates)
        assert result == candidates  # 回退

    def test_empty_candidates(self):
        engine = PolicyEngine()
        engine._constraints = PolicyConstraint(exclude_providers={"openai"})
        result = engine.filter_models([])
        assert result == []

    def test_extra_constraints_merged(self):
        engine = PolicyEngine()
        engine._constraints = PolicyConstraint(exclude_providers={"openai"})
        extra = PolicyConstraint(exclude_models={"deepseek/deepseek-chat"})
        candidates = ["deepseek/deepseek-chat", "deepseek/deepseek-coder", "openai/gpt-4o"]
        result = engine.filter_models(candidates, extra_constraints=extra)
        assert result == ["deepseek/deepseek-coder"]

    def test_combined_exclude(self):
        engine = PolicyEngine()
        engine._constraints = PolicyConstraint(
            exclude_providers={"openai"},
            exclude_models={"kimi/moonshot-v1"},
        )
        candidates = ["deepseek/deepseek-chat", "openai/gpt-4o", "kimi/moonshot-v1", "kimi/kimi-k2"]
        result = engine.filter_models(candidates)
        assert result == ["deepseek/deepseek-chat", "kimi/kimi-k2"]

    def test_model_without_provider_prefix(self):
        """无 provider 前缀的模型 ID"""
        engine = PolicyEngine()
        engine._constraints = PolicyConstraint(exclude_models={"local-model"})
        candidates = ["local-model", "deepseek/deepseek-chat"]
        result = engine.filter_models(candidates)
        assert result == ["deepseek/deepseek-chat"]


class TestLoadFromConfig:
    """config 加载测试"""

    def test_load_empty_config(self):
        engine = PolicyEngine()
        engine.load_from_config({})
        assert engine._constraints.exclude_providers == set()
        assert engine._constraints.exclude_models == set()

    def test_load_with_rules(self):
        config = {
            "policy_rules": {
                "exclude_providers": ["openai", "anthropic"],
                "exclude_models": ["deepseek/deepseek-reasoner"],
                "require_tool_support": True,
            }
        }
        engine = PolicyEngine()
        engine.load_from_config(config)
        assert engine._constraints.exclude_providers == {"openai", "anthropic"}
        assert engine._constraints.exclude_models == {"deepseek/deepseek-reasoner"}
        assert engine._constraints.require_tool_support is True

    def test_load_partial_rules(self):
        config = {
            "policy_rules": {
                "exclude_providers": ["openai"],
            }
        }
        engine = PolicyEngine()
        engine.load_from_config(config)
        assert engine._constraints.exclude_providers == {"openai"}
        assert engine._constraints.exclude_models == set()
        assert engine._constraints.require_tool_support is False


class TestSingleton:
    """全局单例测试"""

    def test_init_and_get(self):
        config = {
            "policy_rules": {
                "exclude_providers": ["test-provider"],
            }
        }
        engine = init_policy_engine(config)
        assert get_policy_engine() is engine
        assert "test-provider" in engine._constraints.exclude_providers

    def test_get_without_init(self):
        """未初始化时 get 返回空约束实例"""
        import app.kernel.router.policy_engine as mod
        old = mod._engine
        mod._engine = None
        try:
            engine = get_policy_engine()
            assert engine is not None
            assert engine._constraints.exclude_providers == set()
        finally:
            mod._engine = old
