"""API 通道：通过 litellm 调用 OpenAI 兼容 API

支持国内主流 Provider（DeepSeek、Qwen、Kimi、智谱、百川、MiniMax）
和 OpenAI 兼容接口。
"""

import json
import logging
import time
from collections.abc import AsyncGenerator

import litellm  # 模块级预加载，消除首次调用时 1-3s 的懒导入延迟
from openai import AsyncOpenAI

from app.domain.models import ChatMessage, StreamChunk, ToolCall

logger = logging.getLogger("evoiceclaw.kernel.api_provider")

# HTTP 连接池缓存：按 (api_key, base_url) 复用 AsyncOpenAI 客户端
# 避免每次请求重建 TCP + TLS 连接（节省 200-500ms）
# 注意：API Key 变更后需重启后端使缓存失效
_client_cache: dict[tuple[str, str], AsyncOpenAI] = {}


def _get_cached_client(api_key: str, base_url: str | None) -> AsyncOpenAI:
    """获取或创建缓存的 AsyncOpenAI 客户端"""
    cache_key = (api_key, base_url or "")
    if cache_key not in _client_cache:
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        _client_cache[cache_key] = AsyncOpenAI(**kwargs)
        logger.debug("[API] 新建连接池客户端: base_url=%s", base_url)
    return _client_cache[cache_key]

# Provider → litellm 前缀映射
_PROVIDER_PREFIX: dict[str, str] = {
    "openai": "openai",
    "deepseek": "deepseek",
    "qwen": "openai",
    "kimi": "openai",
    "zhipu": "openai",
    "minimax": "openai",
    "baichuan": "openai",
    "ollama": "ollama",
}

# Provider → 默认 Base URL
_PROVIDER_DEFAULT_BASE_URL: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "minimax": "https://api.minimaxi.com/v1",
    "baichuan": "https://api.baichuan-ai.com/v1",
    "ollama": "http://localhost:11434",
}

# 不支持 function calling 的模型
_NO_TOOLS_MODELS = {"deepseek-reasoner"}


