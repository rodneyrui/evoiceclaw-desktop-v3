"""记忆蒸馏器（Memory Distiller）— 隐私管道第 ⑤ 级

职责: 从完整会话历史中抽取有价值的信息，蒸馏为长期记忆。
触发时机: 会话结束时或达到一定消息数时。

蒸馏类型:
  - 事实记忆 (fact): 用户提到的具体事实 → memories 表
  - 偏好记忆 (preference): 用户表达的偏好 → memories 表
  - 行为规则 (behavior): 交互模式中发现的规则 → distilled 表

方法: LLM 结构化抽取 → 向量化 → merge_insert 到 LanceDB。
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from app.domain.models import ChatMessage, MessageRole

logger = logging.getLogger("evoiceclaw.pipeline.distiller")

# ── LLM 抽取提示词 ──

_EXTRACTION_PROMPT = """你是一个记忆提取专家。请从以下对话中提取有价值的信息。

提取规则:
1. 事实 (fact): 用户提到的具体个人信息、偏好、经历
2. 偏好 (preference): 用户表达的喜好、习惯、倾向
3. 行为规则 (behavior): 从交互模式中总结出的规则

请以 JSON 数组格式输出，每项包含:
- type: "fact" / "preference" / "behavior"
- content: 提取的内容（简洁的自然语言描述）
- priority: "high" / "medium" / "low"
- confidence: 0.0-1.0 的置信度

如果没有值得提取的信息，返回空数组 []。
仅输出 JSON，不要其他文字。

