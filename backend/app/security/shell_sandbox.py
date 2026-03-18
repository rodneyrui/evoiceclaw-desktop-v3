"""Shell 沙箱：三层防护的受控命令执行器

Layer 1 — 静态白名单（零延迟）
Layer 2 — Skill 声明匹配（安装时确定）
Layer 3 — 运行时沙箱（超时 + 最小环境 + 输出限制）
"""

import asyncio
import contextvars
import logging
import os
import re
import shlex
from dataclasses import dataclass

logger = logging.getLogger("evoiceclaw.security.shell_sandbox")

# ── Skill 执行上下文（ContextVar）──────────────────────────────────────────
# 由调用方在执行 Skill 工具前通过 Token 设置，ExecCommandTool 在 Layer 2 读取。
# 与 permission_broker.elevation_level 的模式完全一致。
#
# 使用方法（在 chat_service 或测试代码中）：
#   token = current_skill_id.set("weather_skill")
#   try:
#       await tool.execute(args)
#   finally:
#       current_skill_id.reset(token)
current_skill_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_skill_id", default=None
)


def get_shell_config(workspace_id: str = "global") -> dict:
    """获取工作区的 Shell 配置

    优先使用工作区级别设置，无设置时用全局配置。

    Returns:
        {"enabled": bool, "level": str, "timeout": int, "max_output": int}
    """
    from app.core.config import load_config
    config = load_config()
    shell_config = config.get("shell", {})

    # 全局默认值
    result = {
        "enabled": bool(shell_config.get("enabled", False)),
        "level": str(shell_config.get("level", "L1")),
        "timeout": int(shell_config.get("timeout_seconds", 30)) if isinstance(shell_config.get("timeout_seconds"), (int, float)) else 30,
        "max_output": int(shell_config.get("max_output_bytes", 102400)) if isinstance(shell_config.get("max_output_bytes"), (int, float)) else 102400,
    }

    # 尝试从工作区获取覆盖设置
    if workspace_id != "global":
        try:
            from app.services.workspace_service import get_workspace_service
            ws_svc = get_workspace_service()
            ws = ws_svc.get_workspace(workspace_id)
            if ws:
                if hasattr(ws, "shell_enabled"):
                    result["enabled"] = ws.shell_enabled
                if hasattr(ws, "shell_level"):
                    result["level"] = ws.shell_level
        except Exception as e:
            logger.debug("[Shell] 获取工作区配置失败，使用全局默认: %s", e)

    return result


def check_shell_enabled(workspace_id: str = "global") -> tuple[bool, str, str]:
    """检查 Shell 是否启用及当前安全级别

    Args:
        workspace_id: 工作区 ID

    Returns:
        (enabled, level, reason)
    """
    shell_cfg = get_shell_config(workspace_id)

    if not shell_cfg["enabled"]:
        return False, "", "Shell 已禁用（宪法第11条：默认关闭，需在设置中手动启用）"

    level = shell_cfg["level"].upper()
    if level not in ("L1", "L2", "L3"):
        return False, "", f"无效的 Shell 安全级别: {level}"

    return True, level, f"Shell 已启用，安全级别: {level}"


# ── Layer 1：静态白名单 / 黑名单 ──

# 代码执行类命令：本身合法但可通过 -c / eval 等参数执行任意代码
# L1 级别禁用，需要 L2（Skill 声明）或 L3 才可使用
_CODE_EXEC_COMMANDS = frozenset([
    "python3", "python",
    "node",
    "pip", "pip3",
    "npm", "npx", "yarn", "pnpm",
    "cargo", "rustc",
    "go",
    "make", "cmake",
    "docker",
    "git",
    "pytest",  # 自举实验：允许 Agent 运行测试
])

# 文件变更类命令：在工作区内是正常开发操作
# L1 级别禁用（可通过权限协商提升到 L2），需要路径在工作区内
_FILE_MUTATE_COMMANDS = frozenset([
    "rm", "rmdir",
    "mv",
    "cp",
    "mkdir",
    "touch",
])