class APIProvider:
    """litellm 流式 API 适配器"""

    async def stream(
        self,
        messages: list[ChatMessage],
        model_id: str,
        config: dict,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式调用 API 模型

        Args:
            messages: 对话消息列表
            model_id: 模型 ID，格式 "provider/model" 或纯模型名
            config: 全局配置
            tools: OpenAI function calling tools 列表
            max_tokens: 最大输出 token 数
        """
        # 解析 provider 和 model
        if "/" in model_id:
            provider_id, model_name = model_id.split("/", 1)
        else:
            provider_id = config.get("llm", {}).get("provider", "deepseek")
            model_name = model_id

        # 读取 provider 配置
        providers = config.get("providers", {})
        provider_config = providers.get(provider_id, {})
        api_key = provider_config.get("api_key", "")
        base_url = (
            provider_config.get("base_url")
            or _PROVIDER_DEFAULT_BASE_URL.get(provider_id)
        )
        temperature = config.get("llm", {}).get("temperature", 0.7)

        # 检查模型是否要求固定温度
        from app.kernel.router.model_matrix import KNOWN_MODELS
        profile = KNOWN_MODELS.get(model_id)
        if profile and profile.fixed_temperature is not None:
            logger.info("[API] 模型 %s 要求固定温度 %.1f", model_id, profile.fixed_temperature)
            temperature = profile.fixed_temperature

        # 构建 litellm model string
        prefix = _PROVIDER_PREFIX.get(provider_id, "openai")
        litellm_model = f"{prefix}/{model_name}"

        # 转换消息格式
        msgs = self._convert_messages(messages)

        # 判断是否启用 tools
        actual_tools = None
        if tools and model_name not in _NO_TOOLS_MODELS:
            actual_tools = tools

        logger.info(
            "[API] 流式调用: provider=%s model=%s tools=%s",
            provider_id, litellm_model,
            len(actual_tools) if actual_tools else 0,
        )

        try:
            _start_time = time.monotonic()

            # 推理模型给 5 分钟，普通模型 2 分钟
            is_reasoning = model_name in _NO_TOOLS_MODELS
            api_timeout = 300 if is_reasoning else 120

            kwargs = {
                "model": litellm_model,
                "messages": msgs,
                "api_key": api_key if api_key else None,
                "base_url": base_url,
                "stream": True,
                "stream_options": {"include_usage": True},
                "temperature": temperature,
                "timeout": api_timeout,
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            if actual_tools:
                kwargs["tools"] = actual_tools
                kwargs["tool_choice"] = "auto"

            # OpenAI 兼容 provider 注入缓存 client，复用底层 HTTP 连接池
            # Ollama 使用独立协议，不走此路径
            if prefix != "ollama" and api_key:
                kwargs["client"] = _get_cached_client(api_key, base_url)

            response = await litellm.acompletion(**kwargs)

            # tool_calls 累积器
            tool_calls_accum: dict[int, dict] = {}
            reasoning_parts: list[str] = []
            _output_text_parts: list[str] = []
            _final_usage = None
            _pending_end = False

            async for chunk in response:
                if not chunk.choices:
                    if hasattr(chunk, "usage") and chunk.usage:
                        _final_usage = {
                            "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                            "completion_tokens": getattr(chunk.usage, "completion_tokens", 0),
                        }
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # thinking 模型的推理内容
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_parts.append(rc)
                    yield StreamChunk(
                        type="thinking",
                        content=rc,
                        model=model_name,
                        provider=provider_id,
                    )

                # 文本内容
                if delta.content:
                    _output_text_parts.append(delta.content)
                    yield StreamChunk(
                        type="text",
                        content=delta.content,
                        model=model_name,
                        provider=provider_id,
                    )

                # 流式 tool_calls 累积
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index if hasattr(tc_delta, "index") else 0
                        if idx not in tool_calls_accum:
                            tool_calls_accum[idx] = {
                                "id": "",
                                "name": "",
                                "arguments_str": "",
                            }

                        acc = tool_calls_accum[idx]
                        if hasattr(tc_delta, "id") and tc_delta.id:
                            acc["id"] = tc_delta.id
                        if hasattr(tc_delta, "function") and tc_delta.function:
                            if tc_delta.function.name:
                                acc["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                acc["arguments_str"] += tc_delta.function.arguments

                # 流结束
                if choice.finish_reason:
                    if choice.finish_reason in ("tool_calls", "stop") and tool_calls_accum:
                        for idx in sorted(tool_calls_accum.keys()):
                            acc = tool_calls_accum[idx]
                            try:
                                arguments = json.loads(acc["arguments_str"]) if acc["arguments_str"] else {}
                            except json.JSONDecodeError:
                                arguments = {"raw": acc["arguments_str"]}
                                logger.warning(
                                    "[API] tool_call arguments JSON 解析失败: %s",
                                    acc["arguments_str"][:200],
                                )

                            tc = ToolCall(
                                id=acc["id"] or f"call_{idx}",
                                name=acc["name"],
                                arguments=arguments,
                            )
                            yield StreamChunk(
                                type="tool_call",
                                model=model_name,
                                provider=provider_id,
                                tool_call=tc,
                            )

                    if not tool_calls_accum or choice.finish_reason != "tool_calls":
                        if hasattr(chunk, "usage") and chunk.usage:
                            _final_usage = {
                                "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                                "completion_tokens": getattr(chunk.usage, "completion_tokens", 0),
                            }
                        _pending_end = True
                    elif tool_calls_accum and reasoning_parts:
                        # thinking 模型的 tool_calls 轮次：也需要发 end chunk
                        # 传递 reasoning_content，否则 assistant 消息缺少 reasoning
                        # 导致 Kimi 等模型拒绝（"thinking is enabled but reasoning_content is missing"）
                        _pending_end = True

            # 循环结束后发送 end chunk
            if _pending_end:
                if _final_usage is None:
                    _final_usage = self._estimate_usage(msgs, _output_text_parts, litellm_model)
                yield StreamChunk(
                    type="end",
                    model=model_name,
                    provider=provider_id,
                    usage=_final_usage,
                    reasoning_content="".join(reasoning_parts) if reasoning_parts else "",
                )

                # 记录健康状态：成功
                try:
                    from app.kernel.providers.health import get_health_tracker
                    _latency = (time.monotonic() - _start_time) * 1000
                    get_health_tracker().record_success(provider_id, _latency)
                except Exception as e:
                    logger.debug("[API] 健康状态记录(成功)失败: %s", e)

        except Exception as e:
            logger.error("[API] 流式调用失败: model=%s error=%s", litellm_model, e)

            # 记录健康状态：失败
            try:
                from app.kernel.providers.health import get_health_tracker
                _is_rate_limit = "429" in str(e) or "rate" in str(e).lower()
                get_health_tracker().record_failure(provider_id, is_rate_limit=_is_rate_limit)
            except Exception as e2:
                logger.debug("[API] 健康状态记录(失败)失败: %s", e2)

            # 错误信息脱敏：截断避免泄露 API Key 或内部细节
            err_msg = str(e)
            # 截断过长的错误信息，避免携带 API Key 或完整堆栈
            if len(err_msg) > 200:
                err_msg = err_msg[:200] + "..."
            # 移除可能包含 API Key 的 Authorization 头信息
            import re as _re
            err_msg = _re.sub(r'(api[_-]?key|authorization|bearer)\s*[=:]\s*\S+', '[REDACTED]', err_msg, flags=_re.IGNORECASE)
            yield StreamChunk(type="error", content=err_msg)

    @staticmethod
    def _estimate_usage(
        msgs: list[dict],
        output_parts: list[str],
        litellm_model: str,
    ) -> dict | None:
        """当 provider 不返回 usage 时估算 token 用量"""
        try:
            import litellm as _lt
            prompt_tokens = _lt.token_counter(model=litellm_model, messages=msgs)
        except Exception as e:
            logger.debug("[API] litellm token_counter 不可用，使用估算: %s", e)
            prompt_text = "".join(m.get("content", "") or "" for m in msgs)
            prompt_tokens = max(1, len(prompt_text) // 2)

        output_text = "".join(output_parts)
        try:
            import litellm as _lt
            completion_tokens = _lt.token_counter(
                model=litellm_model,
                messages=[{"role": "assistant", "content": output_text}],
            )
        except Exception as e:
            logger.debug("[API] litellm completion token 计算失败，使用估算: %s", e)
            completion_tokens = max(1, len(output_text) // 2)

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

    @staticmethod
    def _convert_messages(messages: list[ChatMessage]) -> list[dict]:
        """将 ChatMessage 列表转换为 OpenAI API 格式

        包含消息历史修复：确保每个 assistant+tool_calls 后紧跟对应数量的 tool 消息，
        防止因异常中断导致的消息历史损坏引发 API 拒绝（DeepSeek/Kimi 严格校验）。
        """
        msgs = []
        for m in messages:
            msg: dict = {"role": m.role.value if hasattr(m.role, 'value') else m.role, "content": m.content}

            # assistant 消息携带 tool_calls
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in m.tool_calls
                ]

            # thinking 模型的推理内容，多轮 tool call 时必须回传
            if m.reasoning_content is not None:
                msg["reasoning_content"] = m.reasoning_content

            # tool 结果消息
            if m.role == "tool" or (hasattr(m.role, 'value') and m.role.value == "tool"):
                msg["tool_call_id"] = m.tool_call_id
                if m.name:
                    msg["name"] = m.name

            msgs.append(msg)

        # ── 消息历史修复：补全缺失的 tool 响应消息 ──
        msgs = APIProvider._repair_tool_call_pairs(msgs)
        return msgs

    @staticmethod
    def _repair_tool_call_pairs(msgs: list[dict]) -> list[dict]:
        """修复损坏的 tool_calls / tool 响应对

        场景：assistant 消息有 N 个 tool_calls，但后续的 tool 消息不足 N 个
        （因异常中断、用户断连等）。API 严格校验会拒绝这种消息历史。

        修复策略：为缺失的 tool_call 补充一条 tool 响应消息。
        """
        repaired = []
        i = 0
        while i < len(msgs):
            msg = msgs[i]
            repaired.append(msg)

            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                expected_ids = {tc["id"] for tc in msg["tool_calls"]}
                # 收集后续紧跟的 tool 响应消息
                found_ids: set[str] = set()
                j = i + 1
                while j < len(msgs) and msgs[j].get("role") == "tool":
                    tc_id = msgs[j].get("tool_call_id", "")
                    found_ids.add(tc_id)
                    repaired.append(msgs[j])
                    j += 1

                # 补全缺失的 tool 响应
                missing = expected_ids - found_ids
                if missing:
                    logger.warning(
                        "[API] 消息历史修复: 补全 %d 条缺失的 tool 响应 (ids=%s)",
                        len(missing), missing,
                    )
                    for tc_id in missing:
                        # 找到对应 tool_call 的名称
                        tc_name = ""
                        for tc in msg["tool_calls"]:
                            if tc["id"] == tc_id:
                                tc_name = tc.get("function", {}).get("name", "unknown")
                                break
                        repaired.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "name": tc_name,
                            "content": f"[工具 {tc_name} 执行中断，未获得结果]",
                        })

                i = j
                continue

            i += 1
        return repaired
