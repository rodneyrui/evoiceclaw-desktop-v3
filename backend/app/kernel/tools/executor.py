"""Tool Call 调度执行器

LLM 返回 ToolCall → 查找 ToolRegistry → 校验参数 Schema → 调用 skill.execute()

包含 R4 基础版 Schema 校验：检查必填参数是否存在、类型是否匹配。
"""

import asyncio
import json
import logging
import time

from app.domain.models import ToolCall
from app.kernel.tools.protocol import SkillProtocol
from app.kernel.tools.registry import ToolRegistry
from app.security.audit import log_event

logger = logging.getLogger("evoiceclaw.kernel.tool_executor")

# 工具调用最大轮次（极端安全兜底，正常不应触发）
# Agent 的工作能力不应被过度限制，用户在场可随时终止任务
MAX_TOOL_ROUNDS = 999

# 单次工具执行超时（秒）— 可被工具实例的 tool_timeout 属性覆盖
DEFAULT_TOOL_TIMEOUT = 30


def _validate_arguments(arguments: dict, schema: dict) -> str | None:
    """R4 基础版 Schema 校验

    检查必填参数是否存在，返回错误消息或 None。
    不做完整 JSON Schema 校验，仅检查 required 字段。

    Args:
        arguments: LLM 提供的参数
        schema: 工具的 parameters_schema

    Returns:
        错误消息字符串，或 None（校验通过）
    """
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    missing = [p for p in required if p not in arguments]
    if missing:
        return f"缺少必填参数: {', '.join(missing)}"

    # 基础类型检查（仅检查已提供的参数）
    type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    for param_name, param_value in arguments.items():
        if param_name not in properties:
            continue
        prop_schema = properties[param_name]
        expected_type_str = prop_schema.get("type")
        if not expected_type_str:
            continue

        # SA-11: bool 是 int 的子类，integer/number 类型需显式拒绝 bool 值
        if expected_type_str in ("integer", "number") and isinstance(param_value, bool):
            return f"参数 '{param_name}' 类型错误: 期望 {expected_type_str}，实际 boolean"

        expected_type = type_map.get(expected_type_str)
        if expected_type and not isinstance(param_value, expected_type):
            return f"参数 '{param_name}' 类型错误: 期望 {expected_type_str}，实际 {type(param_value).__name__}"

        # SA-11: enum 值校验
        allowed_values = prop_schema.get("enum")
        if allowed_values and param_value not in allowed_values:
            return f"参数 '{param_name}' 值不在允许范围内: 期望 {allowed_values}，实际 {param_value!r}"

    return None


