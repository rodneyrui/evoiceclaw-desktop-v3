"""专家咨询工具 — 让 Agent 在对话中显式调用另一个 LLM 获取专业意见

参照 code_review.py 的「工具内部调用 LLM」模式，但泛化为通用专家咨询：
  - 递归保护：通过 ExecutionContext 限制嵌套深度
  - 自咨询避免：expert_model_id == parent_model_id 时用 fallback
  - 路由选模型：复用 select_model_with_intent 做 15 维路由
  - 审计日志：每次咨询记录到 audit.db
"""

import asyncio
import logging
import time

from app.core.config import load_config
from app.domain.models import ChatMessage, MessageRole
from app.kernel.context import ExecutionContext, execution_context, get_or_create_context
from app.kernel.router.llm_router import collect_stream_text, get_router
from app.kernel.router.smart_router import select_model_with_intent
from app.kernel.tools.protocol import SkillProtocol

logger = logging.getLogger("evoiceclaw.tool.consult_expert")


class ConsultExpertTool(SkillProtocol):
    """专家咨询工具：调用另一个 LLM 获取专业意见"""

    @property
    def name(self) -> str:
        return "consult_expert"

    @property
    def description(self) -> str:
        return (
            "向另一个 AI 专家咨询问题。当你对某个领域不够确定时，"
            "可以调用此工具获取第二意见。支持指定领域提示（如 '法律'、'医学'、'代码'）。"
            "专家模型由智能路由自动选择。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "要咨询的问题（尽量具体、包含必要上下文）",
                },
                "domain_hint": {
                    "type": "string",
                    "description": (
                        "领域提示（可选），如 '法律'、'医学'、'代码审核'、'数学'。"
                        "帮助路由选择更合适的专家模型"
                    ),
                },
                "context": {
                    "type": "string",
                    "description": (
                        "调用背景（可选）：你为什么需要咨询专家？"
                        "提供你的推理过程和已知信息，帮助专家更好地理解问题。"
                    ),
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "专家回复的最大 token 数（可选，默认 2000）",
                },
            },
            "required": ["question"],
        }

    @property
    def capability_brief(self) -> str:
        return "咨询另一个 AI 专家获取第二意见"

    @property
    def required_permissions(self) -> list[str]:
        return ["network"]

    @property
    def tool_timeout(self) -> int:
        return 300  # 外层兜底，实际超时由内部根据模型延迟动态计算

    async def execute(self, arguments: dict) -> str:
        question = arguments.get("question", "").strip()
        domain_hint = arguments.get("domain_hint", "").strip()
        context = arguments.get("context", "").strip()
        max_tokens = arguments.get("max_tokens", 2000)

        if not question:
            return "错误：请提供要咨询的问题"

        # ── 递归保护 ──
        ctx = get_or_create_context()
        if not ctx.can_recurse:
            logger.warning(
                "[专家咨询] 递归深度已达上限 (depth=%d/%d) 或预算耗尽 (remaining=%d)，拒绝咨询",
                ctx.depth, ctx.max_depth, ctx.remaining_budget,
            )
            return (
                f"无法咨询专家：已达递归深度上限（当前 {ctx.depth}/{ctx.max_depth}）"
                f"或令牌预算不足（剩余 {ctx.remaining_budget}）。"
                "请直接根据已有信息回答。"
            )

        config = load_config()
        start_ms = time.monotonic()

        # ── 路由选专家模型 ──
        routing_message = f"{domain_hint} {question}" if domain_hint else question
        expert_model_id, intent, fallback_candidates = await select_model_with_intent(
            routing_message, config,
        )

        if not expert_model_id:
            return "错误：无可用的专家模型"

        # ── 自咨询避免 ──
        if expert_model_id == ctx.parent_model_id and fallback_candidates:
            for candidate in fallback_candidates:
                if candidate != ctx.parent_model_id:
                    logger.info(
                        "[专家咨询] 避免自咨询: %s → %s",
                        expert_model_id, candidate,
                    )
                    expert_model_id = candidate
                    break

        # ── 构建咨询消息 ──
        system_content = "你是一个专业顾问。请针对以下问题给出专业、准确、有依据的回答。使用中文回复。"
        if domain_hint:
            system_content += f"\n你的专业领域：{domain_hint}"
        if context:
            system_content += f"\n\n调用者背景：{context}"

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=system_content),
            ChatMessage(role=MessageRole.USER, content=question),
        ]

        # ── 动态超时：根据模型延迟计算 ──
        dynamic_timeout = 180  # 默认 180s
        try:
            from app.evaluation.matrix.model_matrix import get_matrix
            profile = get_matrix().get_model_profile(expert_model_id)
            if profile:
                # avg_latency_ms * 3，下限 60s，上限 300s
                dynamic_timeout = max(60, min(300, int(profile.avg_latency_ms / 1000 * 3)))
                logger.info(
                    "[专家咨询] 动态超时: model=%s avg_latency=%dms → timeout=%ds",
                    expert_model_id, int(profile.avg_latency_ms), dynamic_timeout,
                )
        except Exception:
            pass

        # ── 设置子上下文 ──
        child_ctx = ctx.child(parent_model_id=expert_model_id)
        child_token = execution_context.set(child_ctx)

        try:
            router = get_router()
            expert_reply = await asyncio.wait_for(
                collect_stream_text(router, messages, expert_model_id, config),
                timeout=dynamic_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[专家咨询] 模型响应超时: model=%s timeout=%ds",
                expert_model_id, dynamic_timeout,
            )
            return f"专家咨询超时（{expert_model_id} 未在 {dynamic_timeout}s 内完成回复）。请稍后重试或换一个问题。"
        except Exception as e:
            logger.error("[专家咨询] 调用失败: model=%s error=%s", expert_model_id, e)
            return f"专家咨询失败：{e}"
        finally:
            execution_context.reset(child_token)

        elapsed_ms = int((time.monotonic() - start_ms) * 1000)

        if not expert_reply:
            return "专家未返回有效回复，请稍后重试。"

        # ── 审计日志 ──
        try:
            from app.security.audit import log_event
            log_event(
                component="consult_expert",
                action="EXPERT_CONSULTED",
                trace_id=ctx.trace_id,
                detail=(
                    f"expert_model={expert_model_id} intent={intent} "
                    f"domain={domain_hint or 'general'} "
                    f"depth={ctx.depth} reply_len={len(expert_reply)}"
                ),
                duration_ms=elapsed_ms,
            )
        except Exception as e:
            logger.warning("[专家咨询] 审计日志记录失败: %s", e)

        logger.info(
            "[专家咨询] 完成: model=%s intent=%s depth=%d elapsed=%dms reply_len=%d",
            expert_model_id, intent, ctx.depth, elapsed_ms, len(expert_reply),
        )

        return (
            f"## 专家意见\n\n"
            f"**咨询模型**: {expert_model_id}\n"
            f"**领域**: {domain_hint or '通用'}\n\n"
            f"{expert_reply}"
        )
