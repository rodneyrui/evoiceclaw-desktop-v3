"""ExecCommandTool — 让 LLM 通过 function calling 执行 Shell 命令

经过三层安全检查（白名单 → Skill 声明 → 沙箱执行），
每次执行都记录审计日志。

权限协商：当 L1 级别阻止代码执行类命令时，返回结构化的"提升请求"
而非直接报错，由 chat_service 协调用户确认后重试。
"""

import json
import logging
import time

from app.kernel.tools.protocol import SkillProtocol
from app.security.audit import log_event, new_trace_id, LEVEL_WARN
from app.security.shell_sandbox import (
    check_whitelist,
    check_skill_declaration,
    execute_sandboxed,
    ShellResult,
    _CODE_EXEC_COMMANDS,
    _FILE_MUTATE_COMMANDS,
    _BLACKLIST,
    current_skill_id,
)
from app.security.permission_broker import ELEVATION_MARKER, elevation_level

logger = logging.getLogger("evoiceclaw.kernel.tools.builtin.shell")


def _is_upgradeable_denial(command: str, level: str) -> tuple[bool, str]:
    """判断一次拒绝是否可通过提升级别解决

    Args:
        command: 命令字符串
        level: 当前安全级别

    Returns:
        (是否可提升, 所需级别)。黑名单命令不可提升。
    """
    import os
    import shlex

    try:
        tokens = shlex.split(command.strip())
    except ValueError:
        tokens = command.strip().split()

    if not tokens:
        return False, ""

    # 跳过环境变量赋值前缀（如 PYTHONPATH=/path python3 test.py）
    while tokens and "=" in tokens[0] and not tokens[0].startswith("="):
        tokens = tokens[1:]

    if not tokens:
        return False, ""

    cmd_name = os.path.basename(tokens[0])

    # 黑名单命令：绝对禁止，不可提升
    if cmd_name in _BLACKLIST:
        return False, ""

    # L1 下代码执行类命令：可提升到 L2
    if level == "L1" and cmd_name in _CODE_EXEC_COMMANDS:
        return True, "L2"

    # L1 下文件变更类命令（rm/mv/cp 等）：可提升到 L2
    if level == "L1" and cmd_name in _FILE_MUTATE_COMMANDS:
        return True, "L2"

    return False, ""


