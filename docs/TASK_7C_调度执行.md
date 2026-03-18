# TASK 7C — 评测调度与执行

> **Phase**: 7C
> **工作量**: 中
> **依赖**: Phase 7A、7B 已完成
> **目标**: 实现评测任务调度器、空闲监控、执行器

---

## 一、任务目标

实现评测子系统的核心调度与执行逻辑：
1. 任务调度器：管理评测队列、状态转换、优先级
2. 空闲监控：检测系统空闲状态，触发评测
3. 评测执行器：调用 LiteLLM 执行题目，写入结果
4. 触发机制：新模型检测、定时全量、空闲评测

---

## 二、文件结构

```
backend/app/evaluation/
├── scheduler.py        ← 任务调度器（新建）
├── executor.py         ← 评测执行器（新建）
├── idle_monitor.py     ← 空闲监控（新建）
└── models.py           ← 已有（Phase 7A）
```

---

## 三、子任务清单

### 3.1 任务调度器

**文件**: `backend/app/evaluation/scheduler.py`

```python
"""评测任务调度器 — 管理队列、状态转换、触发检测"""

import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import List

from app.evaluation.models import EvaluationTask, EvaluationStatus, TriggerType
from app.infrastructure.db import get_connection

logger = logging.getLogger(__name__)


class EvaluationScheduler:
    """评测任务调度器

    职责：
    1. 管理评测任务队列（SQLite evaluation_queue 表）
    2. 状态转换（PENDING → QUEUED → RUNNING → COMPLETED/FAILED）
    3. 触发检测（新模型、定时、空闲）
    4. 优先级管理
    """

    def __init__(self):
        self._running = False
        self._current_task: EvaluationTask | None = None

    async def start(self):
        """启动调度器（后台任务）"""
        self._running = True
        logger.info("[Scheduler] 启动评测调度器")

        # 启动定时任务
        asyncio.create_task(self._scheduled_evaluation_loop())

    async def stop(self):
        """停止调度器"""
        self._running = False
        logger.info("[Scheduler] 停止评测调度器")

    def create_task(
        self,
        model_id: str,
        trigger: TriggerType,
        priority: int = 50
    ) -> str:
        """创建评测任务

        Args:
            model_id: 模型标识
            trigger: 触发方式
            priority: 优先级（越小越高）

        Returns:
            task_id
        """
        task_id = str(uuid.uuid4())
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO evaluation_queue
            (task_id, model_id, status, priority, trigger)
            VALUES (?, ?, ?, ?, ?)
        """, (task_id, model_id, EvaluationStatus.QUEUED.value, priority, trigger.value))

        conn.commit()
        logger.info(f"[Scheduler] 创建任务: {model_id} (优先级 {priority}, 触发: {trigger.value})")
        return task_id

    def get_next_task(self) -> EvaluationTask | None:
        """从队列取下一个待执行任务（按优先级）"""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT task_id, model_id, status, priority, trigger, retry_count,
                   created_at, started_at, completed_at, error_msg, eval_id
            FROM evaluation_queue
            WHERE status = ?
            ORDER BY priority ASC, created_at ASC
            LIMIT 1
        """, (EvaluationStatus.QUEUED.value,))

        row = cursor.fetchone()
        if not row:
            return None

        return EvaluationTask(
            task_id=row[0],
            model_id=row[1],
            status=EvaluationStatus(row[2]),
            priority=row[3],
            trigger=TriggerType(row[4]),
            retry_count=row[5],
            created_at=datetime.fromisoformat(row[6]) if row[6] else datetime.now(),
            started_at=datetime.fromisoformat(row[7]) if row[7] else None,
            completed_at=datetime.fromisoformat(row[8]) if row[8] else None,
            error_msg=row[9],
            eval_id=row[10],
        )

    def update_task_status(
        self,
        task_id: str,
        status: EvaluationStatus,
        error_msg: str | None = None,
        eval_id: str | None = None
    ):
        """更新任务状态"""
        conn = get_connection()
        cursor = conn.cursor()

        now = datetime.now().isoformat()
        if status == EvaluationStatus.RUNNING:
            cursor.execute("""
                UPDATE evaluation_queue
                SET status = ?, started_at = ?
                WHERE task_id = ?
            """, (status.value, now, task_id))
        elif status in (EvaluationStatus.COMPLETED, EvaluationStatus.FAILED):
            cursor.execute("""
                UPDATE evaluation_queue
                SET status = ?, completed_at = ?, error_msg = ?, eval_id = ?
                WHERE task_id = ?
            """, (status.value, now, error_msg, eval_id, task_id))
        else:
            cursor.execute("""
                UPDATE evaluation_queue
                SET status = ?
                WHERE task_id = ?
            """, (status.value, task_id))

        conn.commit()

    def retry_task(self, task_id: str):
        """重试失败任务"""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE evaluation_queue
            SET status = ?, retry_count = retry_count + 1, error_msg = NULL
            WHERE task_id = ?
        """, (EvaluationStatus.QUEUED.value, task_id))

        conn.commit()
        logger.info(f"[Scheduler] 任务 {task_id} 重新入队")

    async def check_new_models(self):
        """检测新模型（从 secrets.yaml 读取已配置的 provider）

        对比 evaluation_queue 中已有的模型，发现新模型则创建任务
        """
        from app.core.config import load_config

        config = load_config()
        secrets = config.get("secrets", {})

        # 获取所有已配置 API Key 的 provider
        configured_providers = [
            provider for provider, data in secrets.items()
            if data.get("api_key")
        ]

        # 从 provider 推断可用模型（简化实现，实际需调用 LiteLLM list_models）
        # 这里假设每个 provider 有默认模型
        provider_default_models = {
            "deepseek": ["deepseek/deepseek-chat", "deepseek/deepseek-reasoner"],
            "qwen": ["qwen/qwen-max", "qwen/qwen-plus", "qwen/qwen-turbo"],
            "kimi": ["kimi/moonshot-v1-128k", "kimi/kimi-k2.5"],
            "zhipu": ["zhipu/glm-5", "zhipu/glm-4-flash"],
            "baichuan": ["baichuan/Baichuan4-Air", "baichuan/Baichuan4"],
            "minimax": ["minimax/MiniMax-M2.5"],
        }

        available_models = []
        for provider in configured_providers:
            available_models.extend(provider_default_models.get(provider, []))

        # 查询已有任务的模型
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT model_id FROM evaluation_queue")
        existing_models = {row[0] for row in cursor.fetchall()}

        # 发现新模型
        new_models = set(available_models) - existing_models
        for model_id in new_models:
            self.create_task(model_id, TriggerType.AUTO_NEW_MODEL, priority=10)
            logger.info(f"[Scheduler] 检测到新模型: {model_id}")

    async def _scheduled_evaluation_loop(self):
        """定时评测循环（每月 1 号凌晨 2 点）"""
        while self._running:
            now = datetime.now()

            # 检查是否是每月 1 号凌晨 2 点
            if now.day == 1 and now.hour == 2 and now.minute < 5:
                logger.info("[Scheduler] 触发定时全量评测")
                await self._schedule_all_models()

            # 每 5 分钟检查一次
            await asyncio.sleep(300)

    async def _schedule_all_models(self):
        """为所有已启用模型创建评测任务"""
        from app.kernel.router.model_matrix import get_model_matrix

        matrix = get_model_matrix()
        all_models = matrix.get_all_models()

        for model_id in all_models:
            # 检查是否已有 QUEUED 或 RUNNING 任务
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM evaluation_queue
                WHERE model_id = ? AND status IN (?, ?)
            """, (model_id, EvaluationStatus.QUEUED.value, EvaluationStatus.RUNNING.value))

            if cursor.fetchone()[0] == 0:
                self.create_task(model_id, TriggerType.SCHEDULED, priority=50)


# 全局单例
_scheduler_instance: EvaluationScheduler | None = None


def get_scheduler() -> EvaluationScheduler:
    """获取调度器单例"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = EvaluationScheduler()
    return _scheduler_instance
```

