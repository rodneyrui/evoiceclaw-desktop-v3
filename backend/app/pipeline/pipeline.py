"""隐私管道编排器（Pipeline Orchestrator）

串联 5 级隐私管道，trace_id 贯穿全程。

数据流:
  用户消息
    → ① 认知隔离器 (敏感数据检测+UUID替换)
    → ② 实体映射器 (实体提取)  ─┐
    → ③ 上下文压缩器 (历史消息压缩)  │ ②④ 并行执行
    → ④ 记忆注入器 (三层渐进注入) ─┘
    → LLM 处理
    → 隐私恢复器 (UUID→原始数据)
  → 用户

  ⑤ 记忆蒸馏器在会话结束时异步执行。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from uuid import uuid4

from app.domain.models import ChatMessage, RedactionEntry
from app.pipeline.cognitive_isolator import CognitiveIsolator, IsolationResult
from app.pipeline.entity_mapper import EntityMapper, EntityMapResult
from app.pipeline.context_compressor import ContextCompressor, CompressedContext
from app.pipeline.memory_injector import MemoryInjector, InjectionResult
from app.pipeline.memory_distiller import MemoryDistiller
from app.pipeline.privacy_restorer import PrivacyRestorer

logger = logging.getLogger("evoiceclaw.pipeline")


@dataclass
class PipelineResult:
    """管道处理的完整结果。"""
    # 处理后的文本（可直接发送给 LLM）
    clean_message: str = ""
    # 记忆注入文本（附加到 system_prompt）
    memory_text: str = ""
    # 占位符映射（用于回复恢复）
    redaction_map: dict[str, RedactionEntry] = field(default_factory=dict)
    # 压缩后的消息历史
    compressed_messages: list[ChatMessage] = field(default_factory=list)
    # trace_id
    trace_id: str = ""
    # 各阶段耗时
    stage_timings: dict[str, float] = field(default_factory=dict)
    # 统计
    isolation_stats: dict[str, int] = field(default_factory=dict)
    entity_count: int = 0
    memory_count: int = 0


class PrivacyPipeline:
    """隐私管道编排器：串联 5 级处理。"""

    def __init__(self, config: dict | None = None):
        privacy_config = (config or {}).get("privacy", {})
        memory_config = (config or {}).get("memory", {})

        self._enabled = privacy_config.get("enabled", True)

        # 初始化各级组件
        self._isolator = CognitiveIsolator(privacy_config)
        self._entity_mapper = EntityMapper()
        self._compressor = ContextCompressor(memory_config)
        self._memory_injector = MemoryInjector(memory_config)
        self._distiller = MemoryDistiller(memory_config)
        self._restorer = PrivacyRestorer()

        logger.info("[管道] 隐私管道初始化完成 (enabled=%s)", self._enabled)

    async def process_input(
        self,
        message: str,
        messages: list[ChatMessage],
        trace_id: str | None = None,
        user_id: str = "default",
        workspace_id: str = "global",
        model_id: str | None = None,
    ) -> PipelineResult:
        """处理用户输入消息（LLM 调用前）。

        按顺序执行 ①②③④ 级管道。

        Args:
            message: 用户原始消息
            messages: 完整消息历史
            trace_id: 请求追踪 ID（None 则自动生成）
            user_id: 用户 ID（R3 预留）
            workspace_id: 工作区 ID（宪法第3/6条，记忆按工作区隔离）
            model_id: 模型 ID（用于动态计算压缩预算）

        Returns:
            PipelineResult
        """
        trace = trace_id or str(uuid4())[:12]
        result = PipelineResult(trace_id=trace)

        if not self._enabled:
            result.clean_message = message
            result.compressed_messages = messages
            return result

        # ① 认知隔离
        t0 = time.monotonic()
        isolation = self._isolator.isolate(message)
        result.stage_timings["isolator"] = time.monotonic() - t0
        result.clean_message = isolation.clean_text
        result.redaction_map = isolation.redaction_map
        result.isolation_stats = isolation.stats

        # ③ 上下文压缩（同步操作，先执行不阻塞）
        t2 = time.monotonic()
        compressed = self._compressor.compress(messages, current_message=message, model_id=model_id)
        result.stage_timings["compressor"] = time.monotonic() - t2
        result.compressed_messages = compressed.messages

        # ②④ 实体映射 + 记忆注入 并行执行
        t_parallel = time.monotonic()
        entity_task = self._entity_mapper.map_entities(isolation.clean_text)
        memory_task = self._memory_injector.inject(
            query=isolation.clean_text,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        entity_result, injection = await asyncio.gather(entity_task, memory_task)
        parallel_time = time.monotonic() - t_parallel
        result.stage_timings["parallel(entity+memory)"] = parallel_time

        result.entity_count = entity_result.entity_count

        # 从 redaction_map 中额外提取被隔离器替换掉的人名（clean_text 中已不可见）
        redaction_entities = self._entity_mapper.entities_from_redaction_map(
            isolation.redaction_map
        )

        # 异步持久化实体（不阻塞主流程，传递 workspace_id）
        all_entities = entity_result.entities + redaction_entities
        if all_entities:
            try:
                await self._entity_mapper.persist_entities(all_entities, workspace_id)
            except Exception as e:
                logger.debug("[管道] 实体持久化跳过: %s", e)

        result.memory_text = injection.memory_text
        result.memory_count = len(injection.memories)

        total_ms = sum(result.stage_timings.values()) * 1000
        logger.info(
            "[管道] 输入处理完成 [%s]: 隔离=%s 实体=%d 记忆=%d 耗时=%.1fms",
            trace,
            result.isolation_stats,
            result.entity_count,
            result.memory_count,
            total_ms,
        )

        return result

    def restore_output(
        self,
        text: str,
        redaction_map: dict[str, RedactionEntry],
    ) -> str:
        """恢复 LLM 输出中的占位符（LLM 调用后）。

        Args:
            text: LLM 回复文本
            redaction_map: 占位符映射

        Returns:
            恢复后的文本
        """
        if not self._enabled or not redaction_map:
            return text
        return self._restorer.restore(text, redaction_map)

    async def distill_session(
        self,
        messages: list[ChatMessage],
        conversation_id: str = "",
        user_id: str = "default",
        workspace_id: str = "global",
    ) -> None:
        """会话结束时执行记忆蒸馏（⑤ 级）。

        Args:
            messages: 完整会话历史
            conversation_id: 会话 ID
            user_id: 用户 ID
            workspace_id: 工作区 ID（宪法第3/6条，记忆按工作区隔离）
        """
        try:
            await self._distiller.distill(messages, conversation_id, user_id, workspace_id)
        except Exception as e:
            logger.warning("[管道] 记忆蒸馏失败: %s", e)

    @property
    def isolator(self) -> CognitiveIsolator:
        """暴露隔离器实例（用于配置 R2 策略）。"""
        return self._isolator

    @property
    def memory_injector(self) -> MemoryInjector:
        """暴露记忆注入器实例（用于配置重排序器）。"""
        return self._memory_injector

    async def warmup(self) -> None:
        """异步预热：预计算向量等耗时初始化操作。

        应在应用启动后、Embedding 服务初始化完成后调用。
        """
        try:
            await self._isolator.warmup_vectors()
        except Exception as e:
            logger.warning("[管道] 预热失败: %s", e)


# ── 全局单例 ──

_pipeline: PrivacyPipeline | None = None


def init_pipeline(config: dict) -> PrivacyPipeline:
    """初始化全局隐私管道。"""
    global _pipeline
    _pipeline = PrivacyPipeline(config)
    return _pipeline


def get_pipeline() -> PrivacyPipeline:
    """获取全局隐私管道。"""
    if _pipeline is None:
        raise RuntimeError("PrivacyPipeline 未初始化，请先调用 init_pipeline()")
    return _pipeline
