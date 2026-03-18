"""守门员数据模型

ReviewResult: 审查结果（approved/rejected/rewritten + 改写内容 + 安全报告）
SkillMeta: Skill 元数据（name, version, content_hash, reviewed_at, gatekeeper_model）
ActionDeclaration: ACTIONS.yaml 中的单条动作声明
"""

from dataclasses import dataclass, field
from enum import Enum


@dataclass
class ActionDeclaration:
    """Skill 的单条命令声明（ACTIONS.yaml 中的一项）"""
    command: str            # 命令名（如 "curl"）
    pattern: str = ""       # 正则匹配模式（如 r"curl\s+https://api\.weather\.com/.*"）
    description: str = ""   # 用途说明

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "pattern": self.pattern,
            "description": self.description,
        }


@dataclass
class ReviewResult:
    """守门员审查结果"""
    status: str                                  # "approved" / "rejected" / "rewritten"
    safety_report: str = ""                      # 安全报告文本
    rewritten_content: str | None = None         # 改写后的 SKILL.md（仅 rewritten 状态有值）
    actions: list[ActionDeclaration] = field(default_factory=list)  # 提取的动作声明
    model_used: str = ""                         # 审查使用的模型
    duration_ms: int = 0                         # 审查耗时

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "safety_report": self.safety_report,
            "rewritten_content": self.rewritten_content,
            "actions": [a.to_dict() for a in self.actions],
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
        }


class AuthorizationMode(str, Enum):
    """Skill 授权模式（宪法第15条）"""
    ONCE = "once"          # 允许一次（会话结束后失效）
    ALWAYS = "always"      # 始终允许（此工作区）
    DENIED = "denied"      # 拒绝


@dataclass
class SkillMeta:
    """Skill 元数据"""
    name: str
    version: str = "1.0.0"
    content_hash: str = ""
    reviewed_at: str = ""
    gatekeeper_model: str = ""
    status: str = "unknown"                      # "approved" / "rejected" / "rewritten"
    actions: list[ActionDeclaration] = field(default_factory=list)
    authorization_mode: str = "once"   # 默认"允许一次"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "content_hash": self.content_hash,
            "reviewed_at": self.reviewed_at,
            "gatekeeper_model": self.gatekeeper_model,
            "status": self.status,
            "actions": [a.to_dict() for a in self.actions],
            "authorization_mode": self.authorization_mode,
        }