### 3.2 空闲监控

**文件**: `backend/app/evaluation/idle_monitor.py`

```python
"""系统空闲监控 — 检测 CPU/内存/用户活动"""

import asyncio
import logging
import psutil
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class IdleMonitor:
    """系统空闲监控

    检测条件：
    1. CPU 使用率 < 20% 持续 5 分钟
    2. 可用内存 > 2GB
    3. 无用户活动（可选，桌面环境）
    """

    def __init__(self, on_idle_callback):
        self._running = False
        self._on_idle = on_idle_callback
        self._last_check = datetime.now()
        self._idle_start: datetime | None = None

    async def start(self):
        """启动监控"""
        self._running = True
        logger.info("[IdleMonitor] 启动空闲监控")
        asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """停止监控"""
        self._running = False
        logger.info("[IdleMonitor] 停止空闲监控")

    async def _monitor_loop(self):
        """监控循环（每分钟检查一次）"""
        while self._running:
            is_idle = self._check_idle()

            if is_idle:
                if self._idle_start is None:
                    self._idle_start = datetime.now()
                    logger.debug("[IdleMonitor] 系统进入空闲状态")

                # 空闲持续 5 分钟，触发回调
                idle_duration = (datetime.now() - self._idle_start).total_seconds()
                if idle_duration >= 300:  # 5 分钟
                    logger.info("[IdleMonitor] 系统空闲超过 5 分钟，触发评测")
                    await self._on_idle()
                    self._idle_start = None  # 重置，避免重复触发
            else:
                if self._idle_start is not None:
                    logger.debug("[IdleMonitor] 系统退出空闲状态")
                self._idle_start = None

            await asyncio.sleep(60)  # 每分钟检查一次

    def _check_idle(self) -> bool:
        """检查系统是否空闲"""
        # 检查 CPU 使用率
        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent > 20:
            return False

        # 检查可用内存
        mem = psutil.virtual_memory()
        if mem.available < 2 * 1024 * 1024 * 1024:  # 2GB
            return False

        # TODO: 检查用户活动（键盘/鼠标输入）
        # 需要平台相关实现，暂时跳过

        return True


async def on_idle_trigger():
    """空闲触发回调 — 从队列取任务执行"""
    from app.evaluation.scheduler import get_scheduler
    from app.evaluation.executor import get_executor

    scheduler = get_scheduler()
    executor = get_executor()

    # 检查是否有任务在运行
    if executor.is_running():
        logger.debug("[IdleMonitor] 已有评测任务在运行，跳过")
        return

    # 从队列取任务
    task = scheduler.get_next_task()
    if task:
        logger.info(f"[IdleMonitor] 开始执行评测任务: {task.model_id}")
        await executor.execute_task(task)
    else:
        logger.debug("[IdleMonitor] 队列为空，无任务执行")
```

