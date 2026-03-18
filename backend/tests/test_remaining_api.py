"""剩余 API 端点与评测调度子系统测试

覆盖：
- evaluation.py: trigger_evaluation（各 reason / 未知 reason）、cancel_evaluation、
                 get_evaluation_status（DB 返回行）、get_task_detail（404 / 存在）
- logs.py: SSELogHandler.emit（广播 + buffer）、install_log_handler
- permissions.py: respond_to_elevation（404 / 批准 / 拒绝 / 处理失败）、get_elevation_status（404 / 正常）
- IdleMonitor: record_activity、_check_user_idle、is_idle（全空闲 / 部分非空闲）
"""

import asyncio
import logging
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ─── evaluation.py API ────────────────────────────────────────────────────────

class TestTriggerEvaluationEndpoint:

    def _mock_scheduler(self, task_id="task-001"):
        m = MagicMock()
        m.trigger_new_model_evaluation.return_value = task_id
        m.trigger_scheduled_evaluation.return_value = task_id
        m.trigger_idle_evaluation.return_value = task_id
        return m

    @pytest.mark.asyncio
    async def test_reason_manual调用trigger_new_model_evaluation(self):
        from app.api.v1.evaluation import trigger_evaluation, TriggerEvaluationRequest
        mock_sched = self._mock_scheduler()
        with patch("app.api.v1.evaluation.get_scheduler", return_value=mock_sched):
            req = TriggerEvaluationRequest(model_id="deepseek/deepseek-chat", reason="manual")
            result = await trigger_evaluation(req)
        mock_sched.trigger_new_model_evaluation.assert_called_once_with("deepseek/deepseek-chat")
        assert result["success"] is True
        assert result["task_id"] == "task-001"

    @pytest.mark.asyncio
    async def test_reason_auto_new_model调用trigger_new_model_evaluation(self):
        from app.api.v1.evaluation import trigger_evaluation, TriggerEvaluationRequest
        mock_sched = self._mock_scheduler()
        with patch("app.api.v1.evaluation.get_scheduler", return_value=mock_sched):
            req = TriggerEvaluationRequest(model_id="qwen/qwen-max", reason="auto_new_model")
            result = await trigger_evaluation(req)
        mock_sched.trigger_new_model_evaluation.assert_called_once()

    @pytest.mark.asyncio
    async def test_reason_scheduled调用trigger_scheduled_evaluation(self):
        from app.api.v1.evaluation import trigger_evaluation, TriggerEvaluationRequest
        mock_sched = self._mock_scheduler()
        with patch("app.api.v1.evaluation.get_scheduler", return_value=mock_sched):
            req = TriggerEvaluationRequest(model_id="m1", reason="scheduled")
            result = await trigger_evaluation(req)
        mock_sched.trigger_scheduled_evaluation.assert_called_once_with("m1")

    @pytest.mark.asyncio
    async def test_reason_idle调用trigger_idle_evaluation(self):
        from app.api.v1.evaluation import trigger_evaluation, TriggerEvaluationRequest
        mock_sched = self._mock_scheduler()
        with patch("app.api.v1.evaluation.get_scheduler", return_value=mock_sched):
            req = TriggerEvaluationRequest(model_id="m1", reason="idle")
            result = await trigger_evaluation(req)
        mock_sched.trigger_idle_evaluation.assert_called_once_with("m1")

    @pytest.mark.asyncio
    async def test_未知reason抛出HTTP异常(self):
        """未知 reason 在 try 块内引发 HTTPException，被外层 except 捕获重包为 500"""
        from app.api.v1.evaluation import trigger_evaluation, TriggerEvaluationRequest
        from fastapi import HTTPException
        mock_sched = self._mock_scheduler()
        with patch("app.api.v1.evaluation.get_scheduler", return_value=mock_sched):
            req = TriggerEvaluationRequest(model_id="m1", reason="unknown_xyz")
            with pytest.raises(HTTPException) as exc_info:
                await trigger_evaluation(req)
        # HTTPException(400) 被外层 except Exception 捕获后重包为 500
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_scheduler异常返回500(self):
        from app.api.v1.evaluation import trigger_evaluation, TriggerEvaluationRequest
        from fastapi import HTTPException
        mock_sched = MagicMock()
        mock_sched.trigger_new_model_evaluation.side_effect = RuntimeError("DB error")
        with patch("app.api.v1.evaluation.get_scheduler", return_value=mock_sched):
            req = TriggerEvaluationRequest(model_id="m1", reason="manual")
            with pytest.raises(HTTPException) as exc_info:
                await trigger_evaluation(req)
        assert exc_info.value.status_code == 500


