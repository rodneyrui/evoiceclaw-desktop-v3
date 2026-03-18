"""LLM 路由器：根据 model_id 前缀选择 API 或 CLI 通道

model_id 格式约定：
  - "provider/model"  → API 通道
  - "cli:agent_key"   → CLI 通道
"""

import logging
from collections.abc import AsyncGenerator

from app.domain.models import ChatMessage, StreamChunk
from app.kernel.providers.api_provider import APIProvider
from app.kernel.providers.cli_provider import CLIAgentProvider

logger = logging.getLogger("evoiceclaw.kernel.llm_router")

_RETRYABLE_KEYWORDS = ("429", "rate", "5xx", "502", "503", "504", "timeout", "connect", "connection")

# 上下文窗口超限关键词（用于 chat_service 自动缩减重试）
CONTEXT_EXCEEDED_KEYWORDS = (
    "context_length", "context window", "maximum context",
    "max_tokens", "token limit", "context_length_exceeded",
    "maximum token", "too many tokens", "reduce the length",
)


class LLMRouter:
    """统一 LLM 路由器"""

    def __init__(self) -> None:
        self.api_provider = APIProvider()
        self.cli_provider = CLIAgentProvider()

    def get_available_models(self, config: dict) -> list[dict]:
        """收集所有可用模型（API + CLI）"""
        models: list[dict] = []

        providers = config.get("providers", {})
        for pid, pcfg in providers.items():
            if not pcfg.get("enabled"):
                continue
            if not pcfg.get("api_key"):
                continue
            for m in pcfg.get("models", []):
                # models 可以是字符串列表 ["deepseek-chat"] 或字典列表 [{"id": "deepseek-chat"}]
                if isinstance(m, str):
                    model_id_raw = m
                    model_name = m.rsplit("/", 1)[-1] if "/" in m else m
                    mode = "analysis"
                elif isinstance(m, dict):
                    model_id_raw = m.get("id", "")
                    if not model_id_raw:
                        continue
                    model_name = m.get("name", model_id_raw)
                    mode = m.get("mode", "analysis")
                else:
                    # SA-11: 跳过非法类型（非 str/dict）
                    continue

                # 如果 model_id 已包含 provider 前缀则直接用，否则加上
                full_id = model_id_raw if "/" in model_id_raw else f"{pid}/{model_id_raw}"
                models.append({
                    "id": full_id,
                    "name": model_name,
                    "provider": pid,
                    "type": "api",
                    "mode": mode,
                })

        cli_agents = config.get("cli_agents", {})
        for agent_key, agent_cfg in cli_agents.items():
            if not agent_cfg.get("enabled"):
                continue
            models.append({
                "id": f"cli:{agent_key}",
                "name": agent_cfg.get("name", agent_key),
                "provider": "cli",
                "type": "cli",
                "mode": "analysis",
            })

        return models

    async def stream(
        self,
        messages: list[ChatMessage],
        model_id: str,
        config: dict,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """根据 model_id 路由到对应通道并流式输出"""
        if model_id.startswith("cli:"):
            agent_key = model_id[4:]
            cli_agents = config.get("cli_agents", {})
            agent_cfg = cli_agents.get(agent_key)

            if not agent_cfg:
                yield StreamChunk(
                    type="error",
                    content=f"CLI 代理未配置: {agent_key}。请检查 config.yaml 的 cli_agents 段。",
                )
                return
            if not agent_cfg.get("enabled"):
                yield StreamChunk(
                    type="error",
                    content=f"CLI 代理未启用: {agent_key}",
                )
                return

            logger.info("[路由] CLI 通道: agent=%s", agent_key)
            async for chunk in self.cli_provider.stream(messages, agent_cfg):
                yield chunk
        else:
            logger.info("[路由] API 通道: model=%s tools=%s", model_id, len(tools) if tools else 0)
            async for chunk in self.api_provider.stream(
                messages, model_id, config, tools=tools, max_tokens=max_tokens,
            ):
                yield chunk

    async def stream_with_fallback(
        self,
        messages: list[ChatMessage],
        candidates: list[str],
        config: dict,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """尝试 candidates 中的模型，首个成功的流式输出；全部失败则 yield 最后的 error"""
        if not candidates:
            yield StreamChunk(type="error", content="无可用候选模型")
            return

        last_error_chunk: StreamChunk | None = None

        for i, model_id in enumerate(candidates):
            logger.info("[Fallback] 尝试候选 %d/%d: %s", i + 1, len(candidates), model_id)

            first_chunk: StreamChunk | None = None
            stream_gen = self.stream(messages, model_id, config, tools=tools)

            try:
                first_chunk = await stream_gen.__anext__()
            except StopAsyncIteration:
                logger.warning("[Fallback] %s 返回空流", model_id)
                continue
            except Exception as e:
                logger.warning("[Fallback] %s 流创建异常: %s", model_id, e)
                last_error_chunk = StreamChunk(type="error", content=str(e))
                continue

            if first_chunk.type == "error" and self._is_retryable(first_chunk.content):
                logger.warning(
                    "[Fallback] %s 返回可重试错误: %s，尝试下一个候选",
                    model_id, first_chunk.content[:100],
                )
                last_error_chunk = first_chunk
                continue

            yield first_chunk

            if first_chunk.type == "error":
                return

            async for chunk in stream_gen:
                yield chunk
            return

        if last_error_chunk:
            logger.error("[Fallback] 所有 %d 个候选均失败", len(candidates))
            yield last_error_chunk
        else:
            yield StreamChunk(type="error", content="所有候选模型均不可用")

    @staticmethod
    def _is_retryable(error_content: str) -> bool:
        lower = error_content.lower()
        return any(kw in lower for kw in _RETRYABLE_KEYWORDS)


# ── 全局单例 ──

_router: LLMRouter | None = None


def init_router() -> LLMRouter:
    """在 lifespan 中调用，初始化全局单例"""
    global _router
    _router = LLMRouter()
    return _router


def get_router() -> LLMRouter:
    """获取全局单例"""
    if _router is None:
        raise RuntimeError("LLMRouter 未初始化，请确认 lifespan 已执行")
    return _router


async def collect_stream_text(
    router: LLMRouter,
    messages: list[ChatMessage],
    model_id: str,
    config: dict,
    *,
    tools: list[dict] | None = None,
) -> str:
    """消费 router.stream() 并收集文本（用于非流式场景）"""
    parts: list[str] = []
    async for chunk in router.stream(messages, model_id, config, tools=tools):
        if chunk.type == "text":
            parts.append(chunk.content)
    return "".join(parts).strip()