### 3.3 评测执行器

**文件**: `backend/app/evaluation/executor.py`

```python
"""评测执行器 — 调用 LiteLLM 执行题目，写入结果"""

import asyncio
import json
import logging
import statistics
import uuid
from datetime import datetime

from app.evaluation.cases import ALL_TESTS
from app.evaluation.scoring import score_test
from app.evaluation.models import EvaluationTask, EvaluationStatus, EvaluationResult
from app.kernel.providers.api_provider import APIProvider
from app.infrastructure.vector_db import get_connection

logger = logging.getLogger(__name__)


class EvaluationExecutor:
    """评测执行器

    职责：
    1. 执行 165 道题目（11 维 × 15 题）
    2. 调用评分器
    3. 汇总维度得分
    4. 写入 LanceDB model_evaluations 表
    """

    def __init__(self):
        self._running_task: EvaluationTask | None = None

    def is_running(self) -> bool:
        """是否有任务在运行"""
        return self._running_task is not None

    async def execute_task(self, task: EvaluationTask):
        """执行评测任务"""
        from app.evaluation.scheduler import get_scheduler
        from app.core.config import load_config

        scheduler = get_scheduler()
        self._running_task = task

        try:
            # 更新状态为 RUNNING
            scheduler.update_task_status(task.task_id, EvaluationStatus.RUNNING)

            # 加载配置
            config = load_config()

            # 执行评测
            result = await self._run_evaluation(task.model_id, config)

            # 写入 LanceDB
            eval_id = await self._save_result(result)

            # 更新状态为 COMPLETED
            scheduler.update_task_status(
                task.task_id,
                EvaluationStatus.COMPLETED,
                eval_id=eval_id
            )

            logger.info(f"[Executor] ✅ 评测完成: {task.model_id}")

        except Exception as e:
            logger.error(f"[Executor] 评测失败: {task.model_id} - {e}", exc_info=True)

            # 更新状态为 FAILED
            scheduler.update_task_status(
                task.task_id,
                EvaluationStatus.FAILED,
                error_msg=str(e)
            )

            # 重试逻辑
            if task.retry_count < 3:
                scheduler.retry_task(task.task_id)

        finally:
            self._running_task = None

    async def _run_evaluation(self, model_id: str, config: dict) -> EvaluationResult:
        """运行完整评测（165 道题）"""
        provider = APIProvider(config)

        dimension_scores = {}
        dimension_latencies = {}
        dimension_tokens = {}

        for test in ALL_TESTS:
            try:
                # 调用模型
                start_time = datetime.now()
                response, tool_calls, usage = await provider.chat_completion(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": test.system_prompt or ""},
                        {"role": "user", "content": test.prompt}
                    ],
                    tools=test.tools,
                    temperature=0.0,
                )
                latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # 评分
                score, detail = await score_test(test, response, tool_calls, config)

                # 汇总到维度
                dim = test.dimension
                if dim not in dimension_scores:
                    dimension_scores[dim] = []
                    dimension_latencies[dim] = []
                    dimension_tokens[dim] = {"input": [], "output": []}

                dimension_scores[dim].append(score)
                dimension_latencies[dim].append(latency_ms)
                dimension_tokens[dim]["input"].append(usage.get("prompt_tokens", 0))
                dimension_tokens[dim]["output"].append(usage.get("completion_tokens", 0))

                logger.debug(f"[Executor] {model_id} / {test.id}: {score}/100")

                # 控制速率
                await asyncio.sleep(1)

            except Exception as e:
                logger.warning(f"[Executor] {model_id} / {test.id} 失败: {e}")
                # 失败题目记 0 分
                if test.dimension not in dimension_scores:
                    dimension_scores[test.dimension] = []
                dimension_scores[test.dimension].append(0)

        # 计算各维度平均分
        final_scores = {}
        for dim, scores in dimension_scores.items():
            final_scores[dim] = round(sum(scores) / len(scores), 1) if scores else 0

        # 计算派生维度 reasoning
        if all(d in final_scores for d in ["logic", "instruction_following", "math_reasoning"]):
            final_scores["reasoning"] = round(
                (final_scores["logic"] + final_scores["instruction_following"] + final_scores["math_reasoning"]) / 3,
                1
            )

        # 计算平均延迟
        all_latencies = [lat for lats in dimension_latencies.values() for lat in lats]
        avg_latency_ms = int(statistics.median(all_latencies)) if all_latencies else 0

        # 计算平均 tokens
        all_input_tokens = [t for tokens in dimension_tokens.values() for t in tokens["input"]]
        all_output_tokens = [t for tokens in dimension_tokens.values() for t in tokens["output"]]
        avg_input_tokens = int(sum(all_input_tokens) / len(all_input_tokens)) if all_input_tokens else 0
        avg_output_tokens = int(sum(all_output_tokens) / len(all_output_tokens)) if all_output_tokens else 0

        # 获取成本数据（从 provider 定价或配置）
        # 简化实现：从配置读取
        cost_input_per_m = config.get("providers", {}).get(model_id.split("/")[0], {}).get("cost_input_per_m", 0.0)
        cost_output_per_m = config.get("providers", {}).get(model_id.split("/")[0], {}).get("cost_output_per_m", 0.0)

        # 获取 context_window（从配置或默认 128K）
        context_window = config.get("providers", {}).get(model_id.split("/")[0], {}).get("context_window", 128000)

        return EvaluationResult(
            eval_id=str(uuid.uuid4()),
            model_id=model_id,
            timestamp=datetime.now(),
            source="evaluated",
            dimension_scores=final_scores,
            avg_latency_ms=avg_latency_ms,
            avg_input_tokens=avg_input_tokens,
            avg_output_tokens=avg_output_tokens,
            cost_input_per_m=cost_input_per_m,
            cost_output_per_m=cost_output_per_m,
            context_window=context_window,
            not_measured_dims=[],
        )

    async def _save_result(self, result: EvaluationResult) -> str:
        """保存评测结果到 LanceDB"""
        db = get_connection()
        table = db.open_table("model_evaluations")

        record = {
            "eval_id": result.eval_id,
            "model_id": result.model_id,
            "timestamp": result.timestamp,
            "source": result.source,
            "dimension_scores": json.dumps(result.dimension_scores, ensure_ascii=False),
            "avg_latency_ms": result.avg_latency_ms,
            "avg_input_tokens": result.avg_input_tokens,
            "avg_output_tokens": result.avg_output_tokens,
            "cost_input_per_m": result.cost_input_per_m,
            "cost_output_per_m": result.cost_output_per_m,
            "context_window": result.context_window,
            "benchmark_version": result.benchmark_version,
            "eval_version": result.eval_version,
            "not_measured_dims": json.dumps(result.not_measured_dims, ensure_ascii=False),
        }

        table.add([record])
        logger.info(f"[Executor] 评测结果已保存: {result.eval_id}")
        return result.eval_id


# 全局单例
_executor_instance: EvaluationExecutor | None = None


def get_executor() -> EvaluationExecutor:
    """获取执行器单例"""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = EvaluationExecutor()
    return _executor_instance
```

