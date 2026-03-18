"""动态上下文压缩器（Context Compressor）— 隐私管道第 ③ 级

职责: 将历史对话压缩到模型 context window 的 token 预算内。
策略: 保留最近 N 轮完整对话，更早的压缩为摘要，实体相关优先保留。

输入: 消息历史 + 当前消息 + token 预算
输出: CompressedContext { messages, total_tokens_estimate }
"""

import logging
from dataclasses import dataclass, field

from app.domain.models import ChatMessage, MessageRole

logger = logging.getLogger("evoiceclaw.pipeline.compressor")

# ── 粗略 token 估算 ──

# 中文约 1.5 token/字，英文约 1 token/word
# 这里用一个保守的综合估算
_CHARS_PER_TOKEN_CN = 1.5    # 中文字符
_CHARS_PER_TOKEN_EN = 4.0    # 英文字符


def estimate_tokens(text: str) -> int:
    """粗略估算文本 token 数。"""
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - cn_chars
    return int(cn_chars / _CHARS_PER_TOKEN_CN + other_chars / _CHARS_PER_TOKEN_EN)


@dataclass
class CompressedContext:
    """上下文压缩的输出。"""
    messages: list[ChatMessage] = field(default_factory=list)
    total_tokens_estimate: int = 0
    original_count: int = 0        # 原始消息数
    retained_count: int = 0        # 保留的消息数
    compressed: bool = False       # 是否执行了压缩


class ContextCompressor:
    """隐私管道第 ③ 级：动态上下文压缩。

    策略:
    1. system 消息始终保留
    2. 最近 N 轮对话（user+assistant）完整保留
    3. 工具相关消息（tool/tool_call）跟随对应 assistant 保留
    4. 超出预算时，从最早的消息开始截断
    5. 被截断的消息生成简要摘要（Phase 2 初版使用简单截断）
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        # 默认 token 预算: 留给历史上下文的 token 数
        # 总 context = system + history + current_message + completion
        # 对于 8K 模型: ~3000 token 给历史
        # 对于 128K 模型: ~50000 token 给历史
        self._default_budget = self._config.get("context_budget", 6000)
        self._recent_rounds = self._config.get("recent_rounds", 5)

    @staticmethod
    def _group_into_blocks(msgs: list[ChatMessage]) -> list[list[ChatMessage]]:
        """将消息序列分组为逻辑块，保证 tool_calls + tool 消息不被拆散。

        规则：
        - assistant 消息如果有 tool_calls，则它和后续所有对应的 tool 消息组成一个块
        - 普通 user/assistant 消息各自为一个块
        """
        blocks: list[list[ChatMessage]] = []
        i = 0
        while i < len(msgs):
            msg = msgs[i]
            # assistant 消息带 tool_calls → 收集后续 tool 消息
            if msg.role == MessageRole.ASSISTANT and msg.tool_calls:
                block = [msg]
                j = i + 1
                while j < len(msgs) and msgs[j].role == MessageRole.TOOL:
                    block.append(msgs[j])
                    j += 1
                blocks.append(block)
                i = j
            else:
                blocks.append([msg])
                i += 1
        return blocks

    @staticmethod
    def _compute_dynamic_budget(model_id: str | None) -> int | None:
        """根据模型的 context window 动态计算 token 预算。

        公式: context_window * 0.6 - 9000（9000 为 system + tools + completion 预留）
        下限 3000，上限 100000。
        获取失败时返回 None（降级到默认值）。
        """
        if not model_id:
            return None
        try:
            from app.evaluation.matrix.model_matrix import get_matrix
            profile = get_matrix().get_model_profile(model_id)
            if not profile:
                return None
            context_window = profile.max_context_k * 1000
            budget = int(context_window * 0.6 - 9000)
            return max(3000, min(100000, budget))
        except Exception:
            return None

    def compress(
        self,
        messages: list[ChatMessage],
        current_message: str = "",
        token_budget: int | None = None,
        model_id: str | None = None,
    ) -> CompressedContext:
        """压缩消息历史。

        Args:
            messages: 完整消息历史
            current_message: 当前用户消息（用于估算剩余预算）
            token_budget: token 预算（None 则使用默认值）
            model_id: 模型 ID（用于动态计算预算）

        Returns:
            CompressedContext
        """
        if not messages:
            return CompressedContext()

        # 优先级：显式传入 > 动态计算 > 默认值
        if token_budget:
            budget = token_budget
        else:
            dynamic = self._compute_dynamic_budget(model_id)
            budget = dynamic if dynamic is not None else self._default_budget
        current_tokens = estimate_tokens(current_message)
        available = budget - current_tokens

        # 分离 system 消息和对话消息
        system_msgs: list[ChatMessage] = []
        conv_msgs: list[ChatMessage] = []

        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                system_msgs.append(msg)
            else:
                conv_msgs.append(msg)

        # system 消息始终保留（计算占用）
        system_tokens = sum(estimate_tokens(m.content) for m in system_msgs)
        remaining = available - system_tokens

        if remaining <= 0:
            # system 消息就超出预算，只保留 system
            logger.warning("[压缩器] system 消息已超出 token 预算")
            return CompressedContext(
                messages=system_msgs,
                total_tokens_estimate=system_tokens,
                original_count=len(messages),
                retained_count=len(system_msgs),
                compressed=True,
            )

        # 从后往前按逻辑块选取（保护 tool_calls + tool 消息对不被拆散）
        blocks = self._group_into_blocks(conv_msgs)
        retained: list[ChatMessage] = []
        tokens_used = 0

        for block in reversed(blocks):
            block_tokens = sum(estimate_tokens(m.content) for m in block)
            if tokens_used + block_tokens > remaining:
                break
            retained = block + retained
            tokens_used += block_tokens

        compressed = len(retained) < len(conv_msgs)
        final_messages = system_msgs + retained

        if compressed:
            logger.info(
                "[压缩器] 上下文压缩: %d → %d 条消息, ~%d tokens",
                len(messages), len(final_messages),
                system_tokens + tokens_used,
            )

        return CompressedContext(
            messages=final_messages,
            total_tokens_estimate=system_tokens + tokens_used,
            original_count=len(messages),
            retained_count=len(final_messages),
            compressed=compressed,
        )
