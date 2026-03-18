"""智能路由：动态需求向量匹配模型能力矩阵

工作流程：
  1. 快速路径：问候/告别/简单命令 → 直接用默认模型（0 延迟）
  2. 需求预测：用轻量 LLM 分析消息，输出 15 维需求向量（0-10）
  3. 模型选择：需求向量 × 模型能力画像 → 加权评分 → 选最优模型

V2（旧版）：4 意图分类 → 查硬编码需求模板 → 评分
V3（当前）：直接预测需求向量 → 评分，完全释放 15 维矩阵表达力
V3.1：新增 3 个规格需求维度（cost_sensitivity/speed_priority/context_need），
      替代硬编码成本惩罚和 mode 加成
"""

import json
import logging
from typing import Any

from app.domain.models import ChatMessage
from app.evaluation.matrix.model_matrix import (
    get_matrix,
    ModelProfile,
    score_model_for_requirement_dict,
    select_models_by_requirements,
)
from app.kernel.router.llm_router import get_router

logger = logging.getLogger("evoiceclaw.kernel.smart_router")

# ── 意图预测前置脱敏（Level 1 正则，微秒级，无 IO） ──
# 用于在发送给分类 LLM 之前过滤 CRITICAL/HIGH 级别的身份标识符。
# 脱敏后的消息与原始消息的 15 维需求向量完全等价（语义类型不变，内容值被替换）。
_quick_isolator = None


def _get_quick_isolator():
    """懒加载快速脱敏实例（仅启用 Level 1 正则，不依赖外部服务）。"""
    global _quick_isolator
    if _quick_isolator is None:
        from app.pipeline.cognitive_isolator import CognitiveIsolator
        _quick_isolator = CognitiveIsolator({
            "enabled": True,
            "sensitivity_levels": {
                "critical": True,
                "high": True,
                "medium": False,
                "low": False,
            },
        })
    return _quick_isolator

# 默认模型兜底值
_DEFAULT_MODEL_ID_FALLBACK = "deepseek/deepseek-chat"

# 15 个需求维度（12 能力维度 + 3 规格需求维度，与 ModelProfile 字段一致）
ALL_DIMS = [
    "math_reasoning", "coding", "long_context", "chinese_writing",
    "agent_tool_use", "knowledge_tech", "knowledge_business",
    "knowledge_legal", "knowledge_medical", "logic", "reasoning",
    "instruction_following",
    # 规格需求维度（V3.1 新增）
    "cost_sensitivity", "speed_priority", "context_need",
]

# 预测失败时的兜底需求向量（通用均衡）
_FALLBACK_REQUIREMENTS: dict[str, int] = {
    "math_reasoning": 3, "coding": 3, "long_context": 3, "chinese_writing": 5,
    "agent_tool_use": 5, "knowledge_tech": 3, "knowledge_business": 3,
    "knowledge_legal": 2, "knowledge_medical": 2, "logic": 4, "reasoning": 4,
    "instruction_following": 5,
    # 规格需求维度兜底值
    "cost_sensitivity": 3,  # 默认轻微在意成本
    "speed_priority": 4,    # 默认中等在意速度
    "context_need": 3,      # 默认中等上下文需求
}

# 维度 → 粗粒度意图的映射（用于向后兼容日志和验证）
_DIM_TO_INTENT = {
    "math_reasoning": "reasoning",
    "coding": "coding",
    "long_context": "long_text",
    "chinese_writing": "long_text",
    "logic": "reasoning",
    "reasoning": "reasoning",
}

# ── 快速路径关键词 ──
_GREETING_KEYWORDS = frozenset([
    "你好", "您好", "嗨", "hi", "hello", "hey",
    "在吗", "在不在", "在么",
    "谢谢", "感谢", "多谢", "thanks", "thank",
    "再见", "拜拜", "bye", "晚安", "早安", "早上好", "下午好", "晚上好",
    "好的", "ok", "嗯", "哦", "哈喽",
])

