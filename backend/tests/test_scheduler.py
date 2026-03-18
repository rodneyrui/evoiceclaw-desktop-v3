"""EvaluationExecutor 与 EvaluationScheduler 单元测试

覆盖：
- EvaluationExecutor: cancel_task、execute_task（成功/取消/异常）、
                      _update_task_status、_write_to_lancedb、get_executor 单例
- EvaluationScheduler: create_task、get_pending_tasks、update_task_status、
                       trigger_*_evaluation 优先级、cancel_task（运行中/队列中/不存在）、
                       get_scheduler/init_scheduler 单例
"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.evaluation.models import EvaluationStatus, EvaluationTask, TriggerType


# ─── 辅助构建 ─────────────────────────────────────────────────────────────────

def _make_task(
    task_id: str = "t-001",
    model_id: str = "deepseek/deepseek-chat",
    status: EvaluationStatus = EvaluationStatus.PENDING,
    priority: int = 10,
    trigger: TriggerType = TriggerType.AUTO_NEW_MODEL,
) -> EvaluationTask:
    return EvaluationTask(
        task_id=task_id,
        model_id=model_id,
        status=status,
        priority=priority,
        trigger=trigger,
        retry_count=0,
        created_at=datetime.now(),
    )


def _make_scheduler(mock_executor=None, mock_monitor=None):
    """构建 EvaluationScheduler，依赖均 mock"""
    from app.evaluation.scheduler.scheduler import EvaluationScheduler
    if mock_executor is None:
        mock_executor = MagicMock()
    if mock_monitor is None:
        mock_monitor = MagicMock()
    with patch("app.evaluation.scheduler.scheduler.get_executor", return_value=mock_executor), \
         patch("app.evaluation.scheduler.scheduler.get_idle_monitor", return_value=mock_monitor):
        sched = EvaluationScheduler(config={})
    return sched, mock_executor, mock_monitor


# ─── EvaluationExecutor.cancel_task ──────────────────────────────────────────

class TestEvaluationExecutorCancelTask:

    def test_运行中任务返回True并设置事件(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        event = asyncio.Event()
        executor._cancel_events["t-001"] = event

        result = executor.cancel_task("t-001")

        assert result is True
        assert event.is_set()

    def test_不存在的任务返回False(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})

        result = executor.cancel_task("nonexistent")

        assert result is False

    def test_取消后事件仍保留在字典中直到任务结束(self):
        """cancel_task 只设置事件，不从字典里删除——字典清理由 execute_task finally 完成"""
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        event = asyncio.Event()
        executor._cancel_events["t-running"] = event

        executor.cancel_task("t-running")

        assert "t-running" in executor._cancel_events


# ─── EvaluationExecutor.execute_task ─────────────────────────────────────────

class TestEvaluationExecutorExecuteTask:

    @pytest.mark.asyncio
    async def test_成功路径返回True并更新COMPLETED(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        task = _make_task()

        mock_scores = {"coding": 85.0, "logic": 70.0}
        mock_latency = 400

        with patch.object(executor, "_run_evaluation", AsyncMock(return_value=(mock_scores, mock_latency))), \
             patch.object(executor, "_update_task_status") as mock_update, \
             patch.object(executor, "_write_to_lancedb") as mock_write:
            result = await executor.execute_task(task)

        assert result is True
        # 两次状态更新：RUNNING → COMPLETED
        assert mock_update.call_count == 2
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert statuses[0] == EvaluationStatus.RUNNING
        assert statuses[1] == EvaluationStatus.COMPLETED
        mock_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_CancelledError路径返回False并更新CANCELLED(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        task = _make_task(task_id="t-cancel")

        with patch.object(executor, "_run_evaluation", AsyncMock(side_effect=asyncio.CancelledError())), \
             patch.object(executor, "_update_task_status") as mock_update, \
             patch.object(executor, "_write_to_lancedb"):
            result = await executor.execute_task(task)

        assert result is False
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert EvaluationStatus.CANCELLED in statuses

    @pytest.mark.asyncio
    async def test_异常路径返回False并更新FAILED(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        task = _make_task(task_id="t-fail")

        with patch.object(executor, "_run_evaluation", AsyncMock(side_effect=RuntimeError("LLM 不可用"))), \
             patch.object(executor, "_update_task_status") as mock_update, \
             patch.object(executor, "_write_to_lancedb"):
            result = await executor.execute_task(task)

        assert result is False
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert EvaluationStatus.FAILED in statuses

    @pytest.mark.asyncio
    async def test_任务结束后cancel_event从字典清除(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        task = _make_task(task_id="t-cleanup")

        with patch.object(executor, "_run_evaluation", AsyncMock(return_value=({"coding": 80.0}, 300))), \
             patch.object(executor, "_update_task_status"), \
             patch.object(executor, "_write_to_lancedb"):
            await executor.execute_task(task)

        assert "t-cleanup" not in executor._cancel_events

    @pytest.mark.asyncio
    async def test_异常时cancel_event也被清除(self):
        """finally 块无论成功/失败都清理 cancel_event"""
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        task = _make_task(task_id="t-err-cleanup")

        with patch.object(executor, "_run_evaluation", AsyncMock(side_effect=RuntimeError("err"))), \
             patch.object(executor, "_update_task_status"), \
             patch.object(executor, "_write_to_lancedb"):
            await executor.execute_task(task)

        assert "t-err-cleanup" not in executor._cancel_events


# ─── EvaluationExecutor._update_task_status ──────────────────────────────────

class TestEvaluationExecutorUpdateTaskStatus:

    def _mock_conn(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn, mock_cursor

    def test_执行UPDATE_SQL并提交(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        mock_conn, mock_cursor = self._mock_conn()

        with patch("app.evaluation.scheduler.executor.get_connection", return_value=mock_conn):
            executor._update_task_status("t-001", EvaluationStatus.RUNNING)

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "UPDATE evaluation_queue" in sql
        assert "status = ?" in sql
        mock_conn.commit.assert_called_once()

    def test_可选字段started_at写入SQL(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        mock_conn, mock_cursor = self._mock_conn()

        with patch("app.evaluation.scheduler.executor.get_connection", return_value=mock_conn):
            executor._update_task_status(
                "t-001", EvaluationStatus.RUNNING, started_at=datetime.now()
            )

        sql = mock_cursor.execute.call_args[0][0]
        assert "started_at = ?" in sql

    def test_可选字段eval_id写入SQL(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        mock_conn, mock_cursor = self._mock_conn()

        with patch("app.evaluation.scheduler.executor.get_connection", return_value=mock_conn):
            executor._update_task_status(
                "t-001", EvaluationStatus.COMPLETED, eval_id="eval-abc"
            )

        sql = mock_cursor.execute.call_args[0][0]
        assert "eval_id = ?" in sql

    def test_DB异常向上抛出(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})

        with patch("app.evaluation.scheduler.executor.get_connection", side_effect=RuntimeError("DB down")):
            with pytest.raises(RuntimeError, match="DB down"):
                executor._update_task_status("t-001", EvaluationStatus.RUNNING)


# ─── EvaluationExecutor._write_to_lancedb ────────────────────────────────────

class TestEvaluationExecutorWriteToLanceDB:

    def _mock_db(self, existing_row=None):
        mock_db = MagicMock()
        mock_table = MagicMock()
        mock_db.open_table.return_value = mock_table
        search_chain = mock_table.search.return_value.where.return_value.limit.return_value
        search_chain.to_list.return_value = [existing_row] if existing_row else []
        return mock_db, mock_table

    def test_写入基本记录到model_evaluations(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        mock_db, mock_table = self._mock_db()

        with patch("app.evaluation.scheduler.executor.get_db", return_value=mock_db):
            executor._write_to_lancedb(
                eval_id="eval-001",
                model_id="deepseek/chat",
                dimension_scores={"coding": 80.0},
                avg_latency_ms=500,
            )

        mock_db.open_table.assert_called_once_with("model_evaluations")
        mock_table.add.assert_called_once()
        record = mock_table.add.call_args[0][0][0]
        assert record["eval_id"] == "eval-001"
        assert record["model_id"] == "deepseek/chat"
        assert record["avg_latency_ms"] == 500
        assert record["source"] == "evaluated"

    def test_无现有记录时成本字段默认为零(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        mock_db, mock_table = self._mock_db(existing_row=None)

        with patch("app.evaluation.scheduler.executor.get_db", return_value=mock_db):
            executor._write_to_lancedb("eval-002", "model-x", {}, 100)

        record = mock_table.add.call_args[0][0][0]
        assert record["cost_input_per_m"] == 0.0
        assert record["cost_output_per_m"] == 0.0
        assert record["context_window"] == 128000

    def test_有现有记录时复用成本信息(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})
        existing = {
            "cost_input_per_m": 1.5,
            "cost_output_per_m": 3.0,
            "context_window": 200000,
        }
        mock_db, mock_table = self._mock_db(existing_row=existing)

        with patch("app.evaluation.scheduler.executor.get_db", return_value=mock_db):
            executor._write_to_lancedb("eval-003", "model-y", {}, 200)

        record = mock_table.add.call_args[0][0][0]
        assert record["cost_input_per_m"] == 1.5
        assert record["cost_output_per_m"] == 3.0
        assert record["context_window"] == 200000

    def test_LanceDB异常向上抛出(self):
        from app.evaluation.scheduler.executor import EvaluationExecutor
        executor = EvaluationExecutor(config={})

        with patch("app.evaluation.scheduler.executor.get_db", side_effect=RuntimeError("LanceDB down")):
            with pytest.raises(RuntimeError, match="LanceDB down"):
                executor._write_to_lancedb("eval-004", "model-z", {}, 0)


# ─── get_executor 单例 ────────────────────────────────────────────────────────

class TestGetExecutorSingleton:

    def setup_method(self):
        import app.evaluation.scheduler.executor as m
        m._executor_instance = None

    def teardown_method(self):
        import app.evaluation.scheduler.executor as m
        m._executor_instance = None

    def test_首次调用创建实例(self):
        from app.evaluation.scheduler.executor import get_executor
        e = get_executor({"key": "val"})
        assert e is not None

    def test_重复调用返回同一实例(self):
        from app.evaluation.scheduler.executor import get_executor
        e1 = get_executor({"k": "v1"})
        e2 = get_executor({"k": "v2"})  # 不同 config，仍返回同一个实例
        assert e1 is e2


# ─── EvaluationScheduler.create_task ─────────────────────────────────────────

class TestEvaluationSchedulerCreateTask:

    def _mock_conn(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn, mock_cursor

    def test_插入DB并返回task_id(self):
        sched, _, _ = _make_scheduler()
        mock_conn, mock_cursor = self._mock_conn()

        with patch("app.evaluation.scheduler.scheduler.get_connection", return_value=mock_conn):
            task_id = sched.create_task("model-a", TriggerType.AUTO_NEW_MODEL, priority=10)

        assert task_id  # 非空
        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO evaluation_queue" in sql
        mock_conn.commit.assert_called_once()

    def test_返回的task_id为uuid格式(self):
        import uuid
        sched, _, _ = _make_scheduler()
        mock_conn, mock_cursor = self._mock_conn()

        with patch("app.evaluation.scheduler.scheduler.get_connection", return_value=mock_conn):
            task_id = sched.create_task("model-a", TriggerType.SCHEDULED, priority=50)

        # 验证是合法 UUID
        uuid.UUID(task_id)  # 不抛异常即为合法

    def test_DB异常向上抛出(self):
        sched, _, _ = _make_scheduler()

        with patch("app.evaluation.scheduler.scheduler.get_connection", side_effect=RuntimeError("DB error")):
            with pytest.raises(RuntimeError, match="DB error"):
                sched.create_task("model-a", TriggerType.MANUAL)


# ─── EvaluationScheduler.get_pending_tasks ───────────────────────────────────

class TestEvaluationSchedulerGetPendingTasks:

    def test_返回EvaluationTask列表(self):
        sched, _, _ = _make_scheduler()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("t1", "model-a", "pending", 10, "auto_new_model", 0,
             "2026-01-01T00:00:00", None, None, None, None),
        ]
        mock_conn.cursor.return_value = mock_cursor

        with patch("app.evaluation.scheduler.scheduler.get_connection", return_value=mock_conn):
            tasks = sched.get_pending_tasks()

        assert len(tasks) == 1
        assert tasks[0].task_id == "t1"
        assert tasks[0].model_id == "model-a"
        assert tasks[0].priority == 10
        assert tasks[0].status == EvaluationStatus.PENDING
        assert tasks[0].trigger == TriggerType.AUTO_NEW_MODEL

    def test_无任务时返回空列表(self):
        sched, _, _ = _make_scheduler()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor

        with patch("app.evaluation.scheduler.scheduler.get_connection", return_value=mock_conn):
            tasks = sched.get_pending_tasks()

        assert tasks == []

    def test_DB异常返回空列表不抛出(self):
        sched, _, _ = _make_scheduler()

        with patch("app.evaluation.scheduler.scheduler.get_connection", side_effect=RuntimeError("DB error")):
            tasks = sched.get_pending_tasks()

        assert tasks == []


# ─── EvaluationScheduler.update_task_status ──────────────────────────────────

class TestEvaluationSchedulerUpdateTaskStatus:

    def test_执行UPDATE_SQL并提交(self):
        sched, _, _ = _make_scheduler()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("app.evaluation.scheduler.scheduler.get_connection", return_value=mock_conn):
            sched.update_task_status("t-001", EvaluationStatus.QUEUED)

        mock_cursor.execute.assert_called_once()
        sql, params = mock_cursor.execute.call_args[0]
        assert "UPDATE evaluation_queue" in sql
        assert params[0] == EvaluationStatus.QUEUED.value
        assert params[1] == "t-001"
        mock_conn.commit.assert_called_once()

    def test_DB异常不向上抛出(self):
        """update_task_status 捕获异常不重新抛出（只打 error 日志）"""
        sched, _, _ = _make_scheduler()

        with patch("app.evaluation.scheduler.scheduler.get_connection", side_effect=RuntimeError("DB error")):
            # 不应抛出异常
            sched.update_task_status("t-001", EvaluationStatus.CANCELLED)


# ─── EvaluationScheduler 触发方法优先级 ──────────────────────────────────────

class TestEvaluationSchedulerTriggers:

    def test_trigger_new_model_使用优先级10和AUTO_NEW_MODEL(self):
        sched, _, _ = _make_scheduler()

        with patch.object(sched, "create_task", return_value="task-new") as mock_create:
            task_id = sched.trigger_new_model_evaluation("model-x")

        assert task_id == "task-new"
        mock_create.assert_called_once_with(
            model_id="model-x",
            trigger=TriggerType.AUTO_NEW_MODEL,
            priority=10,
        )

    def test_trigger_scheduled_使用优先级50和SCHEDULED(self):
        sched, _, _ = _make_scheduler()

        with patch.object(sched, "create_task", return_value="task-sched") as mock_create:
            task_id = sched.trigger_scheduled_evaluation("model-y")

        assert task_id == "task-sched"
        mock_create.assert_called_once_with(
            model_id="model-y",
            trigger=TriggerType.SCHEDULED,
            priority=50,
        )

    def test_trigger_idle_使用优先级90和IDLE(self):
        sched, _, _ = _make_scheduler()

        with patch.object(sched, "create_task", return_value="task-idle") as mock_create:
            task_id = sched.trigger_idle_evaluation("model-z")

        assert task_id == "task-idle"
        mock_create.assert_called_once_with(
            model_id="model-z",
            trigger=TriggerType.IDLE,
            priority=90,
        )


# ─── EvaluationScheduler.cancel_task ─────────────────────────────────────────

class TestEvaluationSchedulerCancelTask:

    def test_运行中任务通过executor取消返回True(self):
        mock_executor = MagicMock()
        mock_executor.cancel_task.return_value = True
        sched, _, _ = _make_scheduler(mock_executor=mock_executor)

        result = sched.cancel_task("t-running")

        assert result is True
        mock_executor.cancel_task.assert_called_once_with("t-running")

    def test_PENDING状态任务通过DB取消返回True(self):
        mock_executor = MagicMock()
        mock_executor.cancel_task.return_value = False  # 执行器没有这个任务
        sched, _, _ = _make_scheduler(mock_executor=mock_executor)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (EvaluationStatus.PENDING.value,)
        mock_conn.cursor.return_value = mock_cursor

        with patch("app.evaluation.scheduler.scheduler.get_connection", return_value=mock_conn), \
             patch.object(sched, "update_task_status") as mock_update:
            result = sched.cancel_task("t-pending")

        assert result is True
        mock_update.assert_called_once_with("t-pending", EvaluationStatus.CANCELLED)

    def test_QUEUED状态任务通过DB取消返回True(self):
        mock_executor = MagicMock()
        mock_executor.cancel_task.return_value = False
        sched, _, _ = _make_scheduler(mock_executor=mock_executor)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (EvaluationStatus.QUEUED.value,)
        mock_conn.cursor.return_value = mock_cursor

        with patch("app.evaluation.scheduler.scheduler.get_connection", return_value=mock_conn), \
             patch.object(sched, "update_task_status") as mock_update:
            result = sched.cancel_task("t-queued")

        assert result is True
        mock_update.assert_called_once_with("t-queued", EvaluationStatus.CANCELLED)

    def test_RUNNING状态在DB中但executor未找到不取消(self):
        """任务状态为 RUNNING 但 executor 没有其 cancel_event，说明刚完成，不应取消"""
        mock_executor = MagicMock()
        mock_executor.cancel_task.return_value = False
        sched, _, _ = _make_scheduler(mock_executor=mock_executor)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (EvaluationStatus.RUNNING.value,)
        mock_conn.cursor.return_value = mock_cursor

        with patch("app.evaluation.scheduler.scheduler.get_connection", return_value=mock_conn), \
             patch.object(sched, "update_task_status") as mock_update:
            result = sched.cancel_task("t-running-noevent")

        assert result is False
        mock_update.assert_not_called()

    def test_任务不存在返回False(self):
        mock_executor = MagicMock()
        mock_executor.cancel_task.return_value = False
        sched, _, _ = _make_scheduler(mock_executor=mock_executor)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # 不存在
        mock_conn.cursor.return_value = mock_cursor

        with patch("app.evaluation.scheduler.scheduler.get_connection", return_value=mock_conn):
            result = sched.cancel_task("t-nonexistent")

        assert result is False


# ─── get_scheduler / init_scheduler 单例 ─────────────────────────────────────

class TestSchedulerSingleton:

    def setup_method(self):
        import app.evaluation.scheduler.scheduler as m
        m._scheduler_instance = None

    def teardown_method(self):
        import app.evaluation.scheduler.scheduler as m
        m._scheduler_instance = None

    def test_get_scheduler_首次调用无config抛RuntimeError(self):
        from app.evaluation.scheduler.scheduler import get_scheduler
        with pytest.raises(RuntimeError, match="首次调用"):
            get_scheduler()

    def test_get_scheduler_有实例后无需config(self):
        with patch("app.evaluation.scheduler.scheduler.get_executor", return_value=MagicMock()), \
             patch("app.evaluation.scheduler.scheduler.get_idle_monitor", return_value=MagicMock()):
            from app.evaluation.scheduler.scheduler import get_scheduler
            s1 = get_scheduler({"key": "val"})
            s2 = get_scheduler()  # 不传 config
        assert s1 is s2

    def test_init_scheduler_每次创建新实例(self):
        with patch("app.evaluation.scheduler.scheduler.get_executor", return_value=MagicMock()), \
             patch("app.evaluation.scheduler.scheduler.get_idle_monitor", return_value=MagicMock()):
            from app.evaluation.scheduler.scheduler import init_scheduler
            s1 = init_scheduler({"k": "v1"})
            s2 = init_scheduler({"k": "v2"})
        # init_scheduler 每次都创建新实例并覆盖单例
        assert s1 is not s2