class ExecCommandTool(SkillProtocol):
    """执行系统命令（受沙箱保护）"""

    @property
    def name(self) -> str:
        return "exec_command"

    @property
    def description(self) -> str:
        return (
            "在安全沙箱中执行系统命令。"
            "在工作区内，你可以自由执行代码（python3/node/git 等）和文件操作（mkdir/cp/rm 等）。"
            "在工作区外，仅允许只读命令（ls、cat、grep、curl GET 等）。"
            "如需执行更高权限的操作（L3），系统会请求用户确认。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的命令（如 'python3 test.py'、'mkdir data'、'ls -la'、'curl https://api.example.com/data'）",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数（默认 30，最大 60）",
                },
            },
            "required": ["command"],
        }

    @property
    def capability_brief(self) -> str:
        return "在安全沙箱中执行系统命令（工作区内可执行代码和文件操作，工作区外仅只读）"

    @property
    def required_permissions(self) -> list[str]:
        return ["shell"]

    async def execute(self, arguments: dict) -> str:
        command = arguments.get("command", "").strip()
        if not command:
            return "错误：请提供要执行的命令"

        timeout = min(arguments.get("timeout", 30), 60)
        trace_id = new_trace_id()

        # 宪法第11条：Shell 默认禁用，检查启用状态和安全级别
        from app.security.shell_sandbox import check_shell_enabled, get_shell_config
        shell_enabled, shell_level, shell_reason = check_shell_enabled()

        if not shell_enabled:
            log_event(
                component="shell",
                action="COMMAND_DENY",
                trace_id=trace_id,
                detail=json.dumps({"command": command, "reason": shell_reason}, ensure_ascii=False),
                level=LEVEL_WARN,
            )
            return f"命令被拒绝: {shell_reason}"

        # 检查是否有已批准的权限提升（由 chat_service 通过 ContextVar 设置）
        elevated = elevation_level.get()
        if elevated:
            logger.info("[Shell] 使用已批准的提升级别: %s → %s", shell_level, elevated)
            shell_level = elevated

        # 获取工作区项目目录（工作区内自动放行代码执行和文件操作）
        workspace_dir = None
        try:
            from app.services.workspace_service import get_workspace_service
            ws_svc = get_workspace_service()
            # 优先从当前对话上下文获取工作区信息
            for ws in ws_svc.list_workspaces():
                if ws.project_dir:
                    workspace_dir = ws.project_dir
                    break
        except Exception:
            pass

        # L3 高风险模式：记录 PENDING_APPROVAL（Phase 4 前端审批弹窗实现后对接）
        if shell_level == "L3":
            log_event(
                component="shell",
                action="COMMAND_PENDING_APPROVAL",
                trace_id=trace_id,
                detail=json.dumps({
                    "command": command,
                    "level": "L3",
                    "note": "L3 高风险模式，当前自动放行并记录，待前端审批弹窗实现后对接",
                }, ensure_ascii=False),
                level=LEVEL_WARN,
            )
            # 当前阶段 L3 仍然执行，但记录审计日志标记为 PENDING_APPROVAL

        # Layer 1: 静态白名单检查（传入当前级别和工作区路径）
        # 工作区内的代码执行和文件操作命令会自动放行
        allowed, reason = check_whitelist(command, level=shell_level, workspace_dir=workspace_dir)

        log_event(
            component="shell",
            action="COMMAND_REQUEST",
            trace_id=trace_id,
            detail=json.dumps({"command": command, "timeout": timeout}, ensure_ascii=False),
        )

        if not allowed:
            # 检查是否可通过提升级别解决（权限协商）
            upgradeable, required_level = _is_upgradeable_denial(command, shell_level)
            if upgradeable:
                # 返回结构化的提升请求，由 chat_service 协调用户确认
                import os, shlex
                try:
                    tokens = shlex.split(command.strip())
                except ValueError:
                    tokens = command.strip().split()
                cmd_name = os.path.basename(tokens[0]) if tokens else command

                log_event(
                    component="shell",
                    action="COMMAND_ELEVATION_REQUEST",
                    trace_id=trace_id,
                    detail=json.dumps({
                        "command": command,
                        "cmd_name": cmd_name,
                        "current_level": shell_level,
                        "required_level": required_level,
                    }, ensure_ascii=False),
                    level=LEVEL_WARN,
                )

                return json.dumps({
                    ELEVATION_MARKER: True,
                    "command": command,
                    "cmd_name": cmd_name,
                    "current_level": shell_level,
                    "required_level": required_level,
                    "reason": reason,
                }, ensure_ascii=False)

            # 不可提升的拒绝（黑名单等）
            log_event(
                component="shell",
                action="COMMAND_DENY",
                trace_id=trace_id,
                detail=json.dumps({"command": command, "reason": reason}, ensure_ascii=False),
                level=LEVEL_WARN,
            )
            return f"命令被拒绝: {reason}"

        # Layer 2: Skill 声明匹配
        # 从 ContextVar 读取当前 Skill 上下文（无 Skill 时为 None，跳过此层）
        skill_id = current_skill_id.get()
        skill_actions: list[dict] | None = None
        if skill_id:
            from app.services.skill_service import get_skill_actions
            actions = get_skill_actions(skill_id)
            # actions 为 None 表示 ACTIONS.yaml 不存在，视为空声明（拒绝）
            skill_actions = [a.to_dict() for a in actions] if actions is not None else []

        skill_allowed, skill_reason = check_skill_declaration(
            command, skill_id=skill_id, skill_actions=skill_actions,
        )
        if not skill_allowed:
            log_event(
                component="shell",
                action="COMMAND_DENY",
                trace_id=trace_id,
                detail=json.dumps({"command": command, "reason": skill_reason}, ensure_ascii=False),
                level=LEVEL_WARN,
            )
            return f"命令被拒绝: {skill_reason}"

        # Layer 3: 沙箱执行
        log_event(
            component="shell",
            action="COMMAND_ALLOW",
            trace_id=trace_id,
            detail=json.dumps({"command": command}, ensure_ascii=False),
        )

        start_ms = int(time.monotonic() * 1000)
        result: ShellResult = await execute_sandboxed(command, timeout=timeout)
        elapsed = int(time.monotonic() * 1000) - start_ms

        # 记录执行结果
        log_event(
            component="shell",
            action="COMMAND_EXECUTED",
            trace_id=trace_id,
            detail=json.dumps({
                "command": command,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "stdout_len": len(result.stdout),
                "stderr_len": len(result.stderr),
            }, ensure_ascii=False),
            duration_ms=elapsed,
        )

        # 格式化输出
        parts: list[str] = []

        if result.timed_out:
            parts.append(f"⚠ 命令超时（{timeout}s）")

        if result.stdout:
            parts.append(result.stdout)

        if result.stderr:
            parts.append(f"[stderr] {result.stderr}")

        if result.exit_code != 0 and not result.timed_out:
            parts.append(f"[退出码: {result.exit_code}]")

        if not parts:
            parts.append("（命令执行完成，无输出）")

        return "\n".join(parts)