# 需求预测 Prompt
_PREDICT_SYSTEM_PROMPT = """你是一个任务需求分析器。请分析用户消息，评估其对以下能力维度的需求强度，输出 JSON 对象。

维度及含义：
- math_reasoning: 数学推理（计算、证明等）
- coding: 编程能力（写代码、调试）
- long_context: 长上下文处理（长文档、多轮对话）
- chinese_writing: 中文写作（文章、润色）
- agent_tool_use: 工具调用（读文件、搜索、API）
- knowledge_tech: 技术知识（计算机、工程）
- knowledge_business: 商业知识（市场、财务）
- knowledge_legal: 法律知识（合同、法规）
- knowledge_medical: 医学知识（疾病、药物）
- logic: 逻辑推理（分析逻辑关系）
- reasoning: 综合推理（解决问题、分析）
- instruction_following: 指令遵循（精确执行复杂指令）
- cost_sensitivity: 成本敏感度（0=不在乎价格要最好的，10=极度在意成本要最便宜的）
- speed_priority: 速度优先级（0=不在乎速度要最深度的，10=极度在意速度要最快响应的）
- context_need: 上下文需求（0=短对话，10=需要处理超长文档/多轮历史）

评分标准：0 = 完全不需要，10 = 极度需要。只输出 JSON，不要任何解释。
例如：{"math_reasoning":0,"coding":8,"long_context":2,"chinese_writing":3,"agent_tool_use":6,"knowledge_tech":7,"knowledge_business":0,"knowledge_legal":0,"knowledge_medical":0,"logic":5,"reasoning":4,"instruction_following":7,"cost_sensitivity":3,"speed_priority":5,"context_need":2}"""


def _try_fast_path(message: str, available_ids: list[str], default_model: str) -> str | None:
    """尝试快速路径匹配，跳过需求预测

    Returns:
        model_id 或 None
    """
    text = message.strip().lower()

    # 去除常见中英文标点后再匹配（"你好！" → "你好"）
    _punct = "！!？?。.，,～~…、；;：:""''\"'()（）【】[]{}《》<>—\u200b"
    stripped = text.strip(_punct)

    # 短问候/告别直接用默认模型
    if len(stripped) <= 10 and stripped in _GREETING_KEYWORDS:
        if default_model in available_ids:
            logger.info("[快速路径] 问候/告别，使用默认模型: %s", default_model)
            return default_model

    # 以 / 开头的命令
    if text.startswith("/"):
        if default_model in available_ids:
            logger.info("[快速路径] 命令消息，使用默认模型: %s", default_model)
            return default_model

    return None


def _derive_intent(req: dict[str, int]) -> str:
    """从需求向量推导粗粒度意图（向后兼容日志和验证触发）"""
    if not req:
        return "general"

    # 找最高权重的维度
    top_dim = max(req, key=lambda d: req.get(d, 0))
    top_val = req.get(top_dim, 0)

    # 如果最高权重很低，算 general
    if top_val <= 4:
        return "general"

    return _DIM_TO_INTENT.get(top_dim, "general")


async def predict_requirements(message: str, config: dict) -> dict[str, int]:
    """预测用户消息的 15 维需求向量

    双路径策略：
      1. 优先 kNN 预测（本地向量匹配，~30ms）
      2. kNN 不可用或低置信度 → 降级 LLM 分类器（~500ms）

    Returns:
        {dim: score} 其中 score 为 0-10 整数
    """
    # ── 路径 1：kNN 预测（优先） ──
    from app.kernel.router.knn_predictor import get_knn_predictor, _LOW_CONFIDENCE_THRESHOLD

    knn = get_knn_predictor()
    if knn is not None and knn.is_available():
        try:
            req, confidence = await knn.predict(message)
            if confidence <= _LOW_CONFIDENCE_THRESHOLD:
                # 高/中置信度，直接使用 kNN 结果
                logger.info(
                    "[智能路由] kNN 预测 (confidence=%.3f): %s | 输入=%s",
                    confidence, {k: v for k, v in req.items() if v > 0}, message[:60],
                )
                return req
            else:
                # 低置信度，降级到 LLM 分类器
                logger.info(
                    "[智能路由] kNN 置信度过低 (%.3f > %.2f)，降级 LLM 分类器 | 输入=%s",
                    confidence, _LOW_CONFIDENCE_THRESHOLD, message[:60],
                )
        except Exception as e:
            logger.warning("[智能路由] kNN 预测异常: %s，降级 LLM 分类器", e)

    # ── 路径 2：LLM 分类器（降级） ──
    return await _predict_requirements_llm(message, config)