class TestCancelEvaluationEndpoint:

    @pytest.mark.asyncio
    async def test_取消成功返回success_true(self):
        from app.api.v1.evaluation import cancel_evaluation
        mock_sched = MagicMock()
        mock_sched.cancel_task.return_value = True
        with patch("app.api.v1.evaluation.get_scheduler", return_value=mock_sched):
            result = await cancel_evaluation("task-abc")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_任务不存在返回success_false(self):
        from app.api.v1.evaluation import cancel_evaluation
        mock_sched = MagicMock()
        mock_sched.cancel_task.return_value = False
        with patch("app.api.v1.evaluation.get_scheduler", return_value=mock_sched):
            result = await cancel_evaluation("task-nonexistent")
        assert result["success"] is False


class TestGetEvaluationStatus:

    @pytest.mark.asyncio
    async def test_返回任务列表(self):
        from app.api.v1.evaluation import get_evaluation_status
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("t1", "model-a", "running", 10, "manual", "2026-01-01", None, None, None, None),
        ]
        mock_conn.cursor.return_value = mock_cursor
        with patch("app.api.v1.evaluation.get_connection", return_value=mock_conn):
            result = await get_evaluation_status()
        assert result["success"] is True
        assert result["total"] == 1
        assert result["tasks"][0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_DB异常返回500(self):
        from app.api.v1.evaluation import get_evaluation_status
        from fastapi import HTTPException
        with patch("app.api.v1.evaluation.get_connection", side_effect=RuntimeError("DB down")):
            with pytest.raises(HTTPException) as exc_info:
                await get_evaluation_status()
        assert exc_info.value.status_code == 500


class TestGetTaskDetail:

    @pytest.mark.asyncio
    async def test_任务不存在返回404(self):
        from app.api.v1.evaluation import get_task_detail
        from fastapi import HTTPException
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        with patch("app.api.v1.evaluation.get_connection", return_value=mock_conn):
            with pytest.raises(HTTPException) as exc_info:
                await get_task_detail("nonexistent-task")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_任务存在返回详情(self):
        from app.api.v1.evaluation import get_task_detail
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (
            "t1", "model-a", "completed", 10, "manual",
            "2026-01-01", "2026-01-01", "2026-01-01", None, "eval-123",
        )
        mock_conn.cursor.return_value = mock_cursor
        with patch("app.api.v1.evaluation.get_connection", return_value=mock_conn):
            result = await get_task_detail("t1")
        assert result["success"] is True
        assert result["task"].task_id == "t1"
        assert result["task"].eval_id == "eval-123"


# ─── logs.py SSELogHandler ────────────────────────────────────────────────────

class TestSSELogHandler:

    def _make_record(self, msg="test log message", level=logging.INFO) -> logging.LogRecord:
        record = logging.LogRecord(
            name="evoiceclaw.test",
            level=level,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        return record

    def test_emit将日志写入buffer(self):
        import app.api.v1.logs as logs_module
        handler = logs_module.SSELogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))

        old_buffer = logs_module._LOG_BUFFER.copy()
        logs_module._LOG_BUFFER.clear()
        try:
            handler.emit(self._make_record("hello log"))
            assert any("hello log" in line for line in logs_module._LOG_BUFFER)
        finally:
            logs_module._LOG_BUFFER.clear()
            logs_module._LOG_BUFFER.extend(old_buffer)

    def test_emit广播给订阅者(self):
        import app.api.v1.logs as logs_module
        handler = logs_module.SSELogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))

        q = asyncio.Queue(maxsize=10)
        logs_module._subscribers.append(q)
        try:
            handler.emit(self._make_record("broadcast message"))
            assert not q.empty()
            line = q.get_nowait()
            assert "broadcast message" in line
        finally:
            if q in logs_module._subscribers:
                logs_module._subscribers.remove(q)

    def test_emit满队列时移除死订阅(self):
        """满队列的订阅者会被自动清理"""
        import app.api.v1.logs as logs_module
        handler = logs_module.SSELogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))

        full_q = asyncio.Queue(maxsize=1)
        full_q.put_nowait("existing")  # 填满
        logs_module._subscribers.append(full_q)
        try:
            initial_len = len(logs_module._subscribers)
            handler.emit(self._make_record("overflow message"))
            # 满队列被移除
            assert full_q not in logs_module._subscribers
        finally:
            if full_q in logs_module._subscribers:
                logs_module._subscribers.remove(full_q)

    def test_install_log_handler添加到evoiceclaw_logger(self):
        from app.api.v1.logs import install_log_handler, SSELogHandler
        evoice_logger = logging.getLogger("evoiceclaw")
        # 记录安装前的 handler 数量
        before = list(evoice_logger.handlers)
        install_log_handler()
        after = list(evoice_logger.handlers)
        sse_handlers = [h for h in after if isinstance(h, SSELogHandler)]
        assert len(sse_handlers) >= 1
        # 清理安装的 handler
        for h in sse_handlers:
            evoice_logger.removeHandler(h)
        # 恢复原来的 handlers
        for h in before:
            if h not in evoice_logger.handlers:
                evoice_logger.addHandler(h)