### 3.4 集成到 main.py

**文件**: `backend/app/main.py`（修改 lifespan）

```python
from app.evaluation.scheduler import get_scheduler
from app.evaluation.idle_monitor import IdleMonitor, on_idle_trigger

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=== eVoiceClaw Desktop v3 启动 ===")

    # ... 现有初始化

    # 启动评测调度器
    scheduler = get_scheduler()
    await scheduler.start()

    # 检测新模型
    await scheduler.check_new_models()

    # 启动空闲监控
    idle_monitor = IdleMonitor(on_idle_callback=on_idle_trigger)
    await idle_monitor.start()

    yield

    # 停止调度器和监控
    await scheduler.stop()
    await idle_monitor.stop()

    logger.info("=== eVoiceClaw Desktop v3 关闭 ===")
```

---

## 四、验证步骤

### 4.1 验证调度器

```python
# 在 Python REPL 中
from app.evaluation.scheduler import get_scheduler
from app.evaluation.models import TriggerType

scheduler = get_scheduler()

# 创建测试任务
task_id = scheduler.create_task("deepseek/deepseek-chat", TriggerType.MANUAL, priority=10)
print(f"任务已创建: {task_id}")

# 查询队列
task = scheduler.get_next_task()
print(f"下一个任务: {task.model_id if task else 'None'}")
```

