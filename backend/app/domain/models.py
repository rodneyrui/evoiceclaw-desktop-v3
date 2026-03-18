"""领域模型定义

核心数据结构: ChatMessage, StreamChunk, ToolCall 等。
预留 user_id 字段（R3 多用户隔离）。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class StreamChunkType(str, Enum):
    TEXT = "text"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    URL_DETECTED = "url_detected"
    PERMISSION_REQUEST = "permission_request"  # 运行时权限协商
    VERIFICATION_RESULT = "verification_result"  # 回复验证结果
    BROWSER_OPENED = "browser_opened"  # 后端已打开浏览器（托管浏览）
    ERROR = "error"
    STATUS = "status"
    END = "end"


class SensitivityLevel(str, Enum):
    """隐私敏感度等级"""
    CRITICAL = "critical"    # 极高: 身份证/银行卡/密码 → UUID 占位符，完全隔离
    HIGH = "high"            # 高: 姓名/电话/邮箱/金额 → UUID 占位符，脱敏后通过
    MEDIUM = "medium"        # 中: 日期/地点/一般描述 → 标记后通过
    LOW = "low"              # 低: 公开信息 → 直接通过


@dataclass
class ChatMessage:
    role: MessageRole
    content: str
    id: str = field(default_factory=lambda: str(uuid4()))
    model: str | None = None
    tool_calls: list["ToolCall"] | None = None
    tool_call_id: str | None = None
    name: str | None = None           # tool 角色消息的工具名
    reasoning_content: str | None = None  # thinking 模型的推理内容（多轮 tool call 时回传）
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    user_id: str = "default"  # R3 预留


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class StreamChunk:
    type: StreamChunkType
    content: str = ""
    tool_call: ToolCall | None = None
    model: str | None = None
    provider: str | None = None
    trace_id: str | None = None
    usage: dict | None = None             # {prompt_tokens, completion_tokens}
    reasoning_content: str = ""           # thinking 模型的推理内容


@dataclass
class RedactionEntry:
    """UUID 占位符映射条目（隐私管道使用）"""
    original: str
    type: str                  # PERSON_NAME / PHONE / ID_CARD / ...
    sensitivity: SensitivityLevel
    placeholder: str           # __REDACTED_<uuid>__


@dataclass
class SessionPrivacyContext:
    """会话级隐私上下文（贯穿整个对话生命周期）

    - redaction_map: 累积的占位符映射（用户输入 + 工具返回）
    - doc_type: 当前会话识别到的文档类型（Level 0 语义检测结果）
    - known_sensitive_values: 已识别的敏感值集合（用于跨轮次保护）
    - privacy_notice: 需要 LLM 在回复中自然表达的隐私提醒（一次性，表达后清空）
    """
    redaction_map: dict[str, "RedactionEntry"] = field(default_factory=dict)
    doc_type: str | None = None
    known_sensitive_values: set[str] = field(default_factory=set)
    privacy_notice: str | None = None

    def merge_redaction(self, new_map: dict[str, "RedactionEntry"]) -> None:
        """合并新的隔离结果到会话上下文"""
        self.redaction_map.update(new_map)
        for entry in new_map.values():
            self.known_sensitive_values.add(entry.original)
