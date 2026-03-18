"""评测任务调度器 — 队列管理 + 优先级 + 触发检测

触发机制：
1. 新模型检测：检测到 secrets.yaml 新增 API Key → 优先级 10 (高)
2. 定时全量：每月 1 号凌晨 2 点 → 优先级 50 (中)
3. 空闲评测：CPU < 20% 持续 5 分钟 + 无用户活动 → 优先级 90 (低)

状态机：PENDING → QUEUED → RUNNING → COMPLETED/FAILED
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Optional

from app.evaluation.models import EvaluationStatus, EvaluationTask, TriggerType
from app.evaluation.scheduler.executor import get_executor
from app.evaluation.scheduler.idle_monitor import get_idle_monitor
from app.infrastructure.db import get_connection

logger = logging.getLogger("evoiceclaw.evaluation.scheduler")


class EvaluationScheduler:
    """评测任务调度器"""

    def __init__(self, config: dict):
        self.config = config
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        self._executor = get_executor(config)
        self._idle_monitor = get_idle_monitor()

    def create_task(
        self,
        model_id: str,
        trigger: TriggerType,
        priority: int = 50,
    ) -> str:
        """创建评测任务

        Returns:
            task_id
        """
        task_id = str(uuid.uuid4())

        try:
            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO evaluation_queue (
                    task_id, model_id, status, priority, trigger, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    model_id,
                    EvaluationStatus.PENDING.value,
                    priority,
                    trigger.value,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

            logger.info(f"[Scheduler] 创建任务: {model_id} (task_id={task_id}, priority={priority}, trigger={trigger.value})")
            return task_id

        except Exception as e:
            logger.error(f"[Scheduler] 创建任务失败: {e}", exc_info=True)
            raise

    def get_pending_tasks(self, limit: int = 10) -> List[EvaluationTask]:
        """获取待处理任务（按优先级排序）"""
        try:
            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT task_id, model_id, status, priority, trigger, retry_count,
                       created_at, started_at, completed_at, error_msg, eval_id
                FROM evaluation_queue
                WHERE status IN (?, ?)
                ORDER BY priority ASC, created_at ASC
                LIMIT ?
                """,
                (EvaluationStatus.PENDING.value, EvaluationStatus.QUEUED.value, limit),
            )

            tasks = []
            for row in cursor.fetchall():
                task = EvaluationTask(
                    task_id=row[0],
                    model_id=row[1],
                    status=EvaluationStatus(row[2]),
                    priority=row[3],
                    trigger=TriggerType(row[4]),
                    retry_count=row[5],
                    created_at=datetime.fromisoformat(row[6]) if row[6] else None,
                    started_at=datetime.fromisoformat(row[7]) if row[7] else None,
                    completed_at=datetime.fromisoformat(row[8]) if row[8] else None,
                    error_msg=row[9],
                    eval_id=row[10],
                )
                tasks.append(task)

            return tasks

        except Exception as e:
            logger.error(f"[Scheduler] 获取待处理任务失败: {e}", exc_info=True)
            return []

    def update_task_status(self, task_id: str, status: EvaluationStatus) -> None:
        """更新任务状态"""
        try:
            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute(
                "UPDATE evaluation_queue SET status = ? WHERE task_id = ?",
                (status.value, task_id),
            )
            conn.commit()

            logger.debug(f"[Scheduler] 更新任务状态: {task_id} -> {status.value}")

        except Exception as e:
            logger.error(f"[Scheduler] 更新任务状态失败: {e}", exc_info=True)

    async def _schedule_loop(self) -> None:
        """调度循环"""
        logger.info("[Scheduler] 启动调度循环")

        while self._is_running:
            try:
                # 1. 获取待处理任务
                tasks = self.get_pending_tasks(limit=1)  # 一次只处理一个任务

                if tasks:
                    task = tasks[0]

                    # 2. 检查是否应该执行（空闲评测需要等待系统空闲）
                    if task.trigger == TriggerType.IDLE:
                        if not self._idle_monitor.is_idle():
                            logger.debug("[Scheduler] 系统未空闲，跳过空闲评测任务")
                            await asyncio.sleep(60)
                            continue

                    # 3. 更新状态为 QUEUED
                    self.update_task_status(task.task_id, EvaluationStatus.QUEUED)

                    # 4. 执行评测
                    logger.info(f"[Scheduler] 开始执行任务: {task.model_id} (task_id={task.task_id})")
                    success = await self._executor.execute_task(task)

                    if success:
                        logger.info(f"[Scheduler] 任务完成: {task.model_id}")
                    else:
                        logger.warning(f"[Scheduler] 任务失败: {task.model_id}")

                else:
                    # 无任务，等待
                    await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Scheduler] 调度循环异常: {e}", exc_info=True)
                await asyncio.sleep(60)

    def start(self) -> None:
        """启动调度器"""
        if self._is_running:
            logger.warning("[Scheduler] 调度器已在运行")
            return

        self._is_running = True
        self._task = asyncio.create_task(self._schedule_loop())
        self._idle_monitor.start()
        logger.info("[Scheduler] 调度器已启动")

    async def stop(self) -> None:
        """停止调度器"""
        if not self._is_running:
            return

        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        await self._idle_monitor.stop()
        logger.info("[Scheduler] 调度器已停止")

    def trigger_new_model_evaluation(self, model_id: str) -> str:
        """触发新模型评测（高优先级）"""
        return self.create_task(
            model_id=model_id,
            trigger=TriggerType.AUTO_NEW_MODEL,
            priority=10,
        )

    def trigger_scheduled_evaluation(self, model_id: str) -> str:
        """触发定时评测（中优先级）"""
        return self.create_task(
            model_id=model_id,
            trigger=TriggerType.SCHEDULED,
            priority=50,
        )

    def trigger_idle_evaluation(self, model_id: str) -> str:
        """触发空闲评测（低优先级）"""
        return self.create_task(
            model_id=model_id,
            trigger=TriggerType.IDLE,
            priority=90,
        )

    def cancel_task(self, task_id: str) -> bool:
        """取消正在运行的评测任务

        向执行器发出取消信号，并将状态更新为 CANCELLED。

        Returns:
            True 表示取消信号已发出，False 表示任务未在运行
        """
        # 先通过执行器发出取消信号
        cancelled = self._executor.cancel_task(task_id)
        if cancelled:
            logger.info(f"[Scheduler] 任务取消信号已发出: task_id={task_id}")
        else:
            # 任务可能在队列中未开始，直接标记 CANCELLED
            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT status FROM evaluation_queue WHERE task_id = ?",
                    (task_id,),
                )
                row = cursor.fetchone()
                if row and row[0] in (EvaluationStatus.PENDING.value, EvaluationStatus.QUEUED.value):
                    self.update_task_status(task_id, EvaluationStatus.CANCELLED)
                    logger.info(f"[Scheduler] 队列中的任务已取消: task_id={task_id}")
                    cancelled = True
            except Exception as e:
                logger.error(f"[Scheduler] 取消任务失败: {e}", exc_info=True)
        return cancelled


# ── 全局单例 ──
_scheduler_instance: Optional[EvaluationScheduler] = None


def get_scheduler(config: Optional[dict] = None) -> EvaluationScheduler:
    """获取全局 EvaluationScheduler 单例"""
    global _scheduler_instance
    if _scheduler_instance is None:
        if config is None:
            raise RuntimeError("首次调用 get_scheduler 必须提供 config")
        _scheduler_instance = EvaluationScheduler(config)
    return _scheduler_instance


def init_scheduler(config: dict) -> EvaluationScheduler:
    """初始化调度器（在 main.py 中调用）"""
    global _scheduler_instance
    _scheduler_instance = EvaluationScheduler(config)
    return _scheduler_instance
