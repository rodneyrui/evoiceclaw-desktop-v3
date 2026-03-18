"""数据库模块单元测试"""

import tempfile
import os
import sqlite3
from pathlib import Path
import pytest
from app.infrastructure.db import (
    get_connection, init_tables, init_audit_tables, close_all,
    MAIN_DB, AUDIT_DB
)


@pytest.fixture
def temp_db_dir():
    """创建临时数据库目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 临时替换数据库路径
        import app.infrastructure.db as db_module
        original_main = db_module.MAIN_DB
        original_audit = db_module.AUDIT_DB
        original_data_dir = db_module._DATA_DIR
        
        tmp_path = Path(tmpdir)
        db_module.MAIN_DB = tmp_path / "main.db"
        db_module.AUDIT_DB = tmp_path / "audit.db"
        db_module._DATA_DIR = tmp_path
        
        yield tmp_path
        
        # 恢复原始路径
        db_module.MAIN_DB = original_main
        db_module.AUDIT_DB = original_audit
        db_module._DATA_DIR = original_data_dir
        
        # 确保关闭所有连接
        close_all()


def test_get_connection_creates_db_file(temp_db_dir):
    """测试获取连接时创建数据库文件"""
    conn = get_connection()
    
    assert conn is not None
    assert isinstance(conn, sqlite3.Connection)
    
    # 验证数据库文件已创建
    db_path = temp_db_dir / "main.db"
    assert db_path.exists()
    
    # 验证连接可用
    cursor = conn.execute("SELECT 1")
    result = cursor.fetchone()
    assert result[0] == 1


def test_get_connection_persistent(temp_db_dir):
    """测试连接持久化"""
    # 第一次获取连接
    conn1 = get_connection()
    
    # 第二次获取应该是同一个连接
    conn2 = get_connection()
    
    assert conn1 is conn2
    
    # 验证连接仍然可用
    cursor = conn1.execute("SELECT 2")
    result = cursor.fetchone()
    assert result[0] == 2


def test_get_connection_with_custom_path(temp_db_dir):
    """测试使用自定义路径获取连接"""
    custom_db = temp_db_dir / "custom.db"
    conn = get_connection(custom_db)
    
    assert conn is not None
    assert custom_db.exists()
    
    # 验证连接可用
    cursor = conn.execute("SELECT sqlite_version()")
    version = cursor.fetchone()[0]
    assert version is not None


def test_get_connection_pragma_settings(temp_db_dir):
    """测试连接PRAGMA设置"""
    conn = get_connection()
    
    # 验证WAL模式
    cursor = conn.execute("PRAGMA journal_mode")
    journal_mode = cursor.fetchone()[0]
    assert journal_mode.upper() == "WAL"
    
    # 验证busy_timeout
    cursor = conn.execute("PRAGMA busy_timeout")
    busy_timeout = cursor.fetchone()[0]
    assert int(busy_timeout) == 10000
    
    # 验证外键
    cursor = conn.execute("PRAGMA foreign_keys")
    foreign_keys = cursor.fetchone()[0]
    assert int(foreign_keys) == 1
    
    # 验证row_factory
    assert conn.row_factory == sqlite3.Row


def test_init_tables_creates_schema(temp_db_dir):
    """测试初始化表结构"""
    init_tables()
    
    conn = get_connection()
    
    # 验证sessions表
    cursor = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='sessions'
    """)
    assert cursor.fetchone() is not None
    
    # 验证messages表
    cursor = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='messages'
    """)
    assert cursor.fetchone() is not None
    
    # 验证evaluation_queue表
    cursor = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='evaluation_queue'
    """)
    assert cursor.fetchone() is not None
    
    # 验证rule_generation_state表
    cursor = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='rule_generation_state'
    """)
    assert cursor.fetchone() is not None


def test_init_tables_idempotent(temp_db_dir):
    """测试初始化表结构是幂等的"""
    # 第一次初始化
    init_tables()
    
    # 第二次初始化不应该失败
    init_tables()
    
    # 验证表仍然存在
    conn = get_connection()
    cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    table_count = cursor.fetchone()[0]
    assert table_count >= 4  # sessions, messages, evaluation_queue, rule_generation_state


def test_init_audit_tables_creates_schema(temp_db_dir):
    """测试初始化审计表结构"""
    init_audit_tables()
    
    # 使用审计数据库连接
    audit_db_path = temp_db_dir / "audit.db"
    conn = get_connection(audit_db_path)
    
    # 验证audit_log表
    cursor = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='audit_log'
    """)
    assert cursor.fetchone() is not None
    
    # 验证索引
    cursor = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='index' AND name LIKE 'idx_audit_%'
    """)
    indexes = cursor.fetchall()
    index_names = [row[0] for row in indexes]
    assert "idx_audit_trace" in index_names
    assert "idx_audit_time" in index_names
    assert "idx_audit_level" in index_names
    assert "idx_audit_workspace" in index_names


def test_init_audit_tables_idempotent(temp_db_dir):
    """测试初始化审计表结构是幂等的"""
    # 第一次初始化
    init_audit_tables()
    
    # 第二次初始化不应该失败
    init_audit_tables()
    
    # 验证表仍然存在
    audit_db_path = temp_db_dir / "audit.db"
    conn = get_connection(audit_db_path)
    cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    table_count = cursor.fetchone()[0]
    assert table_count >= 1  # audit_log


def test_close_all(temp_db_dir):
    """测试关闭所有连接"""
    # 创建多个连接
    conn1 = get_connection()
    custom_db = temp_db_dir / "custom.db"
    conn2 = get_connection(custom_db)
    audit_conn = get_connection(temp_db_dir / "audit.db")
    
    # 验证连接是活动的
    assert conn1.execute("SELECT 1").fetchone()[0] == 1
    assert conn2.execute("SELECT 1").fetchone()[0] == 1
    assert audit_conn.execute("SELECT 1").fetchone()[0] == 1
    
    # 关闭所有连接
    close_all()
    
    # 验证连接已关闭
    with pytest.raises(sqlite3.ProgrammingError):
        conn1.execute("SELECT 1")
    
    with pytest.raises(sqlite3.ProgrammingError):
        conn2.execute("SELECT 1")
    
    with pytest.raises(sqlite3.ProgrammingError):
        audit_conn.execute("SELECT 1")


def test_get_connection_with_timeout(temp_db_dir):
    """测试带超时的连接"""
    conn = get_connection(timeout=5.0)
    assert conn is not None
    
    # 验证连接可用
    cursor = conn.execute("SELECT 3")
    result = cursor.fetchone()
    assert result[0] == 3


def test_get_connection_with_user_id(temp_db_dir):
    """测试带用户ID的连接（R3预留）"""
    # user_id参数目前未使用，但应该接受
    conn = get_connection(user_id="test_user")
    assert conn is not None
    
    # 验证连接可用
    cursor = conn.execute("SELECT 4")
    result = cursor.fetchone()
    assert result[0] == 4


def test_connection_recovery_on_error(temp_db_dir):
    """测试连接错误后的恢复"""
    conn = get_connection()
    
    # 故意关闭连接（模拟错误）
    conn.close()
    
    # 再次获取连接应该创建新连接
    new_conn = get_connection()
    assert new_conn is not None
    assert new_conn is not conn
    
    # 验证新连接可用
    cursor = new_conn.execute("SELECT 5")
    result = cursor.fetchone()
    assert result[0] == 5


def test_messages_table_columns(temp_db_dir):
    """测试messages表的列结构"""
    init_tables()
    conn = get_connection()
    
    # 获取表结构
    cursor = conn.execute("PRAGMA table_info(messages)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    
    # 验证基本列
    assert "id" in columns
    assert "session_id" in columns
    assert "role" in columns
    assert "content" in columns
    assert "model" in columns
    assert "created_at" in columns
    assert "user_id" in columns
    
    # 验证Phase 7D新增列
    assert "intent" in columns
    assert "cost_usd" in columns
    assert "is_summoned" in columns


def test_audit_log_table_columns(temp_db_dir):
    """测试audit_log表的列结构"""
    init_audit_tables()
    audit_db_path = temp_db_dir / "audit.db"
    conn = get_connection(audit_db_path)
    
    # 获取表结构
    cursor = conn.execute("PRAGMA table_info(audit_log)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    
    # 验证基本列
    assert "id" in columns
    assert "trace_id" in columns
    assert "timestamp" in columns
    assert "level" in columns
    assert "component" in columns
    assert "action" in columns
    assert "detail" in columns
    assert "duration_ms" in columns
    assert "user_id" in columns
    assert "workspace_id" in columns


def test_database_directory_creation(temp_db_dir):
    """测试数据库目录自动创建"""
    # 创建深层目录路径
    deep_dir = temp_db_dir / "deep" / "nested" / "dir"
    deep_db = deep_dir / "deep.db"
    
    # 获取连接应该自动创建目录
    conn = get_connection(deep_db)
    assert conn is not None
    assert deep_db.exists()
    assert deep_dir.exists()


# ─── tool_calls 持久化 ────────────────────────────────────────────────────

def test_messages_table_has_tool_columns(temp_db_dir):
    """messages 表包含 tool_calls_json/tool_call_id/tool_name 列"""
    init_tables()
    conn = get_connection()
    cursor = conn.execute("PRAGMA table_info(messages)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "tool_calls_json" in columns
    assert "tool_call_id" in columns
    assert "tool_name" in columns


def test_insert_message_with_tool_calls(temp_db_dir):
    """insert_message 可以写入 tool_calls_json"""
    from app.infrastructure.db import insert_message, create_session
    init_tables()
    create_session("s1", "test")

    tc_json = '[{"id":"tc_001","name":"web_search","arguments":{"query":"test"}}]'
    insert_message(
        msg_id="m1", session_id="s1", role="assistant",
        content="让我搜索一下", tool_calls_json=tc_json,
    )

    conn = get_connection()
    row = conn.execute("SELECT tool_calls_json FROM messages WHERE id='m1'").fetchone()
    assert row["tool_calls_json"] == tc_json


def test_insert_message_with_tool_call_id(temp_db_dir):
    """insert_message 可以写入 tool_call_id 和 tool_name"""
    from app.infrastructure.db import insert_message, create_session
    init_tables()
    create_session("s1", "test")

    insert_message(
        msg_id="m2", session_id="s1", role="tool",
        content='{"result": "ok"}',
        tool_call_id="tc_001", tool_name="web_search",
    )

    conn = get_connection()
    row = conn.execute("SELECT tool_call_id, tool_name FROM messages WHERE id='m2'").fetchone()
    assert row["tool_call_id"] == "tc_001"
    assert row["tool_name"] == "web_search"


def test_load_session_messages_returns_tool_fields(temp_db_dir):
    """load_session_messages 返回 tool_calls_json/tool_call_id/tool_name"""
    from app.infrastructure.db import insert_message, load_session_messages, create_session
    init_tables()
    create_session("s1", "test")

    tc_json = '[{"id":"tc_002","name":"read_file","arguments":{"path":"/tmp/a.txt"}}]'
    insert_message(msg_id="m1", session_id="s1", role="assistant",
                   content="读取文件", tool_calls_json=tc_json)
    insert_message(msg_id="m2", session_id="s1", role="tool",
                   content="文件内容", tool_call_id="tc_002", tool_name="read_file")

    msgs = load_session_messages("s1")
    assert len(msgs) == 2

    assistant_msg = msgs[0]
    assert assistant_msg["tool_calls_json"] == tc_json
    assert assistant_msg["tool_call_id"] is None

    tool_msg = msgs[1]
    assert tool_msg["tool_call_id"] == "tc_002"
    assert tool_msg["tool_name"] == "read_file"
    assert tool_msg["tool_calls_json"] is None


def test_insert_message_without_tool_fields(temp_db_dir):
    """普通消息不传 tool 字段时，字段为 None"""
    from app.infrastructure.db import insert_message, load_session_messages, create_session
    init_tables()
    create_session("s1", "test")

    insert_message(msg_id="m1", session_id="s1", role="user", content="你好")

    msgs = load_session_messages("s1")
    assert len(msgs) == 1
    assert msgs[0]["tool_calls_json"] is None
    assert msgs[0]["tool_call_id"] is None
    assert msgs[0]["tool_name"] is None