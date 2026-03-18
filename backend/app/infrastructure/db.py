"""SQLite 连接管理器：统一管理所有 DB 文件的持久连接

每个 db 文件维护一个持久连接，启用 WAL + busy_timeout。
应用关闭时通过 close_all() 释放所有连接。

预留 user_id 参数，当前默认 "default"（R3 多用户隔离）。
"""

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger("evoiceclaw.db")

_connections: dict[str, sqlite3.Connection] = {}
_lock = threading.Lock()

# 数据库文件默认路径
_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "db"
MAIN_DB = _DATA_DIR / "main.db"
AUDIT_DB = _DATA_DIR / "audit.db"


def get_connection(db_path: str | Path | None = None, timeout: float = 10.0, user_id: str = "default") -> sqlite3.Connection:
    """获取或创建指定 db 文件的持久连接

    首次创建时启用：
    - journal_mode=WAL（并发读不阻塞）
    - busy_timeout=10000（避免 SQLITE_BUSY）
    - foreign_keys=ON
    - check_same_thread=False（FastAPI 多线程安全）

    Args:
        db_path: 数据库文件路径，默认 MAIN_DB
        timeout: sqlite3.connect 的 timeout 参数
        user_id: 预留多用户隔离（R3），当前未使用

    Returns:
        持久化的 sqlite3.Connection
    """
    if db_path is None:
        db_path = MAIN_DB
    key = str(Path(db_path).resolve())

    with _lock:
        conn = _connections.get(key)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.ProgrammingError:
                _connections.pop(key, None)

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path), timeout=timeout, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row

        _connections[key] = conn
        logger.info("[DB] 新建持久连接: %s", key)
        return conn


