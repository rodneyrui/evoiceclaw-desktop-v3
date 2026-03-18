"""记忆操作工具 — recall / save / delete

提供用户记忆的语义召回、保存和删除功能。
底层使用 LanceDB 向量表 + Embedding 服务实现语义检索。
"""

import logging
import uuid
from datetime import datetime, timezone

from app.infrastructure.embedding import get_embedding_service
from app.infrastructure.vector_db import get_table
from app.kernel.tools.protocol import SkillProtocol

logger = logging.getLogger("evoiceclaw.tool.memory_ops")

# 合法的记忆类型和优先级枚举
_VALID_TYPES = ("fact", "preference", "summary", "episode")
_VALID_PRIORITIES = ("high", "medium", "low")


def _get_active_workspace_id() -> str:
    """获取当前激活工作区的 ID，无激活工作区时返回 'global'。"""
    try:
        from app.services.workspace_service import get_workspace_service
        ws_svc = get_workspace_service()
        active = ws_svc.get_active_workspace()
        if active:
            return active.id
    except Exception as e:
        logger.debug("[MemoryOps] 获取激活工作区失败: %s", e)
    return "global"


class MemoryOpsTool(SkillProtocol):
    """管理用户记忆（语义召回、保存、删除）

    三种操作:
    - recall: 根据自然语言查询进行语义检索，返回最相关的记忆条目
    - save:   将新记忆存入向量数据库（自动向量化）
    - delete: 按 memory_id 删除指定记忆
    """

    @property
    def name(self) -> str:
        return "memory_ops"

    @property
    def description(self) -> str:
        return (
            "管理用户记忆。支持三种操作：\n"
            "1. recall — 语义检索：根据查询文本召回最相关的记忆\n"
            "2. save — 保存记忆：将事实、偏好、总结或事件存入记忆库\n"
            "3. delete — 删除记忆：按 memory_id 删除指定记忆条目\n"
            "记忆会持久化存储，跨会话可用。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["recall", "save", "delete"],
                    "description": "操作类型：recall（语义检索）、save（保存）、delete（删除）",
                },
                # recall 参数
                "query": {
                    "type": "string",
                    "description": "[recall] 语义检索的查询文本",
                },
                "limit": {
                    "type": "integer",
                    "description": "[recall] 返回结果数量上限（默认 5）",
                },
                # save 参数
                "content": {
                    "type": "string",
                    "description": "[save] 要保存的记忆内容",
                },
                "type": {
                    "type": "string",
                    "enum": ["fact", "preference", "summary", "episode"],
                    "description": "[save] 记忆类型：fact（事实）、preference（偏好）、summary（总结）、episode（事件）",
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "[save] 优先级（默认 medium）",
                },
                # delete 参数
                "memory_id": {
                    "type": "string",
                    "description": "[delete] 要删除的记忆 ID",
                },
            },
            "required": ["action"],
        }

    @property
    def capability_brief(self) -> str:
        return "管理用户记忆（语义召回、保存、删除）"

    @property
    def required_permissions(self) -> list[str]:
        return ["memory"]

    @property
    def tool_timeout(self) -> int:
        """记忆操作不需要太长时间"""
        return 15

    async def execute(self, arguments: dict) -> str:
        action = arguments.get("action", "")

        if action == "recall":
            return await self._recall(arguments)
        elif action == "save":
            return await self._save(arguments)
        elif action == "delete":
            return await self._delete(arguments)
        else:
            return f"错误：未知操作 '{action}'，支持的操作：recall、save、delete"

    async def _recall(self, arguments: dict) -> str:
        """语义检索记忆"""
        query = arguments.get("query", "")
        if not query:
            return "错误：recall 操作需要提供 query 参数"

        limit = arguments.get("limit", 5)
        if not isinstance(limit, int) or limit < 1:
            limit = 5
        # 限制最大返回数量，避免过大响应
        limit = min(limit, 20)

        try:
            # 获取查询文本的向量
            embedding_svc = get_embedding_service()
            query_vector = await embedding_svc.embed(query)

            # 在 memories 表中进行向量检索（按工作区隔离）
            table = get_table("memories")
            ws_id = _get_active_workspace_id()
            results = (
                table.search(query_vector)
                .where(f"workspace_id = '{ws_id}'", prefilter=True)
                .limit(limit)
                .to_list()
            )

            if not results:
                return f"未找到与 \"{query}\" 相关的记忆"

            # 格式化结果
            lines = [f"找到 {len(results)} 条相关记忆：\n"]
            for i, row in enumerate(results, 1):
                memory_id = row.get("id", "unknown")
                content = row.get("content", "")
                mem_type = row.get("type", "")
                priority = row.get("priority", "")
                created_at = row.get("created_at", "")
                distance = row.get("_distance", None)

                lines.append(f"[{i}] ID: {memory_id}")
                lines.append(f"    内容: {content}")
                lines.append(f"    类型: {mem_type} | 优先级: {priority}")
                if created_at:
                    lines.append(f"    创建时间: {created_at}")
                if distance is not None:
                    lines.append(f"    相似度距离: {distance:.4f}")
                lines.append("")

            logger.info("记忆检索: query='%s' limit=%d results=%d", query, limit, len(results))
            return "\n".join(lines)

        except ValueError as e:
            # get_table 抛出的表不存在异常
            return f"记忆库尚未初始化：{e}"
        except Exception as e:
            logger.error("记忆检索失败: %s", e, exc_info=True)
            return f"记忆检索失败：{e}"

    async def _save(self, arguments: dict) -> str:
        """保存新记忆"""
        content = arguments.get("content", "")
        if not content:
            return "错误：save 操作需要提供 content 参数"

        mem_type = arguments.get("type", "")
        if mem_type not in _VALID_TYPES:
            return f"错误：无效的记忆类型 '{mem_type}'，支持的类型：{', '.join(_VALID_TYPES)}"

        priority = arguments.get("priority", "medium")
        if priority not in _VALID_PRIORITIES:
            return f"错误：无效的优先级 '{priority}'，支持的优先级：{', '.join(_VALID_PRIORITIES)}"

        try:
            # 向量化记忆内容
            embedding_svc = get_embedding_service()
            vector = await embedding_svc.embed(content)

            # 生成记忆 ID 和时间戳
            memory_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            # 构建记忆记录
            record = {
                "id": memory_id,
                "content": content,
                "type": mem_type,
                "priority": priority,
                "vector": vector,
                "source_conv_id": "manual",
                "entities": "[]",
                "created_at": now,
                "last_recalled": now,
                "recall_count": 0,
                "ttl_days": -1,
                "user_id": "default",
                "workspace_id": _get_active_workspace_id(),  # 工作区隔离
            }

            # 使用 merge_insert 写入（基于 id 去重）
            table = get_table("memories")
            table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute([record])

            logger.info(
                "保存记忆: id=%s type=%s priority=%s content='%s'",
                memory_id, mem_type, priority, content[:50],
            )
            return (
                f"记忆已保存：\n"
                f"  ID: {memory_id}\n"
                f"  类型: {mem_type}\n"
                f"  优先级: {priority}\n"
                f"  内容: {content[:100]}{'...' if len(content) > 100 else ''}"
            )

        except ValueError as e:
            return f"记忆库尚未初始化：{e}"
        except Exception as e:
            logger.error("保存记忆失败: %s", e, exc_info=True)
            return f"保存记忆失败：{e}"

    async def _delete(self, arguments: dict) -> str:
        """删除指定记忆"""
        memory_id = arguments.get("memory_id", "")
        if not memory_id:
            return "错误：delete 操作需要提供 memory_id 参数"

        try:
            table = get_table("memories")
            # 删除时校验 workspace_id，防止跨工作区误删
            ws_id = _get_active_workspace_id()
            table.delete(f"id = '{memory_id}' AND workspace_id = '{ws_id}'")

            logger.info("删除记忆: id=%s", memory_id)
            return f"记忆已删除：{memory_id}"

        except ValueError as e:
            return f"记忆库尚未初始化：{e}"
        except Exception as e:
            logger.error("删除记忆失败: %s", e, exc_info=True)
            return f"删除记忆失败：{e}"
