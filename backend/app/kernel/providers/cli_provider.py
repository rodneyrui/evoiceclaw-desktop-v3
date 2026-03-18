"""CLI 通道：通过 Claude Code CLI 非交互模式调用 LLM

支持 claude -p "prompt" --output-format stream-json 的流式 JSON 输出。
"""

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncGenerator

from app.domain.models import ChatMessage, StreamChunk

logger = logging.getLogger("evoiceclaw.kernel.cli_provider")

# 允许的 CLI 可执行文件名（防止 config.yaml 被篡改后执行任意程序）
_CLI_SAFE_COMMANDS = frozenset(["claude", "claude-code", "claude-dev"])


class CLIAgentProvider:
    """Claude Code CLI 流式包装器"""

    async def stream(
        self,
        messages: list[ChatMessage],
        cli_config: dict,
    ) -> AsyncGenerator[StreamChunk, None]:
        """启动 CLI 子进程并流式读取输出

        Args:
            messages: 对话消息列表
            cli_config: CLI 代理配置
        """
        command = cli_config.get("command", "claude")
        model = cli_config.get("model", "")
        options = cli_config.get("options", {})
        timeout = options.get("timeout", 300)
        output_format = options.get("output_format", "stream-json")
        agent_name = cli_config.get("name", command)

        # 命令名白名单验证（防止 config.yaml 被篡改后执行任意程序）
        cmd_basename = os.path.basename(command)
        if cmd_basename not in _CLI_SAFE_COMMANDS:
            logger.error("[CLI] 不允许的命令: %s", command)
            yield StreamChunk(
                type="error",
                content=f"CLI 命令 '{command}' 不在允许列表中，仅支持: {', '.join(sorted(_CLI_SAFE_COMMANDS))}",
            )
            return

        prompt = self._build_prompt(messages)

        args = [command, "-p", prompt, "--output-format", output_format]
        if model:
            args.extend(["--model", model])

        logger.info("[CLI] 启动: command=%s model=%s timeout=%ds", command, model, timeout)

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("[CLI] 命令未找到: %s", command)
            yield StreamChunk(
                type="error",
                content=f"命令 '{command}' 未找到。请确认已安装 Claude Code CLI。",
            )
            return
        except Exception as e:
            logger.error("[CLI] 启动失败: %s", e)
            yield StreamChunk(type="error", content=f"CLI 启动失败: {e}")
            return

        start_time = time.monotonic()
        try:
            async for line_bytes in process.stdout:
                elapsed = time.monotonic() - start_time
                if elapsed > timeout:
                    process.kill()
                    yield StreamChunk(
                        type="error",
                        content=f"CLI 代理超时 ({timeout}s)",
                    )
                    return

                line = line_bytes.decode("utf-8").strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("[CLI] 非 JSON 行: %s", line[:100])
                    continue

                chunk = self._parse_stream_event(data, agent_name)
                if chunk:
                    yield chunk

        except Exception as e:
            logger.error("[CLI] 读取流失败: %s", e)
            yield StreamChunk(type="error", content=str(e))

        await process.wait()

        if process.returncode and process.returncode != 0:
            stderr_bytes = await process.stderr.read()
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            if stderr_text:
                logger.error("[CLI] 进程退出码 %d: %s", process.returncode, stderr_text[:200])
                yield StreamChunk(type="error", content=stderr_text[:500])

    def _build_prompt(self, messages: list[ChatMessage]) -> str:
        """将消息列表拼合为 CLI prompt"""
        parts = []
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            if role == "system":
                parts.append(f"<system>\n{msg.content}\n</system>")
            elif role == "user":
                parts.append(msg.content)
            elif role == "assistant":
                parts.append(f"<assistant_previous>\n{msg.content}\n</assistant_previous>")
        return "\n\n".join(parts)

    def _parse_stream_event(self, data: dict, agent_name: str) -> StreamChunk | None:
        """解析 claude --output-format stream-json 的单行 JSON"""
        event_type = data.get("type", "")

        if event_type == "content_block_delta":
            delta = data.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                text = delta.get("text", "")
                if text:
                    return StreamChunk(
                        type="text",
                        content=text,
                        provider="cli",
                        model=agent_name,
                    )

            elif delta_type == "thinking_delta":
                text = delta.get("thinking", "")
                if text:
                    return StreamChunk(
                        type="thinking",
                        content=text,
                        provider="cli",
                        model=agent_name,
                    )

        elif event_type == "result":
            if data.get("is_error"):
                return StreamChunk(
                    type="error",
                    content=data.get("error", "CLI 代理执行失败"),
                    provider="cli",
                    model=agent_name,
                )
            usage = {}
            if "cost_usd" in data:
                usage["cost_usd"] = data["cost_usd"]
            if "duration_ms" in data:
                usage["duration_ms"] = data["duration_ms"]
            if "num_turns" in data:
                usage["num_turns"] = data["num_turns"]
            return StreamChunk(
                type="end",
                provider="cli",
                model=agent_name,
                usage=usage if usage else None,
            )

        return None
