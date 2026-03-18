"""评测子系统 — 完全后台化的模型评测与规则生成

核心功能：
1. 持续评测：在系统空闲时自动评测已接入的 LLM 模型
2. 能力矩阵：维护 13 维能力评分 + 3 维规格数据
3. 规则生成：基于评测数据自动生成路由规则
4. 动态优化：SmartRouter 热加载规则，无需重启
"""

from app.evaluation.models import (
    EvaluationStatus,
    TriggerType,
    EvaluationTask,
    EvaluationResult,
)

__all__ = [
    "EvaluationStatus",
    "TriggerType",
    "EvaluationTask",
    "EvaluationResult",
]