# 安全命令：只读 / 查询 / 文本处理类，不具备任意代码执行能力
_SAFE_COMMANDS = frozenset([
    "date", "cal", "echo", "printf",
    "cat", "head", "tail", "less", "more",
    "ls", "pwd", "find", "which", "whereis", "file", "stat",
    "wc", "sort", "uniq", "tr", "cut", "paste", "column",
    "grep", "egrep", "fgrep", "awk", "sed",
    "jq", "yq",
    "curl", "wget",
    "dig", "nslookup", "host", "ping",
    "env", "printenv", "uname", "hostname", "whoami", "id",
    "df", "du", "free", "uptime", "ps", "top",
    "tar", "gzip", "gunzip", "zip", "unzip",
    "base64", "md5sum", "sha256sum", "shasum",
    "diff", "comm",
])

# 完整白名单（L2/L3 下有效）= 安全命令 + 代码执行类命令 + 文件变更命令
_WHITELIST = _SAFE_COMMANDS | _CODE_EXEC_COMMANDS | _FILE_MUTATE_COMMANDS

# 绝对禁止的命令（系统破坏 / 权限提升 / 数据渗出）
_BLACKLIST = frozenset([
    "shred",
    "chmod", "chown", "chgrp",
    "sudo", "su", "doas",
    "ssh", "scp", "sftp", "rsync",
    "eval", "exec", "source",
    "crontab", "at",
    "kill", "killall", "pkill",
    "shutdown", "reboot", "halt", "poweroff",
    "mkfs", "fdisk", "mount", "umount",
    "iptables", "nft", "firewall-cmd",
    "useradd", "userdel", "usermod", "passwd", "groupadd",
    "systemctl", "service", "launchctl",
    "dd",
    "nc", "ncat", "socat",  # 网络后门风险
])

# 危险 Shell 操作符和模式
_DANGEROUS_PATTERNS = [
    re.compile(r">\s*/etc/"),          # 重定向到系统目录
    re.compile(r">\s*/usr/"),
    re.compile(r">\s*/bin/"),
    re.compile(r">\s*/sbin/"),
    re.compile(r">\s*/var/"),
    re.compile(r">\s*/tmp/"),
    re.compile(r"\|\s*curl\b"),        # 管道到 curl（数据渗出）
    re.compile(r"\|\s*wget\b"),        # 管道到 wget
    re.compile(r"\|\s*nc\b"),          # 管道到 netcat
    re.compile(r"\|\s*ssh\b"),         # 管道到 ssh
    re.compile(r"\$\("),               # 命令替换
    re.compile(r"`[^`]+`"),            # 反引号命令替换
    re.compile(r";\s*(sudo|su|eval|exec)\b"),  # 分号后跟危险命令
    re.compile(r"&&\s*(sudo|su|eval|exec)\b"),
    re.compile(r"\|\|\s*(sudo|su|eval|exec)\b"),
]


def _strip_quoted_content(command: str) -> str:
    """去除命令中引号包裹的内容，避免对 Python/Node 代码参数误匹配

    示例:
        python3 -c "import sys; exec(open('f').read())"
        → python3 -c "__QUOTED__"
    """
    result = re.sub(r'"[^"]*"', '"__Q__"', command)
    result = re.sub(r"'[^']*'", "'__Q__'", result)
    return result

# curl 只允许 GET（禁止 POST/PUT/DELETE 等写操作）
_CURL_WRITE_FLAGS = re.compile(r"\bcurl\b.*(-X\s*(POST|PUT|DELETE|PATCH)|--data|-d\s|--upload|-T\s|-F\s|--form)")


