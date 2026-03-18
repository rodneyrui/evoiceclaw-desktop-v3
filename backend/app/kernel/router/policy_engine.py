"""策略引擎：硬性约束筛选

在 SmartRouter 的 15 维评分之前，先用硬性规则过滤候选模型：
  - exclude_providers: 排除整个 provider（如 "openai"）
  - exclude_models: 排除特定模型 ID（如 "deepseek/deepseek-reasoner"）
  - require_tool_support: 仅保留支持 function calling 的模型

规则来源：config.yaml 的 policy_rules 字段。
安全网：如果硬性筛选后无候选，回退到原始列表（避免完全不可用）。
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("evoiceclaw.kernel.policy_engine")


@dataclass
class PolicyConstraint:
    """一组硬性约束条件"""
    exclude_providers: set[str] = field(default_factory=set)
    exclude_models: set[str] = field(default_factory=set)
    require_tool_support: bool = False


class PolicyEngine:
    """硬性约束筛选引擎"""

    def __init__(self) -> None:
        self._constraints = PolicyConstraint()

    def load_from_config(self, config: dict) -> None:
        """从 config.yaml 的 policy_rules 字段加载约束"""
        rules = config.get("policy_rules", {})
        if not rules:
            logger.info("[PolicyEngine] 无 policy_rules 配置，使用空约束")
            return

        self._constraints = PolicyConstraint(
            exclude_providers=set(rules.get("exclude_providers", [])),
            exclude_models=set(rules.get("exclude_models", [])),
            require_tool_support=bool(rules.get("require_tool_support", False)),
        )

        logger.info(
            "[PolicyEngine] 加载约束: exclude_providers=%s exclude_models=%s require_tool_support=%s",
            self._constraints.exclude_providers or "(无)",
            self._constraints.exclude_models or "(无)",
            self._constraints.require_tool_support,
        )

    def filter_models(
        self,
        candidates: list[str],
        extra_constraints: PolicyConstraint | None = None,
    ) -> list[str]:
        """硬性筛选候选模型列表

        Args:
            candidates: 原始候选模型 ID 列表
            extra_constraints: 额外约束（如 consult_expert 的临时约束）

        Returns:
            筛选后的模型列表。全部排除时回退原始列表。
        """
        if not candidates:
            return candidates

        constraints = self._constraints
        filtered = []

        # 合并额外约束
        merged_exclude_providers = set(constraints.exclude_providers)
        merged_exclude_models = set(constraints.exclude_models)
        merged_require_tool = constraints.require_tool_support

        if extra_constraints:
            merged_exclude_providers |= extra_constraints.exclude_providers
            merged_exclude_models |= extra_constraints.exclude_models
            merged_require_tool = merged_require_tool or extra_constraints.require_tool_support

        # require_tool_support 的 no-tools 模型列表
        no_tools_models: set[str] = set()
        if merged_require_tool:
            try:
                from app.kernel.providers.api_provider import _NO_TOOLS_MODELS
                no_tools_models = set(_NO_TOOLS_MODELS)
            except ImportError:
                pass

        for model_id in candidates:
            # 提取 provider（model_id 格式: "provider/model-name"）
            provider = model_id.split("/", 1)[0] if "/" in model_id else ""

            if provider and provider in merged_exclude_providers:
                continue
            if model_id in merged_exclude_models:
                continue
            if merged_require_tool and no_tools_models:
                model_name = model_id.split("/", 1)[-1] if "/" in model_id else model_id
                if model_name in no_tools_models:
                    continue

            filtered.append(model_id)

        # 安全网：全部排除时回退原始列表
        if not filtered:
            logger.warning(
                "[PolicyEngine] 硬性筛选后无候选模型，回退原始列表 (%d 个)",
                len(candidates),
            )
            return candidates

        if len(filtered) < len(candidates):
            excluded = set(candidates) - set(filtered)
            logger.info(
                "[PolicyEngine] 筛选: %d → %d，排除=%s",
                len(candidates), len(filtered), sorted(excluded),
            )

        return filtered


# ── 全局单例 ──

_engine: PolicyEngine | None = None


def init_policy_engine(config: dict) -> PolicyEngine:
    """初始化全局 PolicyEngine 单例"""
    global _engine
    _engine = PolicyEngine()
    _engine.load_from_config(config)
    return _engine


def get_policy_engine() -> PolicyEngine:
    """获取全局 PolicyEngine 单例（未初始化时返回空约束实例）"""
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
    return _engine