async def _predict_requirements_llm(message: str, config: dict) -> dict[str, int]:
    """用轻量 LLM 预测用户消息的 15 维需求向量（原始实现，作为 kNN 降级路径）。

    Returns:
        {dim: score} 其中 score 为 0-10 整数
    """
    # 降级路径使用默认模型（kNN 已覆盖绝大多数请求，降级频率低，用主力模型保证质量）
    classify_model = config.get("llm", {}).get("default_model", "deepseek/deepseek-chat")

    # 前置脱敏：用 Level 1 正则过滤 CRITICAL/HIGH 敏感数据后再发给分类 LLM
    clean_msg = _get_quick_isolator().isolate(message).clean_text
    user_prompt = f"用户消息：{clean_msg[:500]}"

    try:
        from app.kernel.router.llm_router import collect_stream_text
        router = get_router()
        result = await collect_stream_text(
            router,
            [
                ChatMessage(role="system", content=_PREDICT_SYSTEM_PROMPT),
                ChatMessage(role="user", content=user_prompt),
            ],
            classify_model,
            config,
        )
        result = result.strip()

        # 提取 JSON（可能被 ``` 包裹）
        if "```" in result:
            import re
            m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", result)
            if m:
                result = m.group(1).strip()

        parsed: dict[str, Any] = json.loads(result)

        # 规范化：确保所有维度都有值，范围 0-10
        req: dict[str, int] = {}
        for dim in ALL_DIMS:
            val = parsed.get(dim, 0)
            try:
                val = int(val)
            except (TypeError, ValueError):
                val = 0
            req[dim] = max(0, min(10, val))

        logger.info(
            "[智能路由] LLM 需求向量: %s | 输入=%s",
            {k: v for k, v in req.items() if v > 0}, message[:60],
        )
        return req

    except json.JSONDecodeError:
        logger.warning("[智能路由] 需求预测 JSON 解析失败，使用兜底向量")
        return dict(_FALLBACK_REQUIREMENTS)
    except Exception as e:
        logger.warning("[智能路由] 需求预测失败: %s，使用兜底向量", e)
        return dict(_FALLBACK_REQUIREMENTS)


async def select_model_for_direct_chat(message: str, config: dict) -> str:
    """根据需求向量自动选择最优模型"""
    candidates = await select_models_for_direct_chat(message, config, top_k=1)
    if not candidates:
        logger.warning("[智能路由] 无可用模型")
        return ""
    return candidates[0]


