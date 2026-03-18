"""评测系统 API 端点"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional

from app.evaluation.scheduler import get_scheduler
from app.evaluation.models import TriggerType
from app.infrastructure.db import get_connection

router = APIRouter()


class TriggerEvaluationRequest(BaseModel):
    """触发评测请求"""
    model_id: str
    reason: str = "manual"  # manual / auto_new_model / scheduled / idle


class EvaluationTaskResponse(BaseModel):
    """评测任务响应"""
    task_id: str
    model_id: str
    status: str
    priority: int
    trigger: str
    created_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    error_msg: Optional[str]
    eval_id: Optional[str]


@router.post("/trigger")
async def trigger_evaluation(req: TriggerEvaluationRequest):
    """手动触发评测"""
    try:
        scheduler = get_scheduler()

        if req.reason == "manual" or req.reason == "auto_new_model":
            task_id = scheduler.trigger_new_model_evaluation(req.model_id)
        elif req.reason == "scheduled":
            task_id = scheduler.trigger_scheduled_evaluation(req.model_id)
        elif req.reason == "idle":
            task_id = scheduler.trigger_idle_evaluation(req.model_id)
        else:
            raise HTTPException(status_code=400, detail=f"未知的 reason: {req.reason}")

        return {
            "success": True,
            "task_id": task_id,
            "message": f"已创建评测任务: {req.model_id}",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel/{task_id}")
async def cancel_evaluation(task_id: str):
    """取消正在运行或排队中的评测任务"""
    try:
        scheduler = get_scheduler()
        cancelled = scheduler.cancel_task(task_id)

        if cancelled:
            return {"success": True, "message": f"已发出取消信号: {task_id}"}
        else:
            return {"success": False, "message": "任务不在运行或队列中，无法取消"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-rules")
async def trigger_rule_generation(request: Request):
    """手动触发规则生成（内部管理用）"""
    try:
        import asyncio
        from app.evaluation.rules.rule_generator import get_rule_generator, RuleGenerator

        generator = get_rule_generator()
        if generator is None:
            config = request.app.state.config
            generator = RuleGenerator(config)

        if not generator.is_available():
            return {
                "success": False,
                "message": "无深度思维模型可用，无法生成规则",
            }

        # 异步后台执行，立即返回
        asyncio.create_task(generator.generate_rules())

        return {
            "success": True,
            "message": "规则生成任务已启动（后台执行）",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_evaluation_status():
    """查看评测状态"""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT task_id, model_id, status, priority, trigger,
                   created_at, started_at, completed_at, error_msg, eval_id
            FROM evaluation_queue
            ORDER BY created_at DESC
            LIMIT 20
            """
        )

        tasks = []
        for row in cursor.fetchall():
            tasks.append(
                EvaluationTaskResponse(
                    task_id=row[0],
                    model_id=row[1],
                    status=row[2],
                    priority=row[3],
                    trigger=row[4],
                    created_at=row[5],
                    started_at=row[6],
                    completed_at=row[7],
                    error_msg=row[8],
                    eval_id=row[9],
                )
            )

        return {
            "success": True,
            "tasks": tasks,
            "total": len(tasks),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task/{task_id}")
async def get_task_detail(task_id: str):
    """查看单个任务详情"""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT task_id, model_id, status, priority, trigger,
                   created_at, started_at, completed_at, error_msg, eval_id
            FROM evaluation_queue
            WHERE task_id = ?
            """,
            (task_id,),
        )

        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")

        return {
            "success": True,
            "task": EvaluationTaskResponse(
                task_id=row[0],
                model_id=row[1],
                status=row[2],
                priority=row[3],
                trigger=row[4],
                created_at=row[5],
                started_at=row[6],
                completed_at=row[7],
                error_msg=row[8],
                eval_id=row[9],
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
