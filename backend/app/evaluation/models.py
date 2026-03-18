"""评测子系统数据模型"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EvaluationStatus(str, Enum):
    """评测任务状态"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TriggerType(str, Enum):
    """触发方式"""
    AUTO_NEW_MODEL = "auto_new_model"
    SCHEDULED = "scheduled"
    IDLE = "idle"
    MANUAL = "manual"


@dataclass
class EvaluationTask:
    """评测任务"""
    task_id: str
    model_id: str
    status: EvaluationStatus
    priority: int = 50
    trigger: TriggerType = TriggerType.IDLE
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_msg: str | None = None
    eval_id: str | None = None  # 关联到 LanceDB model_evaluations


@dataclass
class EvaluationResult:
    """评测结果（写入 LanceDB）"""
    eval_id: str
    model_id: str
    timestamp: datetime
    source: str  # benchmark_real / preset_v2 / evaluated
    dimension_scores: dict[str, float]  # 13 维得分
    avg_latency_ms: int
    avg_input_tokens: int
    avg_output_tokens: int
    cost_input_per_m: float
    cost_output_per_m: float
    context_window: int
    benchmark_version: str = "2.0"
    eval_version: str = "1.0"
    not_measured_dims: list[str] = field(default_factory=list)
