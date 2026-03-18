"""consult_expert 工具单元测试"""

import contextvars
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.kernel.context import ExecutionContext, execution_context
from app.kernel.tools.builtin.consult_expert import ConsultExpertTool


@pytest.fixture
def tool():
    return ConsultExpertTool()


class TestConsultExpertMeta:
    """工具元数据测试"""

    def test_name(self, tool):
        assert tool.name == "consult_expert"

    def test_timeout(self, tool):
        assert tool.tool_timeout == 300

    def test_required_permissions(self, tool):
        assert "network" in tool.required_permissions

    def test_parameters_schema(self, tool):
        schema = tool.parameters_schema
        assert "question" in schema["properties"]
        assert "question" in schema["required"]


class TestRecursionGuard:
    """递归保护测试"""

    @pytest.mark.asyncio
    async def test_rejects_at_max_depth(self, tool):
        """depth == max_depth 时应拒绝"""
        ctx = ExecutionContext(depth=3, max_depth=3)
        token = execution_context.set(ctx)
        try:
            result = await tool.execute({"question": "测试问题"})
            assert "递归深度上限" in result
        finally:
            execution_context.reset(token)

    @pytest.mark.asyncio
    async def test_rejects_when_budget_exhausted(self, tool):
        """预算耗尽时应拒绝"""
        ctx = ExecutionContext(depth=0, max_depth=3, token_budget=100, tokens_used=100)
        token = execution_context.set(ctx)
        try:
            result = await tool.execute({"question": "测试问题"})
            assert "令牌预算不足" in result
        finally:
            execution_context.reset(token)

    @pytest.mark.asyncio
    async def test_rejects_empty_question(self, tool):
        result = await tool.execute({"question": ""})
        assert "请提供" in result