### 4.2 验证执行器

```python
# 手动触发评测（测试用）
from app.evaluation.executor import get_executor
from app.evaluation.scheduler import get_scheduler

scheduler = get_scheduler()
executor = get_executor()

task = scheduler.get_next_task()
if task:
    await executor.execute_task(task)
```

### 4.3 验证空闲监控

```bash
# 启动服务，观察日志
uvicorn app.main:app --reload

# 预期日志:
# [IdleMonitor] 启动空闲监控
# [IdleMonitor] 系统进入空闲状态
# [IdleMonitor] 系统空闲超过 5 分钟，触发评测
```

---

## 五、交付清单

- [x] `backend/app/evaluation/scheduler.py`
- [x] `backend/app/evaluation/executor.py`
- [x] `backend/app/evaluation/idle_monitor.py`
- [x] `main.py` 集成启动逻辑

---

## 六、注意事项

1. **速率限制**：每道题之间间隔 1 秒，避免触发 API 限流
2. **重试机制**：失败任务最多重试 3 次
3. **空闲检测**：CPU < 20% 持续 5 分钟才触发
4. **并发控制**：同时只运行 1 个评测任务

---

## 七、下一步

完成 Phase 7C 后，进入 **Phase 7D: 规则生成**，实现规则生成器和热加载机制。
