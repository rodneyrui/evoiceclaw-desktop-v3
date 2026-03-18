"""ExecutionContext 单元测试"""

import contextvars

from app.kernel.context import ExecutionContext, execution_context, get_or_create_context


class TestExecutionContext:
    """ExecutionContext 数据类测试"""

    def test_defaults(self):
        ctx = ExecutionContext()
        assert ctx.depth == 0
        assert ctx.max_depth == 3
        assert ctx.token_budget == 50_000
        assert ctx.tokens_used == 0
        assert ctx.parent_model_id == ""
        assert len(ctx.trace_id) == 12

    def test_can_recurse_true(self):
        ctx = ExecutionContext(depth=0, max_depth=3, token_budget=10000, tokens_used=0)
        assert ctx.can_recurse is True

    def test_can_recurse_depth_exceeded(self):
        ctx = ExecutionContext(depth=3, max_depth=3)
        assert ctx.can_recurse is False

    def test_can_recurse_budget_exhausted(self):
        ctx = ExecutionContext(depth=0, max_depth=3, token_budget=1000, tokens_used=1000)
        assert ctx.can_recurse is False

    def test_remaining_budget(self):
        ctx = ExecutionContext(token_budget=5000, tokens_used=3000)
        assert ctx.remaining_budget == 2000

    def test_remaining_budget_never_negative(self):
        ctx = ExecutionContext(token_budget=1000, tokens_used=2000)
        assert ctx.remaining_budget == 0

    def test_child_increments_depth(self):
        parent = ExecutionContext(depth=1, max_depth=5)
        child = parent.child()
        assert child.depth == 2
        assert child.max_depth == 5

    def test_child_shares_trace_id(self):
        parent = ExecutionContext()
        child = parent.child()
        assert child.trace_id == parent.trace_id

    def test_child_accumulates_tokens(self):
        parent = ExecutionContext(token_budget=10000, tokens_used=2000)
        child = parent.child(tokens_used_delta=500)
        assert child.tokens_used == 2500
        assert child.token_budget == 10000

    def test_child_inherits_parent_model(self):
        parent = ExecutionContext(parent_model_id="deepseek/deepseek-chat")
        child = parent.child()
        assert child.parent_model_id == "deepseek/deepseek-chat"

    def test_child_overrides_parent_model(self):
        parent = ExecutionContext(parent_model_id="model-a")
        child = parent.child(parent_model_id="model-b")
        assert child.parent_model_id == "model-b"

    def test_frozen(self):
        ctx = ExecutionContext()
        try:
            ctx.depth = 5  # type: ignore
            assert False, "应该抛出 FrozenInstanceError"
        except AttributeError:
            pass


class TestContextVar:
    """ContextVar 隔离测试"""

    def test_default_is_none(self):
        # 在新的 contextvars.Context 中运行，确保隔离
        def _check():
            assert execution_context.get() is None
        ctx = contextvars.copy_context()
        ctx.run(_check)

    def test_set_and_get(self):
        def _check():
            ec = ExecutionContext(depth=2)
            token = execution_context.set(ec)
            assert execution_context.get() is ec
            assert execution_context.get().depth == 2
            execution_context.reset(token)
            assert execution_context.get() is None
        ctx = contextvars.copy_context()
        ctx.run(_check)

    def test_get_or_create_returns_default(self):
        def _check():
            ec = get_or_create_context()
            assert ec.depth == 0
            assert ec.can_recurse is True
        ctx = contextvars.copy_context()
        ctx.run(_check)

    def test_get_or_create_returns_existing(self):
        def _check():
            existing = ExecutionContext(depth=2, parent_model_id="test-model")
            execution_context.set(existing)
            ec = get_or_create_context()
            assert ec is existing
            assert ec.depth == 2
        ctx = contextvars.copy_context()
        ctx.run(_check)
