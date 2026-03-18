"""执行上下文：递归保护 + 令牌预算追踪

Multi-Agent 协作中，工具内部可能再次调用 LLM（如 consult_expert、code_review）。
ExecutionContext 通过 ContextVar 在调用链中传递，提供：
  - 递归深度限制（max_depth）
  - 令牌预算追踪（token_budget / tokens_used）
  - 链路追踪（trace_id）
  - 自咨询避免（parent_model_id）

使用模式与 permission_broker.py 的 elevation_level 完全一致：
  token = execution_context.set(ctx)
  try: ...
  finally: execution_context.reset(token)
"""

import contextvars
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExecutionContext:
    """不可变执行上下文，在 LLM 调用链中逐层传递"""

    depth: int = 0
    max_depth: int = 3
    token_budget: int = 50_000
    tokens_used: int = 0
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_model_id: str = ""

    @property
    def can_recurse(self) -> bool:
        """是否允许继续递归调用 LLM"""
        return self.depth < self.max_depth and self.remaining_budget > 0

    @property
    def remaining_budget(self) -> int:
        return max(0, self.token_budget - self.tokens_used)

    def child(self, *, tokens_used_delta: int = 0, parent_model_id: str = "") -> "ExecutionContext":
        """创建 depth+1 的子上下文，共享 trace_id 和预算"""
        return ExecutionContext(
            depth=self.depth + 1,
            max_depth=self.max_depth,
            token_budget=self.token_budget,
            tokens_used=self.tokens_used + tokens_used_delta,
            trace_id=self.trace_id,
            parent_model_id=parent_model_id or self.parent_model_id,
        )


# ── ContextVar：与 elevation_level 完全相同的模式 ──
execution_context: contextvars.ContextVar[ExecutionContext | None] = contextvars.ContextVar(
    "execution_context", default=None,
)


def get_or_create_context() -> ExecutionContext:
    """获取当前上下文，不存在则创建默认根上下文"""
    ctx = execution_context.get()
    if ctx is None:
        ctx = ExecutionContext()
    return ctx
