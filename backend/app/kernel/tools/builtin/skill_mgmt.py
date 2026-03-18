"""Skill 管理工具 — skill_mgmt

让 LLM 能自主管理 Skill 的生命周期：安装、卸载、查看列表和详情。
安装时会触发守门员 LLM 审查，因此 tool_timeout 设为 60 秒。
"""

import logging

from app.kernel.tools.protocol import SkillProtocol
from app.services.skill_service import (
    get_skill,
    install_skill,
    list_skills,
    uninstall_skill,
)
from app.core.config import load_config

logger = logging.getLogger("evoiceclaw.tool.skill_mgmt")


class SkillMgmtTool(SkillProtocol):
    """Skill 管理工具

    支持的操作：
    - list: 列出所有已安装的 Skill
    - install: 安装新 Skill（需经守门员审查）
    - uninstall: 卸载已安装的 Skill
    - info: 查看 Skill 详情（SKILL.md 内容 + 元数据）
    """

    @property
    def name(self) -> str:
        return "skill_mgmt"

    @property
    def description(self) -> str:
        return (
            "管理 Skill（可扩展能力包）。支持以下操作（action）：\n"
            "- list: 列出所有已安装的 Skill 及其状态\n"
            "- install: 安装新 Skill，需提供 name 和 skill_md（SKILL.md 内容）。"
            "安装时会经过守门员 LLM 安全审查\n"
            "- uninstall: 卸载指定 Skill，需提供 name\n"
            "- info: 查看 Skill 详情，需提供 name"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "install", "uninstall", "info"],
                    "description": "操作类型",
                },
                "name": {
                    "type": "string",
                    "description": "Skill 名称（install/uninstall/info 时必填）",
                },
                "skill_md": {
                    "type": "string",
                    "description": "SKILL.md 的完整内容（install 时必填）",
                },
            },
            "required": ["action"],
        }

    @property
    def capability_brief(self) -> str:
        return "管理 Skill（安装、卸载、列表、详情）"

    @property
    def tool_timeout(self) -> int:
        # install 操作需要守门员 LLM 审查，耗时较长
        return 60

    async def execute(self, arguments: dict) -> str:
        action = arguments.get("action", "")

        try:
            if action == "list":
                return self._list()
            elif action == "install":
                return await self._install(arguments)
            elif action == "uninstall":
                return self._uninstall(arguments)
            elif action == "info":
                return self._info(arguments)
            else:
                return f"未知操作: {action}。支持: list/install/uninstall/info"
        except Exception as e:
            logger.error("skill_mgmt 执行失败 (action=%s): %s", action, e)
            return f"操作失败: {e}"

    # ------------------------------------------------------------------
    # 各操作的具体实现
    # ------------------------------------------------------------------

    def _list(self) -> str:
        """列出所有已安装的 Skill"""
        skills = list_skills()
        if not skills:
            return "当前没有已安装的 Skill。使用 install 操作来安装新 Skill。"

        lines = [f"已安装 {len(skills)} 个 Skill:\n"]
        for meta in skills:
            actions_count = len(meta.actions)
            lines.append(
                f"  {meta.name} (v{meta.version})\n"
                f"    状态: {meta.status}\n"
                f"    审查模型: {meta.gatekeeper_model or '未知'}\n"
                f"    审查时间: {meta.reviewed_at or '未知'}\n"
                f"    动作数: {actions_count}"
            )
        return "\n".join(lines)

    async def _install(self, arguments: dict) -> str:
        """安装新 Skill（需经守门员审查）"""
        skill_name = arguments.get("name", "").strip()
        skill_md = arguments.get("skill_md", "").strip()

        if not skill_name:
            return "错误：安装 Skill 需要提供 name"
        if not skill_md:
            return "错误：安装 Skill 需要提供 skill_md（SKILL.md 内容）"

        # 加载配置（包含 LLM API Key 等信息，供守门员使用）
        config = load_config()

        # 调用 skill_service 安装（内部会触发守门员审查）
        meta = await install_skill(name=skill_name, skill_md=skill_md, config=config)

        # 格式化安装结果
        actions_summary = ""
        if meta.actions:
            action_names = [a.command for a in meta.actions]
            actions_summary = f"\n    允许的命令: {', '.join(action_names)}"

        return (
            f"Skill 安装成功:\n"
            f"  名称: {meta.name}\n"
            f"  版本: {meta.version}\n"
            f"  审查状态: {meta.status}\n"
            f"  审查模型: {meta.gatekeeper_model or '未知'}\n"
            f"  动作数: {len(meta.actions)}{actions_summary}"
        )

    def _uninstall(self, arguments: dict) -> str:
        """卸载 Skill"""
        skill_name = arguments.get("name", "").strip()
        if not skill_name:
            return "错误：卸载 Skill 需要提供 name"

        ok = uninstall_skill(skill_name)
        if ok:
            return f"Skill 已卸载: {skill_name}"
        else:
            return f"卸载失败：Skill 不存在: {skill_name}"

    def _info(self, arguments: dict) -> str:
        """查看 Skill 详情"""
        skill_name = arguments.get("name", "").strip()
        if not skill_name:
            return "错误：查看 Skill 详情需要提供 name"

        result = get_skill(skill_name)
        if not result:
            return f"Skill 不存在: {skill_name}"

        content, meta = result

        # 格式化动作列表
        actions_text = "  (无)"
        if meta.actions:
            action_lines = []
            for a in meta.actions:
                desc = f" — {a.description}" if a.description else ""
                action_lines.append(f"    - {a.command}{desc}")
            actions_text = "\n".join(action_lines)

        return (
            f"Skill 详情: {meta.name}\n"
            f"  版本: {meta.version}\n"
            f"  状态: {meta.status}\n"
            f"  内容哈希: {meta.content_hash}\n"
            f"  审查模型: {meta.gatekeeper_model or '未知'}\n"
            f"  审查时间: {meta.reviewed_at or '未知'}\n"
            f"  动作列表:\n{actions_text}\n"
            f"\n--- SKILL.md 内容 ---\n{content}"
        )
