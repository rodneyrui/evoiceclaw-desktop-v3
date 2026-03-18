"""SQLite 只读查询工具 — 让 LLM 查询系统数据库

安全措施：
- 仅允许 SELECT 语句
- 禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/ATTACH
- 强制 LIMIT（默认 20，上限 100）
- 只读连接，不 commit
- 结果超过 2000 字符时截断

迁移自 v2 services/skill/builtin/query_database.py
v3 适配：使用 main.db（sessions/messages 表）替换 v2 的 tasks.db/memory.db
"""

import logging
import re
import sqlite3

from app.kernel.tools.protocol import SkillProtocol
from app.infrastructure.db import get_connection, MAIN_DB

logger = logging.getLogger("evoiceclaw.tool.database")

# 数据库路径映射（v3 统一到 main.db）
_DB_PATHS = {
    "main": MAIN_DB,
}

# 禁止的 SQL 关键字（防止写操作）
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|REPLACE|PRAGMA\s+\w+\s*=)\b",
    re.IGNORECASE,
)

_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20
_MAX_RESULT_CHARS = 2000


class QueryDatabaseTool(SkillProtocol):
    """对系统 SQLite 数据库执行只读查询"""

    @property
    def name(self) -> str:
        return "query_database"

    @property
    def description(self) -> str:
        return (
            "对本系统的 SQLite 数据库执行只读 SQL 查询。\n"
            "可查询的数据库：\n"
            "- main: 主数据库，包含以下表：\n"
            "  - sessions (id, title, created_at, updated_at)\n"
            "  - messages (id, session_id, role, content, created_at)\n"
            "  - audit_log (见审计库)\n"
            "仅支持 SELECT 语句，拒绝任何写操作。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "enum": ["main"],
                    "description": "要查询的数据库（当前仅支持 main）",
                },
                "sql": {
                    "type": "string",
                    "description": "SELECT SQL 语句",
                },
                "limit": {
                    "type": "integer",
                    "description": "最大返回行数（默认 20，上限 100）",
                },
            },
            "required": ["database", "sql"],
        }

    @property
    def capability_brief(self) -> str:
        return "查询系统 SQLite 数据库（只读 SELECT）"

    @property
    def required_permissions(self) -> list[str]:
        return ["read_file"]

    async def execute(self, arguments: dict) -> str:
        database = arguments.get("database", "")
        sql = arguments.get("sql", "").strip()
        limit = min(arguments.get("limit", _DEFAULT_LIMIT), _MAX_LIMIT)

        if not database or not sql:
            return "请提供 database 和 sql 参数"

        if database not in _DB_PATHS:
            return f"无效的数据库: {database}。可选值: {', '.join(_DB_PATHS.keys())}"

        # 安全检查 1: 必须以 SELECT 开头
        if not sql.upper().lstrip().startswith("SELECT"):
            return "仅支持 SELECT 查询语句"

        # 安全检查 2: 禁止写操作关键字
        if _FORBIDDEN_KEYWORDS.search(sql):
            return "SQL 语句包含禁止的操作关键字（仅允许 SELECT）"

        # 强制添加 LIMIT（如果 SQL 中没有）
        if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
            sql = f"{sql.rstrip().rstrip(';')} LIMIT {limit}"

        db_path = _DB_PATHS[database]
        if not db_path.exists():
            return f"数据库文件不存在: {database}"

        try:
            conn = get_connection(db_path)
            cursor = conn.execute(sql)
            rows = cursor.fetchall()

            if not rows:
                return "查询结果为空"

            # 获取列名
            col_names = [desc[0] for desc in cursor.description]

            # 格式化输出
            lines = [" | ".join(col_names)]
            lines.append("-" * len(lines[0]))

            for row in rows:
                values = []
                for v in row:
                    s = str(v) if v is not None else "NULL"
                    if len(s) > 200:
                        s = s[:200] + "..."
                    values.append(s)
                lines.append(" | ".join(values))

            result = "\n".join(lines)

            if len(result) > _MAX_RESULT_CHARS:
                result = result[:_MAX_RESULT_CHARS] + f"\n...(结果已截断，共 {len(rows)} 行)"

            logger.info(
                "[QueryDB] 查询成功: db=%s rows=%d sql=%s",
                database, len(rows), sql[:80],
            )
            return f"查询结果（{len(rows)} 行）：\n\n{result}"

        except sqlite3.OperationalError as e:
            logger.warning("[QueryDB] SQL 执行失败: %s", e)
            return f"SQL 执行失败: {e}"
        except Exception as e:
            logger.error("[QueryDB] 查询异常: %s", e, exc_info=True)
            return f"查询异常: {e}"