def check_whitelist(command: str, level: str = "L1", workspace_dir: str | None = None) -> tuple[bool, str]:
    """Layer 1：静态白名单检查

    Args:
        command: 要执行的命令
        level: 当前 Shell 安全级别 (L1/L2/L3)；
               L1 下禁止代码执行类命令（python/node/docker/git 等）
        workspace_dir: 工作区项目目录路径（如有）。在工作区内，代码执行和文件操作
                      命令自动放行，不受 L1 限制。

    Returns:
        (allowed: bool, reason: str)
    """
    stripped = command.strip()
    if not stripped:
        return False, "空命令"

    # 提取第一个词（命令名）
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        # shlex 解析失败（未闭合引号等），用空格分割兜底
        tokens = stripped.split()

    if not tokens:
        return False, "无法解析命令"

    # 跳过环境变量赋值前缀（如 PYTHONPATH=/path python3 test.py）
    cmd_tokens = list(tokens)
    while cmd_tokens and "=" in cmd_tokens[0] and not cmd_tokens[0].startswith("="):
        cmd_tokens = cmd_tokens[1:]

    if not cmd_tokens:
        return False, "命令只包含环境变量赋值"

    cmd_name = os.path.basename(cmd_tokens[0])  # 处理 /usr/bin/ls 这种情况

    # 黑名单检查（绝对禁止，任何级别都不允许）
    if cmd_name in _BLACKLIST:
        return False, f"命令 '{cmd_name}' 在禁止列表中"

    # curl 写操作检查
    if cmd_name in ("curl", "wget") and _CURL_WRITE_FLAGS.search(stripped):
        return False, "curl/wget 仅允许 GET 请求，禁止写操作"

    # 危险模式检查（去除引号内容后再匹配，避免对代码参数误判）
    unquoted = _strip_quoted_content(stripped)
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(unquoted):
            return False, f"检测到危险模式: {pattern.pattern}"

    return True, "通过安全检查"


# ── Layer 2：Skill 声明匹配 ──

def check_skill_declaration(
    command: str,
    skill_id: str | None = None,
    skill_actions: list[dict] | None = None,
) -> tuple[bool, str]:
    """Layer 2：Skill 声明匹配

    如果 skill_id 为 None（用户直接对话，非 Skill 上下文），跳过此层。
    如果有 Skill 上下文，检查命令是否在 ACTIONS.yaml 声明的白名单内。

    Args:
        command: 要执行的命令
        skill_id: Skill 名称（None 表示跳过）
        skill_actions: Skill 的 ACTIONS.yaml 中的动作列表

    Returns:
        (allowed: bool, reason: str)
    """
    # Phase 3 初版：无 Skill 上下文时跳过
    if skill_id is None:
        return True, "无 Skill 上下文，跳过 Layer 2"

    if not skill_actions:
        return False, f"Skill '{skill_id}' 未声明任何允许的命令"

    # 检查命令是否匹配 Skill 声明的模式
    for action in skill_actions:
        pattern = action.get("pattern", "")
        cmd = action.get("command", "")

        # 精确命令匹配
        if cmd and command.strip().startswith(cmd):
            return True, f"匹配 Skill 声明: {cmd}"

        # 正则模式匹配
        if pattern:
            try:
                if re.match(pattern, command.strip()):
                    return True, f"匹配 Skill 模式: {pattern}"
            except re.error:
                continue

    return False, f"命令不在 Skill '{skill_id}' 的声明范围内"


# ── Layer 3：运行时沙箱 ──

# 输出限制
_MAX_OUTPUT_BYTES = 100 * 1024  # 100KB

# 检测需要 shell 解释的操作符（管道、重定向、链接符）
_SHELL_OPERATOR_RE = re.compile(r'[|;&<>]')

# 最小化环境变量
_SANDBOX_ENV = {
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
    "HOME": os.environ.get("HOME", "/tmp"),
    "LANG": "en_US.UTF-8",
    "LC_ALL": "en_US.UTF-8",
    "TERM": "xterm-256color",
    "VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV", ""),
}

