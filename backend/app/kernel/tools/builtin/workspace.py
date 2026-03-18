"""工作区管理工具 — workspace_mgmt

让 LLM 能自主管理项目工作区：注册、激活、查看文件树等。
底层调用 WorkspaceService 完成实际操作。
"""

import json
import logging

from app.kernel.tools.protocol import SkillProtocol
from app.services.workspace_service import get_workspace_service

logger = logging.getLogger("evoiceclaw.tool.workspace")


class WorkspaceMgmtTool(SkillProtocol):
    """工作区管理工具

    支持的操作：
    - register: 注册新工作区（关联一个项目目录）
    - list: 列出所有已注册的工作区
    - activate: 激活指定工作区（切换当前工作区）
    - info: 查看工作区详情
    - tree: 查看工作区文件树
    - unregister: 注销工作区（仅删除元数据，不影响项目文件）
    """

    @property
    def name(self) -> str:
        return "workspace_mgmt"

    @property
    def description(self) -> str:
        return (
            "管理项目工作区。支持以下操作（action）：\n"
            "- register: 注册新工作区，需提供 name（显示名）和 path（项目绝对路径），可选 description\n"
            "- list: 列出所有已注册的工作区\n"
            "- activate: 激活指定工作区，需提供 workspace_id\n"
            "- info: 查看工作区详情，需提供 workspace_id\n"
            "- tree: 查看工作区文件树（排除 node_modules/.git 等），需提供 workspace_id\n"
            "- unregister: 注销工作区，需提供 workspace_id\n"
            "- configure_shell: 设置工作区 Shell 配置，需提供 workspace_id 和 shell_enabled/shell_level\n"
            "- configure_network: 管理工作区域名白名单，需提供 workspace_id 和 domain + add/remove 操作\n"
            "- configure_env: 管理非敏感环境变量，需提供 workspace_id 和 key/value\n"
            "- configure_secret: 管理敏感环境变量，需提供 workspace_id 和 key/value\n"
            "- list_secrets: 列出工作区密钥名称（不暴露值），需提供 workspace_id"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["register", "list", "activate", "info", "tree", "unregister",
                             "configure_shell", "configure_network", "configure_env", "configure_secret", "list_secrets"],
                    "description": "操作类型",
                },
                "name": {
                    "type": "string",
                    "description": "工作区显示名（register 时必填）",
                },
                "path": {
                    "type": "string",
                    "description": "项目根目录绝对路径（register 时必填）",
                },
                "description": {
                    "type": "string",
                    "description": "工作区描述（register 时可选）",
                },
                "workspace_id": {
                    "type": "string",
                    "description": "工作区 ID（activate/info/tree/unregister 时必填）",
                },
                "shell_enabled": {
                    "type": "boolean",
                    "description": "是否启用 Shell（configure_shell 时使用）",
                },
                "shell_level": {
                    "type": "string",
                    "enum": ["L1", "L2", "L3"],
                    "description": "Shell 安全级别（configure_shell 时使用）",
                },
                "domain": {
                    "type": "string",
                    "description": "域名（configure_network 时使用）",
                },
                "operation": {
                    "type": "string",
                    "enum": ["add", "remove"],
                    "description": "添加或移除（configure_network 时使用）",
                },
                "key": {
                    "type": "string",
                    "description": "环境变量/密钥名称",
                },
                "value": {
                    "type": "string",
                    "description": "环境变量/密钥值",
                },
            },
            "required": ["action"],
        }

    @property
    def capability_brief(self) -> str:
        return "管理工作区（注册项目、切换、查看文件树）"

    async def execute(self, arguments: dict) -> str:
        action = arguments.get("action", "")
        svc = get_workspace_service()

        try:
            if action == "register":
                return await self._register(svc, arguments)
            elif action == "list":
                return self._list(svc)
            elif action == "activate":
                return self._activate(svc, arguments)
            elif action == "info":
                return self._info(svc, arguments)
            elif action == "tree":
                return self._tree(svc, arguments)
            elif action == "unregister":
                return self._unregister(svc, arguments)
            elif action == "configure_shell":
                return self._configure_shell(svc, arguments)
            elif action == "configure_network":
                return self._configure_network(svc, arguments)
            elif action == "configure_env":
                return self._configure_env(svc, arguments)
            elif action == "configure_secret":
                return self._configure_secret(svc, arguments)
            elif action == "list_secrets":
                return self._list_secrets(svc, arguments)
            else:
                return f"未知操作: {action}。支持: register/list/activate/info/tree/unregister"
        except Exception as e:
            logger.error("workspace_mgmt 执行失败 (action=%s): %s", action, e)
            return f"操作失败: {e}"

    # ------------------------------------------------------------------
    # 各操作的具体实现
    # ------------------------------------------------------------------

    async def _register(self, svc, arguments: dict) -> str:
        """注册新工作区"""
        ws_name = arguments.get("name", "").strip()
        ws_path = arguments.get("path", "").strip()
        ws_desc = arguments.get("description", "").strip()

        if not ws_name:
            return "错误：注册工作区需要提供 name（显示名）"
        if not ws_path:
            return "错误：注册工作区需要提供 path（项目绝对路径）"

        ws = svc.register_workspace(name=ws_name, path=ws_path, description=ws_desc)
        return (
            f"工作区注册成功:\n"
            f"  ID: {ws.id}\n"
            f"  名称: {ws.name}\n"
            f"  路径: {ws.path}\n"
            f"  描述: {ws.description or '(无)'}\n"
            f"  创建时间: {ws.created_at}"
        )

    def _list(self, svc) -> str:
        """列出所有工作区"""
        workspaces = svc.list_workspaces()
        if not workspaces:
            return "当前没有注册的工作区。使用 register 操作来注册一个项目目录。"

        lines = [f"已注册 {len(workspaces)} 个工作区:\n"]
        for ws in workspaces:
            active_mark = " [激活]" if ws.active else ""
            lines.append(
                f"  {ws.id} — {ws.name}{active_mark}\n"
                f"    路径: {ws.path}\n"
                f"    描述: {ws.description or '(无)'}\n"
                f"    最后访问: {ws.last_accessed}"
            )
        return "\n".join(lines)

    def _activate(self, svc, arguments: dict) -> str:
        """激活工作区"""
        workspace_id = arguments.get("workspace_id", "").strip()
        if not workspace_id:
            return "错误：激活工作区需要提供 workspace_id"

        ws = svc.activate_workspace(workspace_id)
        return f"工作区已激活: {ws.name} ({ws.id})\n路径: {ws.path}"

    def _info(self, svc, arguments: dict) -> str:
        """查看工作区详情"""
        workspace_id = arguments.get("workspace_id", "").strip()
        if not workspace_id:
            return "错误：查看工作区需要提供 workspace_id"

        ws = svc.get_workspace(workspace_id)
        if not ws:
            return f"工作区不存在: {workspace_id}"

        return (
            f"工作区详情:\n"
            f"  ID: {ws.id}\n"
            f"  名称: {ws.name}\n"
            f"  路径: {ws.path}\n"
            f"  描述: {ws.description or '(无)'}\n"
            f"  状态: {'激活' if ws.active else '未激活'}\n"
            f"  创建时间: {ws.created_at}\n"
            f"  最后访问: {ws.last_accessed}"
        )

    def _tree(self, svc, arguments: dict) -> str:
        """查看文件树"""
        workspace_id = arguments.get("workspace_id", "").strip()
        if not workspace_id:
            return "错误：查看文件树需要提供 workspace_id"

        tree = svc.get_file_tree(workspace_id, max_depth=3)
        return f"文件树:\n{tree}"

    def _unregister(self, svc, arguments: dict) -> str:
        """注销工作区"""
        workspace_id = arguments.get("workspace_id", "").strip()
        if not workspace_id:
            return "错误：注销工作区需要提供 workspace_id"

        # 先获取工作区信息用于显示
        ws = svc.get_workspace(workspace_id)
        ws_name = ws.name if ws else workspace_id

        ok = svc.unregister_workspace(workspace_id)
        if ok:
            return f"工作区已注销: {ws_name} ({workspace_id})\n注意：项目文件未被删除。"
        else:
            return f"注销失败：工作区不存在或无法删除: {workspace_id}"

    def _configure_shell(self, svc, arguments: dict) -> str:
        """设置工作区 Shell 配置"""
        workspace_id = arguments.get("workspace_id", "").strip()
        if not workspace_id:
            return "错误：需要提供 workspace_id"

        ws = svc.get_workspace(workspace_id)
        if not ws:
            return f"工作区不存在: {workspace_id}"

        changed = []
        if "shell_enabled" in arguments:
            svc.update_workspace_field(workspace_id, "shell_enabled", bool(arguments["shell_enabled"]))
            changed.append(f"shell_enabled={arguments['shell_enabled']}")
        if "shell_level" in arguments:
            level = arguments["shell_level"]
            if level not in ("L1", "L2", "L3"):
                return f"无效的安全级别: {level}，支持: L1/L2/L3"
            svc.update_workspace_field(workspace_id, "shell_level", level)
            changed.append(f"shell_level={level}")

        if not changed:
            return "未提供任何配置项（shell_enabled 或 shell_level）"
        return f"工作区 {workspace_id} Shell 配置已更新: {', '.join(changed)}"

    def _configure_network(self, svc, arguments: dict) -> str:
        """管理工作区域名白名单"""
        workspace_id = arguments.get("workspace_id", "").strip()
        if not workspace_id:
            return "错误：需要提供 workspace_id"

        domain = arguments.get("domain", "").strip()
        operation = arguments.get("operation", "add").strip()

        if not domain:
            return "错误：需要提供 domain"

        from app.security.network_guard import add_to_whitelist, remove_from_whitelist

        if operation == "add":
            ok = add_to_whitelist(domain, workspace_id)
            if ok:
                return f"域名 {domain} 已添加到工作区 {workspace_id} 白名单"
            return "添加失败"
        elif operation == "remove":
            ok = remove_from_whitelist(domain, workspace_id)
            if ok:
                return f"域名 {domain} 已从工作区 {workspace_id} 白名单移除"
            return "移除失败"
        else:
            return f"未知操作: {operation}，支持: add/remove"

    def _configure_env(self, svc, arguments: dict) -> str:
        """管理非敏感环境变量"""
        workspace_id = arguments.get("workspace_id", "").strip()
        if not workspace_id:
            return "错误：需要提供 workspace_id"

        key = arguments.get("key", "").strip()
        if not key:
            return "错误：需要提供 key"

        ws = svc.get_workspace(workspace_id)
        if not ws:
            return f"工作区不存在: {workspace_id}"

        value = arguments.get("value")
        env_vars = dict(ws.env_vars)

        if value is not None:
            env_vars[key] = value
            svc.update_workspace_field(workspace_id, "env_vars", env_vars)
            return f"环境变量已设置: {key}={value}"
        else:
            if key in env_vars:
                del env_vars[key]
                svc.update_workspace_field(workspace_id, "env_vars", env_vars)
                return f"环境变量已删除: {key}"
            return f"环境变量不存在: {key}"

    def _configure_secret(self, svc, arguments: dict) -> str:
        """管理敏感环境变量"""
        workspace_id = arguments.get("workspace_id", "").strip()
        if not workspace_id:
            return "错误：需要提供 workspace_id"

        key = arguments.get("key", "").strip()
        if not key:
            return "错误：需要提供 key"

        value = arguments.get("value")

        if value is not None:
            ok = svc.save_workspace_secret(workspace_id, key, value)
            if ok:
                return f"敏感变量已保存: {key}（已加密存储）"
            return "保存失败"
        else:
            ok = svc.delete_workspace_secret(workspace_id, key)
            if ok:
                return f"敏感变量已删除: {key}"
            return f"敏感变量不存在: {key}"

    def _list_secrets(self, svc, arguments: dict) -> str:
        """列出工作区密钥名称"""
        workspace_id = arguments.get("workspace_id", "").strip()
        if not workspace_id:
            return "错误：需要提供 workspace_id"

        keys = svc.list_workspace_secret_keys(workspace_id)
        if not keys:
            return f"工作区 {workspace_id} 没有配置敏感变量"
        return f"工作区 {workspace_id} 的敏感变量（共 {len(keys)} 个）:\n" + "\n".join(f"  - {k}" for k in keys)
