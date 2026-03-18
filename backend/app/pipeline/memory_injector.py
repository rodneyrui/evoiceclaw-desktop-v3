"""记忆注入器（Memory Injector）— 隐私管道第 ④ 级

职责: 从 LanceDB 中检索相关记忆，注入到对话上下文中。
三层渐进式注入:
  L1 — 核心事实 (Always Inject): 用户基础信息、强偏好
  L2 — 相关记忆 (Query-Driven): 与当前查询语义相关的记忆
  L3 — 蒸馏规则 (Context-Driven): 历史交互蒸馏出的行为规则

预留接口: set_reranker() 用于记忆召回重排序。
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("evoiceclaw.pipeline.memory_injector")

# workspace_id 格式验证（防止注入到 LanceDB .where() 子句）
# 允许：字母、数字、中文、下划线、连字符，最长 64 字符
_WORKSPACE_ID_RE = re.compile(r'^[\w\u4e00-\u9fff\-]{1,64}$')
# SQL 注入危险字符
_SQL_INJECT_CHARS = {"'", ";", "--", "/*", "*/", "\\"}


def _validate_workspace_id(workspace_id: str) -> str:
    """验证 workspace_id 格式，不合法时回退到 'global'

    防御 SQL 注入：workspace_id 会被拼入 LanceDB .where() SQL 子句。
    允许字母数字、中文、下划线、连字符，最长 64 字符。
    """
    if _WORKSPACE_ID_RE.match(workspace_id):
        # 二次防御：确保不含 SQL 注入字符
        if not any(c in workspace_id for c in _SQL_INJECT_CHARS):
            return workspace_id
    logger.warning("[记忆注入] workspace_id 格式非法，回退到 global: %r", workspace_id)
    return "global"


def _safe_where(conditions: list[str]) -> str:
    """构建安全的 WHERE 子句（所有动态值必须已通过 _validate_workspace_id 校验）"""
    return " AND ".join(conditions)


@dataclass
class InjectedMemory:
    """注入的单条记忆。"""
    content: str
    type: str        # fact / preference / summary / episode
    priority: str    # high / medium / low
    layer: str       # L1 / L2 / L3
    score: float = 0.0   # 相关性分数（L2 向量检索时有值）
    source: str = "user" # 记忆来源：user / common_sense


@dataclass
class InjectionResult:
    """记忆注入的输出。"""
    memories: list[InjectedMemory] = field(default_factory=list)
    memory_text: str = ""      # 拼接后的记忆文本（用于注入 system_prompt）
    l1_count: int = 0
    l2_count: int = 0
    l3_count: int = 0


class MemoryInjector:
    """隐私管道第 ④ 级：三层渐进式记忆注入。

    从 LanceDB 检索相关记忆并格式化为可注入的文本。
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._l2_top_k = self._config.get("l2_top_k", 5)
        self._l3_top_k = self._config.get("l3_top_k", 3)
        self._reranker: Callable | None = None

    def set_reranker(self, reranker_fn: Callable) -> None:
        """设置重排序函数（预留接口）。

        Args:
            reranker_fn: 接收 (query, results) 返回重排序后的 results
        """
        self._reranker = reranker_fn
        logger.info("[记忆注入] Reranker 已设置")

    async def inject(
        self,
        query: str,
        user_id: str = "default",
        workspace_id: str = "global",
    ) -> InjectionResult:
        """执行三层记忆注入（L1/L2/L3 并行检索）。

        Args:
            query: 当前用户查询（用于 L2 语义检索）
            user_id: 用户 ID（R3 预留）
            workspace_id: 工作区 ID（宪法第3/6条，记忆按工作区隔离）

        Returns:
            InjectionResult
        """
        result = InjectionResult()
        has_query = bool(query.strip())

        # L1/L2/L3 并行检索（传递 workspace_id）
        tasks: list = [self._fetch_l1_facts(user_id, workspace_id)]
        if has_query:
            tasks.append(self._fetch_l2_relevant(query, user_id, workspace_id))
        tasks.append(self._fetch_l3_rules(query, user_id, workspace_id))

        fetch_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 解析并行结果
        idx = 0

        # L1: 核心事实（Always Inject）
        l1_memories = fetch_results[idx] if not isinstance(fetch_results[idx], Exception) else []
        if isinstance(fetch_results[idx], Exception):
            logger.debug("[记忆注入] L1 并行检索异常: %s", fetch_results[idx])
        idx += 1

        for mem in l1_memories:
            result.memories.append(InjectedMemory(
                content=mem["content"],
                type=mem.get("type", "fact"),
                priority=mem.get("priority", "high"),
                layer="L1",
                source=mem.get("source", "user"),
            ))
        result.l1_count = len(l1_memories)
        # L1 内容集合，用于 L2 去重（同一条记忆不重复注入）
        _l1_contents = {m.content for m in result.memories}

        # L2: 相关记忆（Query-Driven 向量检索）
        l2_memories: list = []
        if has_query:
            l2_memories = fetch_results[idx] if not isinstance(fetch_results[idx], Exception) else []
            if isinstance(fetch_results[idx], Exception):
                logger.debug("[记忆注入] L2 并行检索异常: %s", fetch_results[idx])
            idx += 1

        for mem in l2_memories:
            if mem["content"] in _l1_contents:
                continue  # 已在 L1 中注入，跳过
            result.memories.append(InjectedMemory(
                content=mem["content"],
                type=mem.get("type", "episode"),
                priority=mem.get("priority", "medium"),
                layer="L2",
                score=mem.get("_distance", 0.0),
                source=mem.get("source", "user"),
            ))
        result.l2_count = len([m for m in result.memories if m.layer == "L2"])

        # L3: 蒸馏规则（Context-Driven）
        l3_rules = fetch_results[idx] if not isinstance(fetch_results[idx], Exception) else []
        if isinstance(fetch_results[idx], Exception):
            logger.debug("[记忆注入] L3 并行检索异常: %s", fetch_results[idx])

        for rule in l3_rules:
            result.memories.append(InjectedMemory(
                content=rule["rule"],
                type=rule.get("type", "behavior"),
                priority="medium",
                layer="L3",
                score=rule.get("confidence", 0.5),
            ))
        result.l3_count = len(l3_rules)

        # 格式化注入文本
        if result.memories:
            result.memory_text = self._format_memory_text(result.memories)
            logger.info(
                "[记忆注入] L1=%d L2=%d L3=%d（并行检索）",
                result.l1_count, result.l2_count, result.l3_count,
            )

        return result

    async def _fetch_l1_facts(self, user_id: str, workspace_id: str = "global") -> list[dict]:
        """L1: 获取核心事实（type=fact, priority=high，按工作区过滤）。"""
        workspace_id = _validate_workspace_id(workspace_id)
        try:
            from app.infrastructure.vector_db import get_table

            t0 = time.monotonic()
            table = get_table("memories")

            results = (
                table.search()
                .where(
                    _safe_where([
                        "type = 'fact'",
                        "priority = 'high'",
                        f"workspace_id = '{workspace_id}'",
                    ]),
                    prefilter=True,
                )
                .limit(10)
                .to_list()
            )
            logger.info("[记忆注入] L1 LanceDB 查询 %.0fms", (time.monotonic() - t0) * 1000)
            return results
        except Exception as e:
            logger.info("[记忆注入] L1 检索跳过: %s", e)
            return []

    async def _fetch_l2_relevant(self, query: str, user_id: str, workspace_id: str = "global") -> list[dict]:
        """L2: 向量语义检索相关记忆（按工作区过滤，同时包含全局常识）。"""
        workspace_id = _validate_workspace_id(workspace_id)
        try:
            from app.infrastructure.vector_db import get_table
            from app.infrastructure.embedding import get_embedding_service

            embed_svc = get_embedding_service()

            t0 = time.monotonic()
            query_vector = await embed_svc.embed(query)
            embed_ms = (time.monotonic() - t0) * 1000

            t1 = time.monotonic()
            table = get_table("memories")
            # 检索当前工作区的个人记忆 + 全局通用常识（source = 'common_sense'）
            workspace_filter = (
                f"(workspace_id = '{workspace_id}') OR "
                f"(workspace_id = 'global' AND source = 'common_sense')"
            )
            results = (
                table.search(query_vector)
                .where(workspace_filter, prefilter=True)
                .limit(self._l2_top_k)
                .to_list()
            )
            db_ms = (time.monotonic() - t1) * 1000

            logger.info("[记忆注入] L2 embed=%.0fms LanceDB=%.0fms", embed_ms, db_ms)

            # 预留: 重排序
            if self._reranker and results:
                results = self._reranker(query, results)

            return results
        except Exception as e:
            logger.info("[记忆注入] L2 检索跳过: %s", e)
            return []

    async def _fetch_l3_rules(self, query: str, user_id: str, workspace_id: str = "global") -> list[dict]:
        """L3: 获取蒸馏规则（按工作区过滤）。"""
        workspace_id = _validate_workspace_id(workspace_id)
        try:
            from app.infrastructure.vector_db import get_table
            from app.infrastructure.embedding import get_embedding_service

            embed_svc = get_embedding_service()

            t0 = time.monotonic()
            query_vector = await embed_svc.embed(query)
            embed_ms = (time.monotonic() - t0) * 1000

            t1 = time.monotonic()
            table = get_table("distilled")
            results = (
                table.search(query_vector)
                .where(
                    _safe_where([
                        "confidence > 0.3",
                        f"workspace_id = '{workspace_id}'",
                    ]),
                    prefilter=True,
                )
                .limit(self._l3_top_k)
                .to_list()
            )
            db_ms = (time.monotonic() - t1) * 1000

            logger.info("[记忆注入] L3 embed=%.0fms LanceDB=%.0fms", embed_ms, db_ms)
            return results
        except Exception as e:
            logger.info("[记忆注入] L3 检索跳过: %s", e)
            return []

    @staticmethod
    def _format_memory_text(memories: list[InjectedMemory]) -> str:
        """将记忆格式化为可注入 system_prompt 的文本。"""
        parts: list[str] = []
        parts.append("\n--- 用户记忆 ---")

        # L1 用户核心事实（source != common_sense）
        l1_user = [m for m in memories if m.layer == "L1" and m.source != "common_sense"]
        if l1_user:
            parts.append("【核心事实】")
            for m in l1_user:
                parts.append(f"- {m.content}")

        # L1 + L2 通用常识（source = common_sense，不区分层级）——直接推理，不引用来源
        all_cs = [m for m in memories if m.source == "common_sense"]
        if all_cs:
            parts.append("【通用常识——直接用于推理，无需说明来源】")
            for m in all_cs:
                parts.append(f"- {m.content}")

        # L2 个人相关记忆（source = user）
        l2_personal = [m for m in memories if m.layer == "L2" and m.source != "common_sense"]
        if l2_personal:
            parts.append("【相关记忆】")
            for m in l2_personal:
                parts.append(f"- {m.content}")

        # L3 蒸馏规则
        l3 = [m for m in memories if m.layer == "L3"]
        if l3:
            parts.append("【行为规则】")
            for m in l3:
                parts.append(f"- {m.content}")

        return "\n".join(parts)