def init_tables() -> None:
    """初始化主数据库表结构。"""
    conn = get_connection(MAIN_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT PRIMARY KEY,
            title       TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
            user_id     TEXT NOT NULL DEFAULT 'default'
        );

        CREATE TABLE IF NOT EXISTS messages (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            model       TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            user_id     TEXT NOT NULL DEFAULT 'default'
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

        -- Phase 7: 评测任务队列表
        CREATE TABLE IF NOT EXISTS evaluation_queue (
            task_id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            status TEXT NOT NULL,
            priority INTEGER DEFAULT 50,
            trigger TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            started_at DATETIME,
            completed_at DATETIME,
            error_msg TEXT,
            eval_id TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_eval_queue_status ON evaluation_queue(status, priority);
        CREATE INDEX IF NOT EXISTS idx_eval_queue_model ON evaluation_queue(model_id);

        -- Phase 7D: 规则生成状态表（记录对话轮次，驱动触发器）
        CREATE TABLE IF NOT EXISTS rule_generation_state (
            id TEXT PRIMARY KEY DEFAULT 'default',
            conversation_count INTEGER DEFAULT 0,
            last_trigger_count INTEGER DEFAULT 0,
            last_trigger_at DATETIME
        );
    """)
    conn.commit()

    # 兼容已有数据库：为 messages 表添加 Phase 7D 所需字段（如果不存在）
    _add_messages_columns_if_missing(conn)

    logger.info("[DB] 主数据库表初始化完成: %s", MAIN_DB)


def _add_messages_columns_if_missing(conn) -> None:
    """为 messages 表动态添加缺失字段（兼容旧数据库）"""
    new_columns = [
        ("intent", "TEXT"),           # 意图分类：general/reasoning/coding/long_text
        ("cost_usd", "REAL DEFAULT 0"),  # 本轮估算成本（美元）
        ("is_summoned", "INTEGER DEFAULT 0"),  # 是否为召唤特定模型的消息
        ("tool_calls_json", "TEXT"),   # assistant 消息的 tool_calls 序列化 JSON
        ("tool_call_id", "TEXT"),      # tool 角色消息关联的 tool_call ID
        ("tool_name", "TEXT"),         # tool 角色消息的工具名称
    ]
    for col_name, col_def in new_columns:
        try:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_def}")
            conn.commit()
            logger.info("[DB] 已为 messages 表添加 %s 列", col_name)
        except Exception as e:
            # 列已存在或其他原因忽略（首次迁移正常，后续启动会触发此分支）
            logger.debug("[DB] messages 表添加列 %s 跳过: %s", col_name, e)


def init_audit_tables() -> None:
    """初始化审计数据库表结构。"""
    conn = get_connection(AUDIT_DB)

    # Step 1: 创建表（不含 workspace_id，兼容旧表）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          TEXT PRIMARY KEY,
            trace_id    TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            level       TEXT NOT NULL,
            component   TEXT NOT NULL,
            action      TEXT NOT NULL,
            detail      TEXT,
            duration_ms INTEGER,
            user_id     TEXT DEFAULT 'default'
        )
    """)
    conn.commit()

    # Step 2: 兼容迁移——先补列，再建索引（避免旧表缺列时建索引失败）
    try:
        conn.execute("ALTER TABLE audit_log ADD COLUMN workspace_id TEXT DEFAULT 'global'")
        conn.commit()
        logger.info("[DB] 已为 audit_log 表添加 workspace_id 列")
    except Exception as e:
        # 列已存在或其他原因忽略（首次迁移正常，后续启动会触发此分支）
        logger.debug("[DB] audit_log 表添加 workspace_id 列跳过: %s", e)

    # Step 3: 创建索引（此时 workspace_id 列已确保存在）
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_log(trace_id);
        CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_audit_level ON audit_log(level);
        CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_log(workspace_id);
    """)
    conn.commit()

    logger.info("[DB] 审计数据库表初始化完成: %s", AUDIT_DB)


def create_session(session_id: str, title: str = "", user_id: str = "default") -> None:
    """创建会话（INSERT OR IGNORE，幂等）"""
    conn = get_connection(MAIN_DB)
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, title, user_id) VALUES (?, ?, ?)",
        (session_id, title, user_id),
    )
    conn.commit()


def update_session_title(session_id: str, title: str) -> None:
    """更新会话标题（用首条用户消息截取）"""
    conn = get_connection(MAIN_DB)
    conn.execute(
        "UPDATE sessions SET title = ?, updated_at = datetime('now') WHERE id = ?",
        (title[:100], session_id),
    )
    conn.commit()


def touch_session(session_id: str) -> None:
    """更新会话的 updated_at 时间戳"""
    conn = get_connection(MAIN_DB)
    conn.execute(
        "UPDATE sessions SET updated_at = datetime('now') WHERE id = ?",
        (session_id,),
    )
    conn.commit()


def insert_message(
    msg_id: str,
    session_id: str,
    role: str,
    content: str,
    model: str | None = None,
    user_id: str = "default",
    tool_calls_json: str | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
) -> None:
    """插入单条消息

    Args:
        tool_calls_json: assistant 消息的 tool_calls 序列化 JSON
        tool_call_id: tool 角色消息关联的 tool_call ID
        tool_name: tool 角色消息的工具名称
    """
    conn = get_connection(MAIN_DB)
    conn.execute(
        "INSERT OR IGNORE INTO messages "
        "(id, session_id, role, content, model, user_id, tool_calls_json, tool_call_id, tool_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (msg_id, session_id, role, content, model, user_id, tool_calls_json, tool_call_id, tool_name),
    )
    conn.commit()


def load_session_messages(session_id: str, limit: int = 200) -> list[dict]:
    """按时间正序加载会话消息

    Returns:
        [{"id", "role", "content", "model", "created_at", "tool_calls_json", "tool_call_id", "tool_name"}, ...]
    """
    conn = get_connection(MAIN_DB)
    rows = conn.execute(
        "SELECT id, role, content, model, created_at, tool_calls_json, tool_call_id, tool_name "
        "FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def list_sessions(user_id: str = "default", limit: int = 50, offset: int = 0) -> list[dict]:
    """按更新时间倒序列出会话，含消息数

    Returns:
        [{"id", "title", "created_at", "updated_at", "message_count"}, ...]
    """
    conn = get_connection(MAIN_DB)
    rows = conn.execute(
        "SELECT s.id, s.title, s.created_at, s.updated_at, "
        "  (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count "
        "FROM sessions s WHERE s.user_id = ? "
        "ORDER BY s.updated_at DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_session(session_id: str) -> None:
    """删除会话（CASCADE 自动清理消息）"""
    conn = get_connection(MAIN_DB)
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()


def close_all() -> None:
    """关闭所有持久连接（应用关闭时调用）。"""
    with _lock:
        for key, conn in _connections.items():
            try:
                conn.close()
                logger.info("[DB] 已关闭连接: %s", key)
            except Exception as e:
                logger.warning("[DB] 关闭连接失败: %s error=%s", key, e)
        _connections.clear()