对话内容:
{conversation}"""


@dataclass
class DistilledItem:
    """蒸馏出的单条记忆。"""
    type: str          # fact / preference / behavior
    content: str
    priority: str = "medium"
    confidence: float = 0.5


@dataclass
class DistillResult:
    """蒸馏结果。"""
    items: list[DistilledItem] = field(default_factory=list)
    facts_count: int = 0
    preferences_count: int = 0
    rules_count: int = 0
    persisted: bool = False


class MemoryDistiller:
    """隐私管道第 ⑤ 级：记忆蒸馏器。

    从会话历史中提取有价值的信息，存入长期记忆。
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        # 最少消息数才触发蒸馏（避免太短的对话）
        self._min_messages = self._config.get("min_messages", 4)
        # 蒸馏用的模型（默认用便宜模型）
        self._model = self._config.get("distill_model", None)

    async def distill(
        self,
        messages: list[ChatMessage],
        conversation_id: str = "",
        user_id: str = "default",
        workspace_id: str = "global",
    ) -> DistillResult:
        """从会话历史中蒸馏记忆。

        Args:
            messages: 完整会话历史
            conversation_id: 会话 ID
            user_id: 用户 ID（R3 预留）
            workspace_id: 工作区 ID（宪法第3/6条，记忆按工作区隔离）

        Returns:
            DistillResult
        """
        # 过滤掉 system 消息，只保留实际对话
        conv_msgs = [m for m in messages if m.role != MessageRole.SYSTEM]

        if len(conv_msgs) < self._min_messages:
            logger.debug("[蒸馏器] 消息数不足 (%d < %d)，跳过", len(conv_msgs), self._min_messages)
            return DistillResult()

        # 构造对话文本
        conv_text = self._format_conversation(conv_msgs)

        # 调用 LLM 抽取
        items = await self._extract_with_llm(conv_text)

        if not items:
            return DistillResult()

        result = DistillResult(items=items)
        for item in items:
            if item.type == "fact":
                result.facts_count += 1
            elif item.type == "preference":
                result.preferences_count += 1
            elif item.type == "behavior":
                result.rules_count += 1

        # 持久化到 LanceDB
        persisted = await self._persist(items, conversation_id, user_id, workspace_id)
        result.persisted = persisted

        logger.info(
            "[蒸馏器] 会话 %s: 提取 %d 项 (事实=%d 偏好=%d 规则=%d) 持久化=%s",
            conversation_id, len(items),
            result.facts_count, result.preferences_count, result.rules_count,
            persisted,
        )

        return result

    async def _extract_with_llm(self, conv_text: str) -> list[DistilledItem]:
        """调用 LLM 提取记忆。"""
        try:
            from app.kernel.router.llm_router import get_router, collect_stream_text
            from app.core.config import load_config

            router = get_router()
            config = load_config()

            # 选择蒸馏模型（默认用配置中的默认模型）
            model_id = self._model or config.get("llm", {}).get("model", "deepseek/deepseek-chat")

            prompt = _EXTRACTION_PROMPT.format(conversation=conv_text[:8000])

            messages = [ChatMessage(role=MessageRole.USER, content=prompt)]
            response = await collect_stream_text(router, messages, model_id, config)

            return self._parse_llm_response(response)

        except Exception as e:
            logger.warning("[蒸馏器] LLM 抽取失败: %s", e)
            return []

    async def _persist(
        self,
        items: list[DistilledItem],
        conversation_id: str,
        user_id: str,
        workspace_id: str = "global",
    ) -> bool:
        """将蒸馏结果持久化到 LanceDB。"""
        try:
            from app.infrastructure.vector_db import get_table
            from app.infrastructure.embedding import get_embedding_service

            embed_svc = get_embedding_service()
            now = datetime.now().isoformat()

            # 分别处理 memories 和 distilled 表
            memory_items = [i for i in items if i.type in ("fact", "preference")]
            rule_items = [i for i in items if i.type == "behavior"]

            # 持久化到 memories 表
            if memory_items:
                texts = [i.content for i in memory_items]
                vectors = await embed_svc.embed_batch(texts)

                rows = []
                for item, vector in zip(memory_items, vectors):
                    rows.append({
                        "id": str(uuid4()),
                        "content": item.content,
                        "type": item.type,
                        "priority": item.priority,
                        "vector": vector,
                        "source_conv_id": conversation_id,
                        "entities": "[]",
                        "created_at": now,
                        "last_recalled": "",
                        "recall_count": 0,
                        "ttl_days": 0,
                        "user_id": user_id,
                        "workspace_id": workspace_id,  # 工作区隔离
                        "source": "user",  # 蒸馏来源标识
                    })

                table = get_table("memories")
                table.add(rows)
                logger.debug("[蒸馏器] 写入 memories: %d 条", len(rows))

            # 持久化到 distilled 表
            if rule_items:
                texts = [i.content for i in rule_items]
                vectors = await embed_svc.embed_batch(texts)

                rows = []
                for item, vector in zip(rule_items, vectors):
                    rows.append({
                        "id": str(uuid4()),
                        "rule": item.content,
                        "type": item.type,
                        "vector": vector,
                        "confidence": item.confidence,
                        "evidence_count": 1,
                        "created_at": now,
                        "updated_at": now,
                        "user_id": user_id,
                        "workspace_id": workspace_id,  # 工作区隔离
                    })

                table = get_table("distilled")
                table.add(rows)
                logger.debug("[蒸馏器] 写入 distilled: %d 条", len(rows))

            return True

        except Exception as e:
            logger.warning("[蒸馏器] 持久化失败: %s", e)
            return False

    @staticmethod
    def _format_conversation(messages: list[ChatMessage]) -> str:
        """格式化对话为文本。"""
        lines: list[str] = []
        for msg in messages:
            role_label = {"user": "用户", "assistant": "助手", "tool": "工具"}.get(
                msg.role.value if isinstance(msg.role, MessageRole) else msg.role,
                msg.role.value if isinstance(msg.role, MessageRole) else msg.role,
            )
            content = msg.content[:500]  # 截断长消息
            lines.append(f"{role_label}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _parse_llm_response(response: str) -> list[DistilledItem]:
        """解析 LLM 的 JSON 响应。"""
        try:
            # 尝试从响应中提取 JSON
            text = response.strip()
            # 处理可能被 markdown 包裹的 JSON
            if text.startswith("```"):
                lines = text.split("\n")
                json_lines = []
                in_json = False
                for line in lines:
                    if line.startswith("```") and not in_json:
                        in_json = True
                        continue
                    elif line.startswith("```") and in_json:
                        break
                    elif in_json:
                        json_lines.append(line)
                text = "\n".join(json_lines)

            data = json.loads(text)
            if not isinstance(data, list):
                return []

            items: list[DistilledItem] = []
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                item_type = entry.get("type", "")
                content = entry.get("content", "")
                if item_type in ("fact", "preference", "behavior") and content:
                    items.append(DistilledItem(
                        type=item_type,
                        content=content,
                        priority=entry.get("priority", "medium"),
                        confidence=float(entry.get("confidence", 0.5)),
                    ))
            return items

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("[蒸馏器] JSON 解析失败: %s", e)
            return []