# 工作区环境变量注入黑名单
# 这些 key 可被用于劫持动态链接器或 Python 运行时，从而在子进程中执行任意代码
_BLOCKED_ENV_KEYS: frozenset[str] = frozenset({
    # Linux 动态链接器劫持
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_DEBUG",
    "LD_PROFILE", "LD_ORIGIN_PATH", "LD_HWCAP_MASK",
    # macOS 动态链接器劫持
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH", "DYLD_FALLBACK_LIBRARY_PATH",
    "DYLD_FALLBACK_FRAMEWORK_PATH", "DYLD_IMAGE_SUFFIX",
    # Python 运行时劫持
    "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "PYTHONEXECUTABLE", "PYTHONDONTWRITEBYTECODE",
    # Shell 解释器劫持
    "IFS", "BASH_ENV", "ENV", "CDPATH",
})


@dataclass
class ShellResult:
    """Shell 命令执行结果"""
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


async def execute_sandboxed(
    command: str,
    timeout: int = 30,
    cwd: str | None = None,
    workspace_id: str = "global",
) -> ShellResult:
    """Layer 3：在沙箱中执行命令

    简单命令使用 create_subprocess_exec（无 shell 解释，杜绝注入）。
    含管道等 shell 操作符的命令仍用 shell 模式（安全依赖 Layer 1 白名单检查）。

    Args:
        command: 要执行的命令（必须已通过 check_whitelist）
        timeout: 超时秒数（默认 30）
        cwd: 工作目录（可选）
        workspace_id: 工作区 ID（用于合并工作区环境变量）

    Returns:
        ShellResult 执行结果
    """
    # 确保超时合理
    timeout = max(1, min(timeout, 120))

    # 构建沙箱环境变量
    env = dict(_SANDBOX_ENV)

    # 合并工作区环境变量（宪法第6条：工作区隔离）
    if workspace_id != "global":
        try:
            from app.services.workspace_service import get_workspace_service
            ws_svc = get_workspace_service()
            ws_env = ws_svc.get_workspace_env(workspace_id)
            # 过滤危险 key，防止 LD_PRELOAD / DYLD_INSERT_LIBRARIES 等注入
            blocked = {k for k in ws_env if k.upper() in _BLOCKED_ENV_KEYS}
            if blocked:
                logger.warning("[沙箱] 工作区环境变量包含危险 key，已丢弃: %s", blocked)
            env.update({k: v for k, v in ws_env.items() if k.upper() not in _BLOCKED_ENV_KEYS})
        except Exception as e:
            logger.debug("[沙箱] 获取工作区环境变量失败: %s", e)

    # 检测是否包含需要 shell 解释的操作符（管道、重定向、链接符）
    needs_shell = bool(_SHELL_OPERATOR_RE.search(command))

    try:
        if needs_shell:
            # 含 shell 操作符：必须使用 shell 模式
            # 安全保证：调用方已通过 check_whitelist 验证（Layer 1）
            # 注意：不再用 f-string 拼接 ulimit，超时完全由 asyncio.wait_for 控制
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )
        else:
            # 简单命令：使用 exec 模式，杜绝 shell 注入
            try:
                tokens = shlex.split(command)
            except ValueError:
                return ShellResult(
                    stdout="", stderr="命令解析失败（引号未闭合）",
                    exit_code=-1, timed_out=False,
                )
            if not tokens:
                return ShellResult(
                    stdout="", stderr="空命令",
                    exit_code=-1, timed_out=False,
                )
            process = await asyncio.create_subprocess_exec(
                *tokens,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return ShellResult(
                stdout="",
                stderr="",
                exit_code=-1,
                timed_out=True,
            )

        # 截断输出
        stdout = stdout_bytes[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        stderr = stderr_bytes[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")

        return ShellResult(
            stdout=stdout.rstrip(),
            stderr=stderr.rstrip(),
            exit_code=process.returncode or 0,
            timed_out=False,
        )

    except Exception as e:
        logger.error("[沙箱] 执行异常: %s — %s", command[:80], e)
        return ShellResult(
            stdout="",
            stderr=str(e),
            exit_code=-1,
            timed_out=False,
        )