class ToolExecutor:
    """Tool Call 调度执行器

    接收 LLM 的 ToolCall 列表，从 ToolRegistry 查找对应工具并执行。
    包含权限检查（预留）和全链路审计日志记录。
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def _check_permissions(
        self, skill: SkillProtocol, caller_permissions: list[str] | None
    ) -> tuple[bool, str]:
        """检查调用方是否拥有工具所需的全部权限

        Args:
            skill: 待执行的工具实例
            caller_permissions: 调用方拥有的权限列表，None 表示跳过检查（当前阶段默认跳过）

        Returns:
            (是否通过, 错误消息)。通过时错误消息为空字符串。
        """
        # 当前阶段：caller_permissions 为 None 时跳过检查，为后续守门员集成预留
        if caller_permissions is None:
            logger.debug(
                "[ToolExecutor] 权限检查跳过: tool=%s (caller_permissions=None，守门员未集成)",
                skill.name,
            )
            return True, ""

        required = skill.required_permissions
        if not required:
            return True, ""

        missing = [p for p in required if p not in caller_permissions]
        if missing:
            return False, f"权限不足，缺少: {', '.join(missing)}"

        return True, ""

    def _summarize_args(self, arguments: dict, max_len: int = 200) -> str:
        """生成参数摘要，用于审计日志（避免记录过长内容）"""
        try:
            text = json.dumps(arguments, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(arguments)
        return text[:max_len] if len(text) > max_len else text

    async def execute(
        self, tool_call: ToolCall, *, caller_permissions: list[str] | None = None,
        workspace_id: str | None = None,
    ) -> tuple[str, str]:
        """执行单个 tool call

        Args:
            tool_call: LLM 生成的工具调用
            caller_permissions: 调用方权限列表，None 表示跳过权限检查
            workspace_id: 当前工作区 ID，注入到工具参数的 _context 字段

        Returns:
            (tool_call_id, result_string)
        """
        skill = self._registry.get(tool_call.name)
        if not skill:
            error_msg = f"未知工具: {tool_call.name}"
            logger.warning("[ToolExecutor] %s", error_msg)
            return tool_call.id, error_msg

        # 权限检查
        perm_ok, perm_err = self._check_permissions(skill, caller_permissions)
        if not perm_ok:
            error_msg = f"工具 {tool_call.name} {perm_err}"
            logger.warning("[ToolExecutor] 权限拒绝: %s", error_msg)
            log_event(
                component="tool_executor",
                action="TOOL_PERMISSION_DENIED",
                detail=json.dumps(
                    {"tool": tool_call.name, "reason": perm_err},
                    ensure_ascii=False,
                ),
                level="WARN",
            )
            return tool_call.id, error_msg

        # R4: 基础 Schema 校验
        validation_error = _validate_arguments(tool_call.arguments, skill.parameters_schema)
        if validation_error:
            error_msg = f"工具 {tool_call.name} 参数校验失败: {validation_error}"
            logger.warning("[ToolExecutor] %s", error_msg)
            return tool_call.id, error_msg

        # 注入工作区上下文（约定字段 _context，让工具感知当前工作区）
        if workspace_id:
            ctx = tool_call.arguments.get("_context")
            if not isinstance(ctx, dict):
                tool_call.arguments["_context"] = {}
            tool_call.arguments["_context"]["workspace_id"] = workspace_id

        logger.info(
            "[ToolExecutor] 执行: %s (call_id=%s) args=%s",
            tool_call.name, tool_call.id,
            str(tool_call.arguments)[:200],
        )

        args_summary = self._summarize_args(tool_call.arguments)
        start_time = time.monotonic()

        try:
            timeout = getattr(skill, "tool_timeout", DEFAULT_TOOL_TIMEOUT)
            result = await asyncio.wait_for(
                skill.execute(tool_call.arguments),
                timeout=timeout,
            )
            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            logger.info(
                "[ToolExecutor] 完成: %s 结果长度=%d 耗时=%dms",
                tool_call.name, len(result), elapsed_ms,
            )

            # 审计日志：工具执行成功
            log_event(
                component="tool_executor",
                action="TOOL_EXECUTED",
                detail=json.dumps(
                    {
                        "tool": tool_call.name,
                        "workspace_id": workspace_id,
                        "args_summary": args_summary,
                        "result_length": len(result),
                        "result_summary": result[:200] if result else "",
                    },
                    ensure_ascii=False,
                ),
                duration_ms=elapsed_ms,
            )

            return tool_call.id, result

        except asyncio.TimeoutError:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"工具 {tool_call.name} 执行超时 ({timeout}s)"
            logger.warning("[ToolExecutor] %s", error_msg)

            # 审计日志：工具执行超时
            log_event(
                component="tool_executor",
                action="TOOL_EXECUTED",
                detail=json.dumps(
                    {
                        "tool": tool_call.name,
                        "args_summary": args_summary,
                        "error": error_msg,
                    },
                    ensure_ascii=False,
                ),
                level="WARN",
                duration_ms=elapsed_ms,
            )

            return tool_call.id, error_msg

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"工具 {tool_call.name} 执行出错: {e}"
            logger.error("[ToolExecutor] %s", error_msg, exc_info=True)

            # 审计日志：工具执行异常
            log_event(
                component="tool_executor",
                action="TOOL_EXECUTED",
                detail=json.dumps(
                    {
                        "tool": tool_call.name,
                        "args_summary": args_summary,
                        "error": str(e),
                    },
                    ensure_ascii=False,
                ),
                level="ERROR",
                duration_ms=elapsed_ms,
            )

            return tool_call.id, error_msg

    async def execute_all(
        self, tool_calls: list[ToolCall], *, workspace_id: str | None = None,
    ) -> list[tuple[str, str]]:
        """并行执行多个 tool calls

        当 tool_calls 包含多个调用时，使用 asyncio.gather 并行执行。
        execute() 内部已有 try/except 包裹，不会抛出异常，因此 gather 安全。

        Args:
            tool_calls: ToolCall 列表
            workspace_id: 当前工作区 ID

        Returns:
            [(tool_call_id, result_string), ...]
        """
        if len(tool_calls) <= 1:
            # 单个工具调用无需并行开销
            results = []
            for tc in tool_calls:
                result = await self.execute(tc, workspace_id=workspace_id)
                results.append(result)
            return results
        # 多个工具调用并行执行
        tasks = [self.execute(tc, workspace_id=workspace_id) for tc in tool_calls]
        return list(await asyncio.gather(*tasks, return_exceptions=False))
