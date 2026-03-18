"""守门员主逻辑：调用审查 LLM 改写 SKILL.md + 生成 ACTIONS

调用流程：
1. 加载 V5 System Prompt
2. 将原始 SKILL.md 作为 user message 发送给审查 LLM
3. 收集完整回复并解析 JSON
4. 返回 ReviewResult（含 status、改写内容、actions 列表）
"""

import json
import logging
import re
import time

from app.domain.models import ChatMessage
from app.kernel.router.llm_router import get_router, collect_stream_text
from app.security.audit import log_event, new_trace_id, LEVEL_INFO, LEVEL_WARN
from app.security.gatekeeper.models import ReviewResult, ActionDeclaration
from app.security.gatekeeper.prompt import load_gatekeeper_prompt

logger = logging.getLogger("evoiceclaw.security.gatekeeper")

# 默认审查模型（可在 config.yaml 的 gatekeeper.model 中覆盖）
_DEFAULT_GATEKEEPER_MODEL = "deepseek/deepseek-chat"


async def review_skill(skill_md_content: str, config: dict) -> ReviewResult:
    """审查一个 SKILL.md

    Args:
        skill_md_content: 原始 SKILL.md 文本
        config: 全局配置

    Returns:
        ReviewResult 审查结果
    """
    trace_id = new_trace_id()
    start_ms = int(time.monotonic() * 1000)

    # 确定审查模型
    gatekeeper_cfg = config.get("gatekeeper", {})
    model_id = gatekeeper_cfg.get("model", _DEFAULT_GATEKEEPER_MODEL)

    log_event(
        component="gatekeeper",
        action="REVIEW_START",
        trace_id=trace_id,
        detail=f"model={model_id}, md_len={len(skill_md_content)}",
    )

    # 加载 System Prompt
    system_prompt = load_gatekeeper_prompt()

    # 构建消息
    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=f"请审查以下 SKILL.md：\n\n{skill_md_content}"),
    ]

    # 调用 LLM
    try:
        router = get_router()
        raw_response = await collect_stream_text(
            router, messages, model_id, config,
        )
    except Exception as e:
        elapsed = int(time.monotonic() * 1000) - start_ms
        log_event(
            component="gatekeeper",
            action="REVIEW_ERROR",
            trace_id=trace_id,
            detail=f"LLM 调用失败: {e}",
            level=LEVEL_WARN,
            duration_ms=elapsed,
        )
        # LLM 调用失败时，保守处理：拒绝
        return ReviewResult(
            status="rejected",
            safety_report=f"守门员 LLM 调用失败: {e}",
            model_used=model_id,
            duration_ms=elapsed,
        )

    elapsed = int(time.monotonic() * 1000) - start_ms

    # 解析 LLM 响应
    result = _parse_review_response(raw_response, model_id, elapsed)

    log_event(
        component="gatekeeper",
        action="REVIEW_DONE",
        trace_id=trace_id,
        detail=f"status={result.status}, actions={len(result.actions)}, report_len={len(result.safety_report)}",
        duration_ms=elapsed,
    )

    return result


def _parse_review_response(raw: str, model_id: str, elapsed_ms: int) -> ReviewResult:
    """解析守门员 LLM 的 JSON 响应

    支持两种格式：
    1. 纯 JSON
    2. Markdown 代码块包裹的 JSON
    """
    # 尝试从 markdown 代码块中提取 JSON
    json_str = raw.strip()
    code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)```", json_str, re.DOTALL)
    if code_block_match:
        json_str = code_block_match.group(1).strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # 尝试找到第一个 { 和最后一个 } 之间的内容
        brace_start = json_str.find("{")
        brace_end = json_str.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                data = json.loads(json_str[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                logger.warning("[守门员] JSON 解析失败，保守拒绝")
                return ReviewResult(
                    status="rejected",
                    safety_report=f"守门员响应无法解析为 JSON:\n{raw[:500]}",
                    model_used=model_id,
                    duration_ms=elapsed_ms,
                )
        else:
            logger.warning("[守门员] 响应中未找到 JSON 结构")
            return ReviewResult(
                status="rejected",
                safety_report=f"守门员响应中未找到 JSON 结构:\n{raw[:500]}",
                model_used=model_id,
                duration_ms=elapsed_ms,
            )

    # 提取字段
    status = data.get("status", "rejected")
    if status not in ("approved", "rejected", "rewritten"):
        status = "rejected"

    safety_report = data.get("safety_report", "")
    rewritten_content = data.get("rewritten_content") if status == "rewritten" else None

    # 解析 actions
    actions: list[ActionDeclaration] = []
    raw_actions = data.get("actions", [])
    if isinstance(raw_actions, list):
        for a in raw_actions:
            if isinstance(a, dict) and a.get("command"):
                actions.append(ActionDeclaration(
                    command=a["command"],
                    pattern=a.get("pattern", ""),
                    description=a.get("description", ""),
                ))

    return ReviewResult(
        status=status,
        safety_report=safety_report,
        rewritten_content=rewritten_content,
        actions=actions,
        model_used=model_id,
        duration_ms=elapsed_ms,
    )