# ─── permissions.py API ───────────────────────────────────────────────────────

class TestRespondToElevationEndpoint:

    def _make_request_obj(self, request_id="req-1", approved=False):
        req = MagicMock()
        req.request_id = request_id
        req.event = MagicMock()
        req.event.is_set.return_value = False
        return req

    @pytest.mark.asyncio
    async def test_请求不存在返回404(self):
        from app.api.v1.permissions import respond_to_elevation, ElevationResponse
        from fastapi import HTTPException
        mock_broker = MagicMock()
        mock_broker.get_request.return_value = None
        with patch("app.api.v1.permissions.get_permission_broker", return_value=mock_broker):
            with pytest.raises(HTTPException) as exc_info:
                await respond_to_elevation("no-such-req", ElevationResponse(approved=True))
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_批准成功返回已批准(self):
        from app.api.v1.permissions import respond_to_elevation, ElevationResponse
        mock_broker = MagicMock()
        mock_broker.get_request.return_value = self._make_request_obj()
        mock_broker.approve.return_value = True
        with patch("app.api.v1.permissions.get_permission_broker", return_value=mock_broker):
            result = await respond_to_elevation("req-1", ElevationResponse(approved=True))
        assert result.success is True
        assert "批准" in result.message

    @pytest.mark.asyncio
    async def test_拒绝成功返回已拒绝(self):
        from app.api.v1.permissions import respond_to_elevation, ElevationResponse
        mock_broker = MagicMock()
        mock_broker.get_request.return_value = self._make_request_obj()
        mock_broker.deny.return_value = True
        with patch("app.api.v1.permissions.get_permission_broker", return_value=mock_broker):
            result = await respond_to_elevation("req-1", ElevationResponse(approved=False))
        assert result.success is True
        assert "拒绝" in result.message

    @pytest.mark.asyncio
    async def test_处理失败返回409(self):
        from app.api.v1.permissions import respond_to_elevation, ElevationResponse
        from fastapi import HTTPException
        mock_broker = MagicMock()
        mock_broker.get_request.return_value = self._make_request_obj()
        mock_broker.approve.return_value = False  # 处理失败
        with patch("app.api.v1.permissions.get_permission_broker", return_value=mock_broker):
            with pytest.raises(HTTPException) as exc_info:
                await respond_to_elevation("req-1", ElevationResponse(approved=True))
        assert exc_info.value.status_code == 409


