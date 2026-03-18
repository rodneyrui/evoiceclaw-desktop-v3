"""系统事件定义

用于内部组件间的事件通信。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    # 对话相关
    CHAT_REQUEST_START = "chat.request.start"
    CHAT_REQUEST_END = "chat.request.end"

    # 隐私管道
    PIPELINE_STAGE_START = "pipeline.stage.start"
    PIPELINE_STAGE_END = "pipeline.stage.end"

    # 工具执行
    TOOL_EXECUTE_START = "tool.execute.start"
    TOOL_EXECUTE_END = "tool.execute.end"

    # Shell 沙箱
    SHELL_COMMAND_REQUEST = "shell.command.request"
    SHELL_COMMAND_ALLOW = "shell.command.allow"
    SHELL_COMMAND_DENY = "shell.command.deny"

    # Skill 管理
    SKILL_INSTALL_START = "skill.install.start"
    SKILL_INSTALL_END = "skill.install.end"
    SKILL_UPDATE = "skill.update"

    # 安全
    SECURITY_ALERT = "security.alert"


@dataclass
class SystemEvent:
    type: EventType
    trace_id: str
    component: str
    detail: dict | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
