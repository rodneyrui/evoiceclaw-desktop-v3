"""评测执行器 — 调用 LLM 跑题并评分

工作流程：
1. 从 evaluation_queue 获取 QUEUED 任务
2. 遍历 ALL_TESTS (155 题)，每题后检查取消信号
3. 调用 LLM (复用 APIProvider)
4. 评分 (复用 scoring/)
5. 汇总维度得分
6. 写入 LanceDB model_evaluations
7. 更新 SQLite 状态

取消机制：
- cancel_task(task_id) 设置 asyncio.Event 取消信号
- 每道题完成后检查信号，立即中止并更新状态为 CANCELLED
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from app.evaluation.cases import ALL_TESTS, DIMENSIONS
from app.evaluation.scoring import score_test
from app.evaluation.models import EvaluationStatus, EvaluationTask
from app.infrastructure.vector_db import get_db
from app.infrastructure.db import get_connection

logger = logging.getLogger("evoiceclaw.evaluation.executor")


class EvaluationExecutor:
    """评测执行器"""

    def __init__(self, config: dict):
        self.config = config
        # task_id → asyncio.Event，用于取消信号
        self._cancel_events: Dict[str, asyncio.Event] = {}

    def cancel_task(self, task_id: str) -> bool:
        """向正在运行的任务发出取消信号

        Returns:
            True 表示任务找到并已发出信号，False 表示任务不在运行
        """
        event = self._cancel_events.get(task_id)
        if event is not None:
            event.set()
            logger.info(f"[Executor] 已发出取消信号: task_id={task_id}")
            return True
        return False

    async def execute_task(self, task: EvaluationTask) -> bool:
        """执行单个评测任务

        Returns:
            True 表示成功，False 表示失败或取消
        """
        logger.info(f"[Executor] 开始评测: {task.model_id} (task_id={task.task_id})")

        # 注册取消 Event
        cancel_event = asyncio.Event()
        self._cancel_events[task.task_id] = cancel_event

        try:
            # 1. 更新状态为 RUNNING
            self._update_task_status(
                task.task_id,
                EvaluationStatus.RUNNING,
                started_at=datetime.now(),
            )

            # 2. 执行评测（带取消支持）
            dimension_scores, avg_latency = await self._run_evaluation(
                task.model_id, cancel_event
            )

            # 3. 写入 LanceDB
            eval_id = f"eval_{task.model_id.replace('/', '_')}_{uuid.uuid4().hex[:8]}"
            self._write_to_lancedb(
                eval_id=eval_id,
                model_id=task.model_id,
                dimension_scores=dimension_scores,
                avg_latency_ms=avg_latency,
            )

            # 4. 更新状态为 COMPLETED
            self._update_task_status(
                task.task_id,
                EvaluationStatus.COMPLETED,
                completed_at=datetime.now(),
                eval_id=eval_id,
            )

            logger.info(f"[Executor] 评测完成: {task.model_id} (eval_id={eval_id})")
            return True

        except asyncio.CancelledError:
            logger.info(f"[Executor] 评测已取消: {task.model_id}")
            self._update_task_status(
                task.task_id,
                EvaluationStatus.CANCELLED,
                completed_at=datetime.now(),
                error_msg="用户取消",
            )
            return False

        except Exception as e:
            logger.error(f"[Executor] 评测失败: {task.model_id}, 错误: {e}", exc_info=True)
            self._update_task_status(
                task.task_id,
                EvaluationStatus.FAILED,
                completed_at=datetime.now(),
                error_msg=str(e),
            )
            return False

        finally:
            # 清理取消 Event
            self._cancel_events.pop(task.task_id, None)

    async def _run_evaluation(
        self, model_id: str, cancel_event: asyncio.Event
    ) -> tuple[Dict[str, float], int]:
        """运行评测，返回 (dimension_scores, avg_latency_ms)

        每道题完成后检查 cancel_event，若被设置则抛出 CancelledError。
        """
        from app.kernel.providers.api_provider import APIProvider
        from app.domain.models import ChatMessage

        provider = APIProvider()

        dimension_results: Dict[str, List[int]] = {dim: [] for dim in DIMENSIONS}
        total_latency = 0
        total_tests = 0

        logger.info(f"[Executor] 开始跑题: {model_id}, 共 {len(ALL_TESTS)} 题")

        for i, test in enumerate(ALL_TESTS):
            # ── 取消检查 ──
            if cancel_event.is_set():
                logger.info(f"[Executor] 检测到取消信号，中止于第 {i+1} 题 (共 {len(ALL_TESTS)} 题)")
                raise asyncio.CancelledError(f"评测被取消: {model_id}")

            try:
                messages = [ChatMessage(role="user", content=test.prompt)]

                start_time = datetime.now()
                response_text = ""
                tool_calls = []

                async for chunk in provider.stream(
                    messages=messages,
                    model_id=model_id,
                    config=self.config,
                    tools=None,
                ):
                    if chunk.type == "text":
                        response_text += chunk.content or ""
                    elif chunk.type == "tool_call":
                        tool_calls.append(chunk)
                    elif chunk.type == "error":
                        raise RuntimeError(f"模型返回错误: {chunk.content}")

                elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                total_latency += elapsed_ms
                total_tests += 1

                score, detail = await score_test(
                    test=test,
                    response=response_text,
                    tool_calls=tool_calls if tool_calls else None,
                    config=self.config,
                )
                dimension_results[test.dimension].append(score)

                if (i + 1) % 10 == 0:
                    logger.info(
                        f"[Executor] 进度: {i+1}/{len(ALL_TESTS)}, "
                        f"平均延迟: {total_latency // total_tests}ms"
                    )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[Executor] 题目 {i+1} 失败: {e}")
                dimension_results[test.dimension].append(0)

        # 计算每个维度的平均分
        dimension_scores = {}
        for dim in DIMENSIONS:
            scores = dimension_results[dim]
            dimension_scores[dim] = sum(scores) / len(scores) if scores else 0.0

        # 派生维度 reasoning = (logic + instruction_following + math_reasoning) / 3
        dimension_scores["reasoning"] = (
            dimension_scores.get("logic", 0)
            + dimension_scores.get("instruction_following", 0)
            + dimension_scores.get("math_reasoning", 0)
        ) / 3

        avg_latency = total_latency // total_tests if total_tests > 0 else 0

        logger.info(f"[Executor] 评测完成: {model_id}, 平均延迟: {avg_latency}ms")
        logger.info(f"[Executor] 维度得分: {dimension_scores}")

        return dimension_scores, avg_latency

    def _write_to_lancedb(
        self,
        eval_id: str,
        model_id: str,
        dimension_scores: Dict[str, float],
        avg_latency_ms: int,
    ) -> None:
        """写入 LanceDB model_evaluations 表"""
        try:
            db = get_db()
            table = db.open_table("model_evaluations")

            # 从现有模型数据中获取成本信息
            existing = None
            try:
                results = table.search().where(f"model_id = '{model_id}'").limit(1).to_list()
                if results:
                    existing = results[0]
            except Exception as e:
                logger.debug("[Executor] 查询现有评测数据失败: %s", e)

            now_ms = int(datetime.now().timestamp() * 1000)

            record = {
                "eval_id": eval_id,
                "model_id": model_id,
                "timestamp": now_ms,
                "source": "evaluated",
                "dimension_scores": json.dumps(dimension_scores, ensure_ascii=False),
                "avg_latency_ms": avg_latency_ms,
                "avg_input_tokens": 0,
                "avg_output_tokens": 0,
                "cost_input_per_m": existing["cost_input_per_m"] if existing else 0.0,
                "cost_output_per_m": existing["cost_output_per_m"] if existing else 0.0,
                "context_window": existing["context_window"] if existing else 128000,
                "benchmark_version": "2.0",
                "eval_version": "1.0",
                "not_measured_dims": json.dumps([], ensure_ascii=False),
            }

            table.add([record])
            logger.info(f"[Executor] 写入 LanceDB: {eval_id}")

        except Exception as e:
            logger.error(f"[Executor] 写入 LanceDB 失败: {e}", exc_info=True)
            raise

    def _update_task_status(
        self,
        task_id: str,
        status: EvaluationStatus,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error_msg: Optional[str] = None,
        eval_id: Optional[str] = None,
    ) -> None:
        """更新 SQLite evaluation_queue 表状态"""
        try:
            conn = get_connection()
            cursor = conn.cursor()

            updates = ["status = ?"]
            params = [status.value]

            if started_at:
                updates.append("started_at = ?")
                params.append(started_at.isoformat())

            if completed_at:
                updates.append("completed_at = ?")
                params.append(completed_at.isoformat())

            if error_msg:
                updates.append("error_msg = ?")
                params.append(error_msg)

            if eval_id:
                updates.append("eval_id = ?")
                params.append(eval_id)

            params.append(task_id)

            sql = f"UPDATE evaluation_queue SET {', '.join(updates)} WHERE task_id = ?"
            cursor.execute(sql, params)
            conn.commit()

            logger.debug(f"[Executor] 更新任务状态: {task_id} -> {status.value}")

        except Exception as e:
            logger.error(f"[Executor] 更新任务状态失败: {e}", exc_info=True)
            raise


# ── 全局单例 ──
_executor_instance: Optional[EvaluationExecutor] = None


def get_executor(config: dict) -> EvaluationExecutor:
    """获取全局 EvaluationExecutor 单例"""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = EvaluationExecutor(config)
    return _executor_instance