class TestGetElevationStatusEndpoint:

    @pytest.mark.asyncio
    async def test_请求不存在返回404(self):
        from app.api.v1.permissions import get_elevation_status
        from fastapi import HTTPException
        mock_broker = MagicMock()
        mock_broker.get_request.return_value = None
        with patch("app.api.v1.permissions.get_permission_broker", return_value=mock_broker):
            with pytest.raises(HTTPException) as exc_info:
                await get_elevation_status("no-req")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_请求存在返回状态(self):
        from app.api.v1.permissions import get_elevation_status
        mock_req = MagicMock()
        mock_req.request_id = "req-123"
        mock_req.command = "ls -la"
        mock_req.cmd_name = "ls"
        mock_req.current_level = 1
        mock_req.required_level = 2
        mock_req.approved = False
        mock_req.event = MagicMock()
        mock_req.event.is_set.return_value = False

        mock_broker = MagicMock()
        mock_broker.get_request.return_value = mock_req
        with patch("app.api.v1.permissions.get_permission_broker", return_value=mock_broker):
            result = await get_elevation_status("req-123")
        assert result["request_id"] == "req-123"
        assert result["pending"] is True
        assert result["approved"] is False


# ─── IdleMonitor ──────────────────────────────────────────────────────────────

class TestIdleMonitor:

    def test_record_activity更新last_activity_time(self):
        from app.evaluation.scheduler.idle_monitor import IdleMonitor
        monitor = IdleMonitor()
        assert monitor._last_activity_time is None
        monitor.record_activity()
        assert monitor._last_activity_time is not None

    def test_record_activity重置idle_start_time(self):
        from app.evaluation.scheduler.idle_monitor import IdleMonitor
        monitor = IdleMonitor()
        monitor._idle_start_time = datetime.now()
        monitor.record_activity()
        assert monitor._idle_start_time is None

    def test_check_user_idle首次启动时返回True(self):
        from app.evaluation.scheduler.idle_monitor import IdleMonitor
        monitor = IdleMonitor()
        assert monitor._check_user_idle() is True

    def test_check_user_idle最近有活动返回False(self):
        from app.evaluation.scheduler.idle_monitor import IdleMonitor
        monitor = IdleMonitor(idle_duration=300)
        monitor._last_activity_time = datetime.now()
        assert monitor._check_user_idle() is False

    def test_check_user_idle超过idle_duration返回True(self):
        from app.evaluation.scheduler.idle_monitor import IdleMonitor
        monitor = IdleMonitor(idle_duration=300)
        monitor._last_activity_time = datetime.now() - timedelta(seconds=400)
        assert monitor._check_user_idle() is True

    def test_is_idle_首次调用记录idle_start_time但返回False(self):
        """第一次检测到空闲只标记开始时间，不立即返回 True"""
        from app.evaluation.scheduler.idle_monitor import IdleMonitor
        monitor = IdleMonitor(idle_duration=300)
        # 模拟 CPU、内存均空闲，且用户无活动
        with patch.object(monitor, "_check_cpu_idle", return_value=True), \
             patch.object(monitor, "_check_memory_idle", return_value=True), \
             patch.object(monitor, "_check_user_idle", return_value=True):
            result = monitor.is_idle()
        # 首次设置 _idle_start_time，但尚未持续足够长，返回 False
        assert result is False
        assert monitor._idle_start_time is not None

    def test_is_idle_持续空闲后返回True(self):
        from app.evaluation.scheduler.idle_monitor import IdleMonitor
        monitor = IdleMonitor(idle_duration=300)
        # 模拟已经空闲超过 300 秒
        monitor._idle_start_time = datetime.now() - timedelta(seconds=400)
        with patch.object(monitor, "_check_cpu_idle", return_value=True), \
             patch.object(monitor, "_check_memory_idle", return_value=True), \
             patch.object(monitor, "_check_user_idle", return_value=True):
            result = monitor.is_idle()
        assert result is True

    def test_is_idle_有用户活动时重置idle_start_time(self):
        from app.evaluation.scheduler.idle_monitor import IdleMonitor
        monitor = IdleMonitor()
        monitor._idle_start_time = datetime.now() - timedelta(seconds=100)
        with patch.object(monitor, "_check_cpu_idle", return_value=True), \
             patch.object(monitor, "_check_memory_idle", return_value=True), \
             patch.object(monitor, "_check_user_idle", return_value=False):  # 有用户活动
            result = monitor.is_idle()
        assert result is False
        assert monitor._idle_start_time is None

    def test_get_idle_monitor返回同一实例(self):
        from app.evaluation.scheduler.idle_monitor import get_idle_monitor
        m1 = get_idle_monitor()
        m2 = get_idle_monitor()
        assert m1 is m2