async def select_models_for_direct_chat(
    message: str, config: dict, top_k: int = 3,
) -> list[str]:
    """返回 top_k 个候选模型 ID（按适配分降序）"""
    router = get_router()
    all_models = router.get_available_models(config)
    available_ids = [m["id"] for m in all_models if m["type"] == "api"]

    if not available_ids:
        logger.warning("[智能路由] 无可用 API 模型")
        return []

    # 过滤：仅保留有评测数据的模型（无评测数据的模型不参与路由）
    matrix = get_matrix()
    evaluated_ids = [mid for mid in available_ids if matrix.get_model_profile(mid) is not None]
    if not evaluated_ids:
        logger.warning("[智能路由] 所有可用模型均无评测数据，回退到全量候选")
        evaluated_ids = available_ids  # 极端回退：避免完全无模型可用
    elif len(evaluated_ids) < len(available_ids):
        skipped = set(available_ids) - set(evaluated_ids)
        logger.info("[智能路由] 已排除 %d 个无评测数据的模型: %s", len(skipped), sorted(skipped))

    # 硬性约束筛选（PolicyEngine）
    from app.kernel.router.policy_engine import get_policy_engine
    evaluated_ids = get_policy_engine().filter_models(evaluated_ids)

    # 默认模型
    default_model = config.get("llm", {}).get("default_model", _DEFAULT_MODEL_ID_FALLBACK)

    # 快速路径
    fast_result = _try_fast_path(message, evaluated_ids, default_model)
    if fast_result is not None:
        return [fast_result]

    # 需求预测
    req = await predict_requirements(message, config)

    # 全零向量安全网：LLM 对简单消息可能返回全零，回退到默认模型
    if all(v == 0 for v in req.values()):
        logger.info("[智能路由] 需求向量全零，回退默认模型: %s", default_model)
        if default_model in evaluated_ids:
            return [default_model]

    # 按需求向量选模型
    candidates = select_models_by_requirements(
        requirements=req,
        available_models=evaluated_ids,
        top_k=top_k,
    )

    logger.info("[智能路由] 候选模型=%s", candidates)
    return candidates


async def select_model_with_intent(
    message: str, config: dict,
) -> tuple[str, str, list[str]]:
    """返回 (model_id, intent, fallback_candidates)

    intent 从需求向量推导，用于向后兼容日志和验证触发。
    fallback_candidates 包含 top 3 候选模型（含首选），供 chat_service fallback 使用。
    """
    router = get_router()
    all_models = router.get_available_models(config)
    available_ids = [m["id"] for m in all_models if m["type"] == "api"]

    if not available_ids:
        return ("", "general", [])

    # 过滤：仅保留有评测数据的模型（无评测数据的模型不参与路由）
    matrix = get_matrix()
    evaluated_ids = [mid for mid in available_ids if matrix.get_model_profile(mid) is not None]
    if not evaluated_ids:
        evaluated_ids = available_ids  # 极端回退
    elif len(evaluated_ids) < len(available_ids):
        skipped = set(available_ids) - set(evaluated_ids)
        logger.info("[智能路由] 已排除 %d 个无评测数据的模型: %s", len(skipped), sorted(skipped))

    # 硬性约束筛选（PolicyEngine）
    from app.kernel.router.policy_engine import get_policy_engine
    evaluated_ids = get_policy_engine().filter_models(evaluated_ids)

    default_model = config.get("llm", {}).get("default_model", _DEFAULT_MODEL_ID_FALLBACK)

    # 快速路径
    fast_result = _try_fast_path(message, evaluated_ids, default_model)
    if fast_result is not None:
        return (fast_result, "general", [fast_result])

    # 需求预测
    req = await predict_requirements(message, config)
    intent = _derive_intent(req)

    # 全零向量安全网
    if all(v == 0 for v in req.values()):
        logger.info("[智能路由] 需求向量全零，回退默认模型: %s", default_model)
        if default_model in evaluated_ids:
            return (default_model, "general", [default_model])

    # 按需求向量选模型（取 top 3 供 fallback）
    candidates = select_models_by_requirements(
        requirements=req,
        available_models=evaluated_ids,
        top_k=3,
    )
    if candidates:
        return (candidates[0], intent, candidates)

    return (evaluated_ids[0], intent, evaluated_ids[:3])


# ── 向后兼容：保留 classify_intent 供外部调用 ──

async def classify_intent(message: str, config: dict) -> str:
    """向后兼容：通过需求预测推导意图（旧版直接返回意图字符串）"""
    req = await predict_requirements(message, config)
    return _derive_intent(req)
