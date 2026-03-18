"""Function Calling 工具注册中心

管理所有已注册工具（内置硬工具 + 已安装 Skill），
提供 LLM function calling 格式的工具描述列表。
"""

import logging

from app.kernel.tools.protocol import SkillProtocol

logger = logging.getLogger("evoiceclaw.kernel.tool_registry")


class ToolRegistry:
    """Function Calling 工具注册中心"""

    def __init__(self) -> None:
        self._tools: dict[str, SkillProtocol] = {}

    def register(self, skill: SkillProtocol) -> None:
        """注册一个工具"""
        self._tools[skill.name] = skill
        logger.info("[ToolRegistry] 注册: %s", skill.name)

    def unregister(self, name: str) -> bool:
        """注销一个工具"""
        removed = self._tools.pop(name, None)
        if removed:
            logger.info("[ToolRegistry] 注销: %s", name)
        return removed is not None

    def get(self, name: str) -> SkillProtocol | None:
        """按名称获取工具"""
        return self._tools.get(name)

    def get_all(self) -> list[SkillProtocol]:
        """获取所有已注册的工具"""
        return list(self._tools.values())

    def tools_json_for_llm(self) -> list[dict]:
        """生成 OpenAI tools 格式（仅 supports_llm_calling=True 的工具）

        Returns:
            OpenAI function calling 格式的 tools 列表
        """
        tools = []
        for skill in self._tools.values():
            if not skill.supports_llm_calling:
                continue
            tools.append({
                "type": "function",
                "function": {
                    "name": skill.name,
                    "description": skill.description,
                    "parameters": skill.parameters_schema,
                },
            })
        return tools

    def tools_json_for_model(self, model_id: str) -> list[dict]:
        """生成特定模型允许使用的工具列表

        根据配置中的模型工具限制规则，过滤 tools_json_for_llm() 的结果。
        规则不存在时返回全量（兜底）。

        Args:
            model_id: 模型 ID（如 "deepseek/deepseek-chat"）

        Returns:
            OpenAI function calling 格式的 tools 列表（已按规则过滤）
        """
        all_tools = self.tools_json_for_llm()

        # 从配置获取模型的 allowed_tools 限制
        allowed = self._get_allowed_tools(model_id)
        if allowed is None:
            return all_tools  # 无限制规则，全量返回

        if not allowed:
            return []  # 空列表 = 不使用工具

        allowed_set = set(allowed)
        filtered = [t for t in all_tools if t["function"]["name"] in allowed_set]
        logger.info(
            "[ToolRegistry] 模型工具过滤: model=%s 全量=%d 允许=%d 实际=%d",
            model_id, len(all_tools), len(allowed_set), len(filtered),
        )
        return filtered

    def _get_allowed_tools(self, model_id: str) -> list[str] | None:
        """从配置获取模型允许使用的工具列表

        Returns:
            None: 无限制（全量）
            []: 不使用工具
            ["tool1", "tool2"]: 仅允许这些工具
        """
        try:
            from app.core.config import load_config
            config = load_config()
            model_rules = config.get("model_tool_rules", {})
            return model_rules.get(model_id)
        except Exception as e:
            logger.debug("[ToolRegistry] 加载模型工具规则失败: %s", e)
            return None

    def build_capability_declaration(self) -> str:
        """收集所有工具的 capability_brief 生成能力声明

        注入到 system prompt 中，让 LLM 知道可以用哪些工具。
        """
        briefs = []
        for skill in self._tools.values():
            if not skill.supports_llm_calling:
                continue
            brief = skill.capability_brief
            if brief:
                briefs.append(f"- {skill.name}: {brief}")
        if not briefs:
            return ""

        return (
            "\n## 可用工具\n"
            "你可以通过 function calling 使用以下工具：\n"
            + "\n".join(briefs)
        )


# ── 全局单例 ──

_registry: ToolRegistry | None = None


def init_tool_registry() -> ToolRegistry:
    """在 lifespan 中调用，预初始化单例"""
    global _registry
    _registry = ToolRegistry()
    return _registry


def get_tool_registry() -> ToolRegistry:
    """获取单例（lifespan 中已初始化）"""
    if _registry is None:
        raise RuntimeError("ToolRegistry 未初始化，请确认 lifespan 已执行")
    return _registry