class TestSelfConsultAvoidance:
    """自咨询避免测试"""

    @pytest.mark.asyncio
    @patch("app.kernel.tools.builtin.consult_expert.collect_stream_text", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.get_router")
    @patch("app.kernel.tools.builtin.consult_expert.select_model_with_intent", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.load_config")
    async def test_avoids_self_consult(
        self, mock_config, mock_select, mock_router, mock_collect, tool,
    ):
        """parent_model_id 与路由结果相同时，应切换到 fallback"""
        mock_config.return_value = {}
        # 路由返回与 parent 相同的模型，但有 fallback
        mock_select.return_value = ("model-a", "general", ["model-a", "model-b"])
        mock_router.return_value = MagicMock()
        mock_collect.return_value = "专家回复内容"

        ctx = ExecutionContext(depth=0, max_depth=3, parent_model_id="model-a")
        token = execution_context.set(ctx)
        try:
            result = await tool.execute({"question": "测试自咨询避免"})
            # 应该用 model-b 而非 model-a
            call_args = mock_collect.call_args
            actual_model = call_args[0][2]  # 第3个位置参数是 model_id
            assert actual_model == "model-b"
            assert "专家回复内容" in result
        finally:
            execution_context.reset(token)

    @pytest.mark.asyncio
    @patch("app.kernel.tools.builtin.consult_expert.collect_stream_text", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.get_router")
    @patch("app.kernel.tools.builtin.consult_expert.select_model_with_intent", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.load_config")
    async def test_no_fallback_uses_same_model(
        self, mock_config, mock_select, mock_router, mock_collect, tool,
    ):
        """无 fallback 候选时，即使与 parent 相同也只能用它"""
        mock_config.return_value = {}
        mock_select.return_value = ("model-a", "general", ["model-a"])
        mock_router.return_value = MagicMock()
        mock_collect.return_value = "回复"

        ctx = ExecutionContext(depth=0, max_depth=3, parent_model_id="model-a")
        token = execution_context.set(ctx)
        try:
            result = await tool.execute({"question": "测试"})
            call_args = mock_collect.call_args
            actual_model = call_args[0][2]
            assert actual_model == "model-a"
        finally:
            execution_context.reset(token)


class TestNormalExecution:
    """正常执行流程测试"""

    @pytest.mark.asyncio
    @patch("app.kernel.tools.builtin.consult_expert.collect_stream_text", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.get_router")
    @patch("app.kernel.tools.builtin.consult_expert.select_model_with_intent", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.load_config")
    async def test_successful_consult(
        self, mock_config, mock_select, mock_router, mock_collect, tool,
    ):
        mock_config.return_value = {}
        mock_select.return_value = ("expert-model", "reasoning", ["expert-model"])
        mock_router.return_value = MagicMock()
        mock_collect.return_value = "这是专家的详细回复"

        # 确保在干净的上下文中运行
        ctx = ExecutionContext(depth=0, parent_model_id="caller-model")
        token = execution_context.set(ctx)
        try:
            result = await tool.execute({
                "question": "什么是量子纠缠？",
                "domain_hint": "物理",
            })
            assert "专家意见" in result
            assert "expert-model" in result
            assert "物理" in result
            assert "这是专家的详细回复" in result
        finally:
            execution_context.reset(token)

    @pytest.mark.asyncio
    @patch("app.kernel.tools.builtin.consult_expert.collect_stream_text", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.get_router")
    @patch("app.kernel.tools.builtin.consult_expert.select_model_with_intent", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.load_config")
    async def test_empty_reply(
        self, mock_config, mock_select, mock_router, mock_collect, tool,
    ):
        mock_config.return_value = {}
        mock_select.return_value = ("model-x", "general", ["model-x"])
        mock_router.return_value = MagicMock()
        mock_collect.return_value = ""

        ctx = ExecutionContext(depth=0)
        token = execution_context.set(ctx)
        try:
            result = await tool.execute({"question": "测试空回复"})
            assert "未返回有效回复" in result
        finally:
            execution_context.reset(token)

    @pytest.mark.asyncio
    @patch("app.kernel.tools.builtin.consult_expert.collect_stream_text", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.get_router")
    @patch("app.kernel.tools.builtin.consult_expert.select_model_with_intent", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.load_config")
    async def test_llm_exception(
        self, mock_config, mock_select, mock_router, mock_collect, tool,
    ):
        mock_config.return_value = {}
        mock_select.return_value = ("model-x", "general", ["model-x"])
        mock_router.return_value = MagicMock()
        mock_collect.side_effect = RuntimeError("连接超时")

        ctx = ExecutionContext(depth=0)
        token = execution_context.set(ctx)
        try:
            result = await tool.execute({"question": "测试异常"})
            assert "咨询失败" in result
            assert "连接超时" in result
        finally:
            execution_context.reset(token)

    @pytest.mark.asyncio
    @patch("app.kernel.tools.builtin.consult_expert.collect_stream_text", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.get_router")
    @patch("app.kernel.tools.builtin.consult_expert.select_model_with_intent", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.load_config")
    async def test_no_available_model(
        self, mock_config, mock_select, mock_router, mock_collect, tool,
    ):
        mock_config.return_value = {}
        mock_select.return_value = ("", "general", [])
        mock_router.return_value = MagicMock()

        ctx = ExecutionContext(depth=0)
        token = execution_context.set(ctx)
        try:
            result = await tool.execute({"question": "测试无模型"})
            assert "无可用" in result
        finally:
            execution_context.reset(token)


class TestChildContext:
    """子上下文设置测试"""

    @pytest.mark.asyncio
    @patch("app.kernel.tools.builtin.consult_expert.collect_stream_text", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.get_router")
    @patch("app.kernel.tools.builtin.consult_expert.select_model_with_intent", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.load_config")
    async def test_context_restored_after_execution(
        self, mock_config, mock_select, mock_router, mock_collect, tool,
    ):
        """执行后上下文应恢复为原始值"""
        mock_config.return_value = {}
        mock_select.return_value = ("expert", "general", ["expert"])
        mock_router.return_value = MagicMock()
        mock_collect.return_value = "回复"

        original_ctx = ExecutionContext(depth=1, parent_model_id="original")
        token = execution_context.set(original_ctx)
        try:
            await tool.execute({"question": "测试上下文恢复"})
            # 执行后应恢复为原始上下文
            restored = execution_context.get()
            assert restored is original_ctx
            assert restored.depth == 1
            assert restored.parent_model_id == "original"
        finally:
            execution_context.reset(token)


class TestContextParameter:
    """context 参数传递测试"""

    def test_context_field_in_parameters_schema(self, tool):
        """context 字段应出现在 parameters_schema 中"""
        schema = tool.parameters_schema
        assert "context" in schema["properties"]
        assert schema["properties"]["context"]["type"] == "string"

    @pytest.mark.asyncio
    @patch("app.kernel.tools.builtin.consult_expert.collect_stream_text", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.get_router")
    @patch("app.kernel.tools.builtin.consult_expert.select_model_with_intent", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.load_config")
    async def test_context_injected_into_system_prompt(
        self, mock_config, mock_select, mock_router, mock_collect, tool,
    ):
        """context 非空时应注入到专家 system prompt"""
        mock_config.return_value = {}
        mock_select.return_value = ("expert-model", "reasoning", ["expert-model"])
        mock_router.return_value = MagicMock()
        mock_collect.return_value = "专家回复"

        ctx = ExecutionContext(depth=0, parent_model_id="caller")
        token = execution_context.set(ctx)
        try:
            await tool.execute({
                "question": "量子纠缠是什么？",
                "context": "我在写一篇科普文章，需要准确但通俗的解释",
            })
            # 检查 collect_stream_text 收到的 messages 中 system prompt 包含 context
            call_args = mock_collect.call_args
            messages = call_args[0][1]  # 第2个位置参数是 messages
            system_msg = messages[0]
            assert "调用者背景" in system_msg.content
            assert "科普文章" in system_msg.content
        finally:
            execution_context.reset(token)

    @pytest.mark.asyncio
    @patch("app.kernel.tools.builtin.consult_expert.collect_stream_text", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.get_router")
    @patch("app.kernel.tools.builtin.consult_expert.select_model_with_intent", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.load_config")
    async def test_empty_context_not_injected(
        self, mock_config, mock_select, mock_router, mock_collect, tool,
    ):
        """context 为空时不应注入到 system prompt"""
        mock_config.return_value = {}
        mock_select.return_value = ("expert-model", "general", ["expert-model"])
        mock_router.return_value = MagicMock()
        mock_collect.return_value = "回复"

        ctx = ExecutionContext(depth=0, parent_model_id="caller")
        token = execution_context.set(ctx)
        try:
            await tool.execute({
                "question": "测试空 context",
                "context": "",
            })
            call_args = mock_collect.call_args
            messages = call_args[0][1]
            system_msg = messages[0]
            assert "调用者背景" not in system_msg.content
        finally:
            execution_context.reset(token)

    @pytest.mark.asyncio
    @patch("app.kernel.tools.builtin.consult_expert.collect_stream_text", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.get_router")
    @patch("app.kernel.tools.builtin.consult_expert.select_model_with_intent", new_callable=AsyncMock)
    @patch("app.kernel.tools.builtin.consult_expert.load_config")
    async def test_no_context_param_not_injected(
        self, mock_config, mock_select, mock_router, mock_collect, tool,
    ):
        """不传 context 参数时不应注入到 system prompt"""
        mock_config.return_value = {}
        mock_select.return_value = ("expert-model", "general", ["expert-model"])
        mock_router.return_value = MagicMock()
        mock_collect.return_value = "回复"

        ctx = ExecutionContext(depth=0, parent_model_id="caller")
        token = execution_context.set(ctx)
        try:
            await tool.execute({"question": "测试无 context"})
            call_args = mock_collect.call_args
            messages = call_args[0][1]
            system_msg = messages[0]
            assert "调用者背景" not in system_msg.content
        finally:
            execution_context.reset(token)
