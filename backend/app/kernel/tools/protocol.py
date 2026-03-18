"""工具协议抽象基类

所有 function calling 工具（内置硬工具 + Skill 安装的软工具）都实现此协议。
LLM 通过 tool_use 看到 name/description/parameters_schema，自主决定是否调用。
"""

from abc import ABC, abstractmethod


class SkillProtocol(ABC):
    """统一工具接口

    所有 function calling 工具都必须实现此协议。
    包括内置硬工具和经守门员审查的已安装 Skill。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称（LLM tool_use 的 function name，如 "recall_memory"）"""

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述（LLM 看到的 description，决定是否调用）"""

    @property
    @abstractmethod
    def parameters_schema(self) -> dict:
        """参数 JSON Schema（OpenAI function calling 格式）"""

    @property
    def required_permissions(self) -> list[str]:
        """工具所需权限列表（如 ["read_file", "network", "shell"]）

        权限类型:
        - network: 需要访问外部网络
        - read_file: 需要读取文件系统
        - write_file: 需要写入文件系统
        - shell: 需要执行系统命令
        - memory: 需要访问记忆系统

        默认空列表（无特殊权限要求）"""
        return []

    @property
    def security_level(self) -> str:
        """工具安全级别: "L1"(内核硬工具) / "L2"(官方可选) / "L3"(社区)
        默认 L1"""
        return "L1"

    @abstractmethod
    async def execute(self, arguments: dict) -> str:
        """执行工具，返回结果字符串"""

    @property
    def supports_llm_calling(self) -> bool:
        """是否暴露给 LLM（默认 True）"""
        return True

    @property
    def capability_brief(self) -> str | None:
        """能力简述，注入 system prompt 的能力声明（可选）"""
        return None

    @property
    def tool_timeout(self) -> int:
        """工具执行超时秒数（默认 30s，可由子类覆盖）"""
        return 30
