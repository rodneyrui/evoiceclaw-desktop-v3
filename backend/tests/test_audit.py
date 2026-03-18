"""审计日志服务测试"""

import pytest
import uuid
from datetime import datetime, timezone

from app.security.audit import (
    log_event,
    query_audit,
    new_trace_id,
    init_audit,
    LEVEL_INFO,
    LEVEL_WARN,
    LEVEL_ERROR,
)


# ─── 辅助工具 ─────────────────────────────────────────────────

def _unique_component() -> str:
    """每个测试用例用唯一组件名，避免交叉污染"""
    return f"test_{uuid.uuid4().hex[:8]}"


# ─── new_trace_id ─────────────────────────────────────────────

class TestNewTraceId:

    def test_returns_string(self):
        tid = new_trace_id()
        assert isinstance(tid, str)

    def test_uuid4_format(self):
        tid = new_trace_id()
        # UUID4 格式：xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
        parsed = uuid.UUID(tid)
        assert parsed.version == 4

    def test_unique(self):
        ids = {new_trace_id() for _ in range(100)}
        assert len(ids) == 100


# ─── 日志级别常量 ─────────────────────────────────────────────

class TestLevelConstants:

    def test_info_level(self):
        assert LEVEL_INFO == "INFO"

    def test_warn_level(self):
        assert LEVEL_WARN == "WARN"

    def test_error_level(self):
        assert LEVEL_ERROR == "ERROR"


# ─── init_audit ───────────────────────────────────────────────

class TestInitAudit:

    def test_init_audit_does_not_raise(self):
        """init_audit 是空操作，不应抛出异常"""
        init_audit()  # 不应抛出


# ─── log_event ────────────────────────────────────────────────

class TestLogEvent:

    def test_log_basic_event(self):
        """写入基本事件，能被 query_audit 查到"""
        component = _unique_component()
        trace_id = new_trace_id()
        log_event(
            component=component,
            action="TEST_ACTION",
            trace_id=trace_id,
            detail="test detail",
        )
        results = query_audit(trace_id=trace_id)
        assert len(results) == 1
        assert results[0]["component"] == component
        assert results[0]["action"] == "TEST_ACTION"

    def test_log_with_all_fields(self):
        component = _unique_component()
        trace_id = new_trace_id()
        log_event(
            component=component,
            action="FULL_EVENT",
            trace_id=trace_id,
            detail='{"key": "value"}',
            level=LEVEL_WARN,
            duration_ms=42,
            user_id="user_test",
            workspace_id="ws_test",
        )
        results = query_audit(trace_id=trace_id)
        assert len(results) == 1
        r = results[0]
        assert r["level"] == LEVEL_WARN
        assert r["duration_ms"] == 42
        assert r["workspace_id"] == "ws_test"

    def test_log_without_trace_id_auto_generates(self):
        """不传 trace_id 时自动生成"""
        component = _unique_component()
        log_event(component=component, action="AUTO_TRACE")
        results = query_audit(component=component)
        assert len(results) >= 1
        assert results[0]["trace_id"] is not None
        assert len(results[0]["trace_id"]) > 0

    def test_log_default_level_is_info(self):
        component = _unique_component()
        trace_id = new_trace_id()
        log_event(component=component, action="DEFAULT_LEVEL", trace_id=trace_id)
        results = query_audit(trace_id=trace_id)
        assert results[0]["level"] == LEVEL_INFO

    def test_log_warn_level(self):
        component = _unique_component()
        trace_id = new_trace_id()
        log_event(
            component=component,
            action="WARN_EVENT",
            trace_id=trace_id,
            level=LEVEL_WARN,
        )
        results = query_audit(trace_id=trace_id)
        assert results[0]["level"] == LEVEL_WARN

    def test_multiple_events_same_trace(self):
        """同一 trace_id 的多条事件"""
        component = _unique_component()
        trace_id = new_trace_id()
        for action in ["STEP_1", "STEP_2", "STEP_3"]:
            log_event(component=component, action=action, trace_id=trace_id)
        results = query_audit(trace_id=trace_id)
        assert len(results) == 3
        actions = {r["action"] for r in results}
        assert actions == {"STEP_1", "STEP_2", "STEP_3"}

    def test_log_does_not_raise_on_error(self, monkeypatch):
        """即使 DB 写入失败，log_event 也不应抛出（业务不中断）"""
        from app.security import audit as audit_module
        original = audit_module.get_connection

        def bad_conn(*args, **kwargs):
            raise RuntimeError("DB unavailable")

        monkeypatch.setattr(audit_module, "get_connection", bad_conn)
        # 不应抛出
        log_event(component="test", action="FAIL_TEST")


# ─── query_audit ──────────────────────────────────────────────

class TestQueryAudit:

    def setup_method(self):
        """每个测试创建独立组件名"""
        self.component = _unique_component()
        self.trace_id = new_trace_id()

    def _log(self, action="TEST", level=LEVEL_INFO, workspace_id="global"):
        log_event(
            component=self.component,
            action=action,
            trace_id=self.trace_id,
            level=level,
            workspace_id=workspace_id,
        )

    def test_query_by_trace_id(self):
        self._log()
        results = query_audit(trace_id=self.trace_id)
        assert len(results) == 1

    def test_query_by_component(self):
        self._log("A1")
        self._log("A2")
        results = query_audit(component=self.component)
        assert len(results) == 2

    def test_query_by_level(self):
        warn_component = _unique_component()
        warn_trace = new_trace_id()
        log_event(component=warn_component, action="W1", trace_id=warn_trace, level=LEVEL_WARN)
        log_event(component=warn_component, action="I1", trace_id=warn_trace, level=LEVEL_INFO)
        results = query_audit(component=warn_component, level=LEVEL_WARN)
        assert len(results) == 1
        assert results[0]["action"] == "W1"

    def test_query_by_workspace_id(self):
        ws = f"ws_{uuid.uuid4().hex[:6]}"
        log_event(
            component=self.component,
            action="WS_EVENT",
            trace_id=self.trace_id,
            workspace_id=ws,
        )
        results = query_audit(component=self.component, workspace_id=ws)
        assert len(results) == 1
        assert results[0]["workspace_id"] == ws

    def test_query_limit(self):
        component = _unique_component()
        for i in range(10):
            log_event(component=component, action=f"EVT_{i}")
        results = query_audit(component=component, limit=3)
        assert len(results) == 3

    def test_query_returns_dict_list(self):
        self._log()
        results = query_audit(trace_id=self.trace_id)
        assert isinstance(results, list)
        assert isinstance(results[0], dict)

    def test_query_result_has_expected_fields(self):
        self._log()
        r = query_audit(trace_id=self.trace_id)[0]
        expected_fields = {"id", "trace_id", "timestamp", "level", "component", "action"}
        assert expected_fields.issubset(r.keys())

    def test_query_no_match_returns_empty(self):
        results = query_audit(trace_id="nonexistent_trace_id_xyz")
        assert results == []

    def test_query_ordered_by_timestamp_desc(self):
        component = _unique_component()
        for action in ["FIRST", "SECOND", "THIRD"]:
            log_event(component=component, action=action)
        results = query_audit(component=component, limit=3)
        # 最新的在前（DESC）
        timestamps = [r["timestamp"] for r in results]
        assert timestamps == sorted(timestamps, reverse=True)
