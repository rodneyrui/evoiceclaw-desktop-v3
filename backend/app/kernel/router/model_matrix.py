"""国内 LLM 模型能力矩阵与自动分配策略

基于 2026 年 3 月调研数据 + 国内五大模型 API 对照表 + 自建 Benchmark 实测，
用于智能路由自动为不同意图选择最合适的模型。

13 维度模型画像：
  能力维度（1-5 评分，5 为最强）：
    1. math_reasoning    — 数学/逻辑推理
    2. coding             — 代码/工程
    3. long_context       — 长文本处理
    4. chinese_writing    — 中文写作/报告
    5. agent_tool_use     — Agent/工具调用
    6. knowledge_tech     — 技术/工程知识
    7. knowledge_finance  — 金融/经济知识
    8. knowledge_legal    — 法律/法规知识
    9. knowledge_market   — 市场/商业知识
   10. logic              — 形式逻辑
   11. reasoning          — 开放推理
  经济维度：
   12. cost_input/output_per_m — 精确价格（元/百万tokens）

最后更新：2026-03-09
"""

from dataclasses import dataclass


# ── 能力维度字段名集合 ──
_CAPABILITY_FIELDS = {
    "math_reasoning", "coding", "long_context", "chinese_writing",
    "agent_tool_use", "knowledge_tech", "knowledge_finance",
    "knowledge_legal", "knowledge_market", "logic", "reasoning",
}


@dataclass
class ModelProfile:
    """单个模型的能力画像"""
    provider: str
    model: str
    display_name: str
    math_reasoning: int = 3
    coding: int = 3
    long_context: int = 3
    chinese_writing: int = 3
    agent_tool_use: int = 3
    knowledge_tech: int = 3
    knowledge_finance: int = 3
    knowledge_legal: int = 3
    knowledge_market: int = 3
    logic: int = 3
    reasoning: int = 3
    cost_input_per_m: float = 0.0
    cost_output_per_m: float = 0.0
    cost_level: int = 3
    rate_limit: int = 3
    max_context_k: int = 128
    mode: str = "analysis"
    fixed_temperature: float | None = None


# ─── 国内模型能力库 ───────────────────────────────────

KNOWN_MODELS: dict[str, ModelProfile] = {
    # ── DeepSeek 系列 ──
    "deepseek/deepseek-chat": ModelProfile(
        provider="deepseek", model="deepseek-chat",
        display_name="DeepSeek V3",
        math_reasoning=5, coding=5, long_context=5, chinese_writing=5,
        agent_tool_use=5, knowledge_tech=4, knowledge_finance=4, knowledge_legal=5, knowledge_market=4,
        logic=5, reasoning=5,
        cost_input_per_m=2, cost_output_per_m=3,
        cost_level=1, rate_limit=3, max_context_k=128, mode="analysis",
    ),
    "deepseek/deepseek-reasoner": ModelProfile(
        provider="deepseek", model="deepseek-reasoner",
        display_name="DeepSeek R1",
        math_reasoning=5, coding=5, long_context=5, chinese_writing=5,
        agent_tool_use=4, knowledge_tech=4, knowledge_finance=4, knowledge_legal=5, knowledge_market=5,
        logic=5, reasoning=5,
        cost_input_per_m=2, cost_output_per_m=3,
        cost_level=1, rate_limit=3, max_context_k=128, mode="analysis",
    ),

    # ── Qwen 系列 ──
    "qwen/qwen-max": ModelProfile(
        provider="qwen", model="qwen-max",
        display_name="Qwen3 Max",
        math_reasoning=5, coding=4, long_context=5, chinese_writing=4,
        agent_tool_use=5, knowledge_tech=5, knowledge_finance=5, knowledge_legal=3, knowledge_market=4,
        logic=5, reasoning=5,
        cost_input_per_m=6, cost_output_per_m=24,
        cost_level=4, rate_limit=4, max_context_k=256, mode="analysis",
    ),
    "qwen/qwen-plus": ModelProfile(
        provider="qwen", model="qwen-plus",
        display_name="Qwen3 Plus",
        math_reasoning=5, coding=5, long_context=5, chinese_writing=4,
        agent_tool_use=5, knowledge_tech=5, knowledge_finance=5, knowledge_legal=5, knowledge_market=4,
        logic=5, reasoning=4,
        cost_input_per_m=0.8, cost_output_per_m=2,
        cost_level=2, rate_limit=4, max_context_k=32, mode="fast",
    ),
    "qwen/qwen-turbo": ModelProfile(
        provider="qwen", model="qwen-turbo",
        display_name="Qwen3 Turbo",
        math_reasoning=5, coding=5, long_context=4, chinese_writing=4,
        agent_tool_use=5, knowledge_tech=4, knowledge_finance=3, knowledge_legal=5, knowledge_market=4,
        logic=4, reasoning=5,
        cost_input_per_m=0.3, cost_output_per_m=0.6,
        cost_level=1, rate_limit=5, max_context_k=8, mode="fast",
    ),
    "qwen/qwen-coder-plus": ModelProfile(
        provider="qwen", model="qwen-coder-plus",
        display_name="Qwen3 Coder",
        math_reasoning=5, coding=4, long_context=5, chinese_writing=5,
        agent_tool_use=4, knowledge_tech=5, knowledge_finance=4, knowledge_legal=3, knowledge_market=4,
        logic=5, reasoning=5,
        cost_input_per_m=4, cost_output_per_m=16,
        cost_level=3, rate_limit=4, max_context_k=256, mode="analysis",
    ),
    "qwen/qwen-long": ModelProfile(
        provider="qwen", model="qwen-long",
        display_name="Qwen Long",
        math_reasoning=5, coding=5, long_context=5, chinese_writing=4,
        agent_tool_use=5, knowledge_tech=4, knowledge_finance=4, knowledge_legal=5, knowledge_market=4,
        logic=5, reasoning=4,
        cost_input_per_m=0.5, cost_output_per_m=2,
        cost_level=1, rate_limit=3, max_context_k=10000, mode="analysis",
    ),

    # ── Kimi 系列 ──
    "kimi/moonshot-v1-128k": ModelProfile(
        provider="kimi", model="moonshot-v1-128k",
        display_name="Kimi (128K)",
        math_reasoning=5, coding=4, long_context=4, chinese_writing=4,
        agent_tool_use=4, knowledge_tech=4, knowledge_finance=3, knowledge_legal=5, knowledge_market=4,
        logic=4, reasoning=5,
        cost_input_per_m=24, cost_output_per_m=24,
        cost_level=3, rate_limit=3, max_context_k=128, mode="fast",
    ),
    "kimi/kimi-k2.5": ModelProfile(
        provider="kimi", model="kimi-k2.5",
        display_name="Kimi K2.5",
        math_reasoning=5, coding=5, long_context=5, chinese_writing=5,
        agent_tool_use=5, knowledge_tech=4, knowledge_finance=4, knowledge_legal=5, knowledge_market=5,
        logic=5, reasoning=5,
        cost_input_per_m=4, cost_output_per_m=21,
        cost_level=3, rate_limit=3, max_context_k=256, mode="analysis",
        fixed_temperature=1.0,
    ),

    # ── 智谱 GLM 系列 ──
    "zhipu/glm-5": ModelProfile(
        provider="zhipu", model="glm-5",
        display_name="GLM-5",
        math_reasoning=5, coding=5, long_context=5, chinese_writing=5,
        agent_tool_use=5, knowledge_tech=4, knowledge_finance=4, knowledge_legal=5, knowledge_market=4,
        logic=5, reasoning=4,
        cost_input_per_m=4, cost_output_per_m=18,
        cost_level=4, rate_limit=3, max_context_k=128, mode="analysis",
    ),
    "zhipu/glm-4-flash": ModelProfile(
        provider="zhipu", model="glm-4-flash",
        display_name="GLM-4 Flash",
        math_reasoning=5, coding=5, long_context=4, chinese_writing=4,
        agent_tool_use=3, knowledge_tech=4, knowledge_finance=3, knowledge_legal=5, knowledge_market=3,
        logic=3, reasoning=4,
        cost_input_per_m=0, cost_output_per_m=0,
        cost_level=1, rate_limit=4, max_context_k=128, mode="fast",
    ),
    "zhipu/glm-4-air": ModelProfile(
        provider="zhipu", model="glm-4-air",
        display_name="GLM-4 Air",
        math_reasoning=5, coding=5, long_context=5, chinese_writing=4,
        agent_tool_use=5, knowledge_tech=4, knowledge_finance=3, knowledge_legal=5, knowledge_market=5,
        logic=5, reasoning=5,
        cost_input_per_m=0.5, cost_output_per_m=0.5,
        cost_level=1, rate_limit=4, max_context_k=128, mode="fast",
    ),

    # ── 百川智能 系列 ──
    "baichuan/Baichuan4-Air": ModelProfile(
        provider="baichuan", model="Baichuan4-Air",
        display_name="百川4 Air",
        math_reasoning=5, coding=4, long_context=5, chinese_writing=4,
        agent_tool_use=5, knowledge_tech=5, knowledge_finance=4, knowledge_legal=5, knowledge_market=5,
        logic=5, reasoning=4,
        cost_input_per_m=0.98, cost_output_per_m=0.98,
        cost_level=1, rate_limit=3, max_context_k=32, mode="analysis",
    ),
    "baichuan/Baichuan2-Turbo": ModelProfile(
        provider="baichuan", model="Baichuan2-Turbo",
        display_name="百川2 Turbo",
        math_reasoning=5, coding=4, long_context=5, chinese_writing=5,
        agent_tool_use=5, knowledge_tech=5, knowledge_finance=4, knowledge_legal=5, knowledge_market=5,
        logic=5, reasoning=4,
        cost_input_per_m=8, cost_output_per_m=8,
        cost_level=2, rate_limit=3, max_context_k=32, mode="analysis",
    ),
    "baichuan/Baichuan3-Turbo": ModelProfile(
        provider="baichuan", model="Baichuan3-Turbo",
        display_name="百川3 Turbo",
        math_reasoning=5, coding=4, long_context=5, chinese_writing=4,
        agent_tool_use=5, knowledge_tech=5, knowledge_finance=4, knowledge_legal=5, knowledge_market=5,
        logic=5, reasoning=4,
        cost_input_per_m=12, cost_output_per_m=12,
        cost_level=3, rate_limit=3, max_context_k=32, mode="analysis",
    ),
    "baichuan/Baichuan4": ModelProfile(
        provider="baichuan", model="Baichuan4",
        display_name="百川4",
        math_reasoning=5, coding=4, long_context=5, chinese_writing=4,
        agent_tool_use=5, knowledge_tech=5, knowledge_finance=4, knowledge_legal=5, knowledge_market=5,
        logic=5, reasoning=4,
        cost_input_per_m=100, cost_output_per_m=100,
        cost_level=5, rate_limit=3, max_context_k=128, mode="analysis",
    ),

    # ── MiniMax 系列 ──
    "minimax/MiniMax-M2.5": ModelProfile(
        provider="minimax", model="MiniMax-M2.5",
        display_name="MiniMax M2.5",
        math_reasoning=5, coding=5, long_context=5, chinese_writing=5,
        agent_tool_use=5, knowledge_tech=4, knowledge_finance=4, knowledge_legal=5, knowledge_market=4,
        logic=5, reasoning=5,
        cost_input_per_m=2.1, cost_output_per_m=8.4,
        cost_level=2, rate_limit=4, max_context_k=1024, mode="analysis",
    ),
    "minimax/MiniMax-M2.1": ModelProfile(
        provider="minimax", model="MiniMax-M2.1",
        display_name="MiniMax M2.1",
        math_reasoning=5, coding=5, long_context=5, chinese_writing=4,
        agent_tool_use=5, knowledge_tech=4, knowledge_finance=4, knowledge_legal=5, knowledge_market=4,
        logic=5, reasoning=5,
        cost_input_per_m=2.1, cost_output_per_m=8.4,
        cost_level=2, rate_limit=4, max_context_k=1024, mode="analysis",
    ),
    "minimax/MiniMax-M2": ModelProfile(
        provider="minimax", model="MiniMax-M2",
        display_name="MiniMax M2",
        math_reasoning=5, coding=5, long_context=5, chinese_writing=5,
        agent_tool_use=4, knowledge_tech=4, knowledge_finance=4, knowledge_legal=5, knowledge_market=3,
        logic=5, reasoning=4,
        cost_input_per_m=2.1, cost_output_per_m=8.4,
        cost_level=2, rate_limit=4, max_context_k=1024, mode="analysis",
    ),
}


# ─── Agent 角色 → 能力需求映射 ─────────────────────────

@dataclass
class AgentRequirement:
    """某个 Agent 角色对模型能力的需求权重（0-10，0=不关心，10=极重要）"""
    math_reasoning: int = 0
    coding: int = 0
    long_context: int = 0
    chinese_writing: int = 0
    agent_tool_use: int = 0
    knowledge_tech: int = 0
    knowledge_finance: int = 0
    knowledge_legal: int = 0
    knowledge_market: int = 0
    logic: int = 0
    reasoning: int = 0


# 直聊模式 4 种意图的能力需求
DIRECT_CHAT_REQUIREMENTS: dict[str, AgentRequirement] = {
    "general": AgentRequirement(
        knowledge_tech=5, knowledge_finance=5, knowledge_legal=5, knowledge_market=5,
        chinese_writing=6, agent_tool_use=3,
    ),
    "reasoning": AgentRequirement(
        math_reasoning=9, knowledge_tech=4, knowledge_finance=4,
        coding=4, logic=7, reasoning=9,
    ),
    "coding": AgentRequirement(
        coding=9, knowledge_tech=6, agent_tool_use=6,
    ),
    "long_text": AgentRequirement(
        long_context=8, chinese_writing=8,
        knowledge_tech=3, knowledge_finance=3, knowledge_legal=3, knowledge_market=3,
    ),
}


def score_model_for_agent(profile: ModelProfile, req: AgentRequirement) -> float:
    """计算某模型对某意图的适配得分（越高越好）"""
    score = 0.0
    score += req.math_reasoning * profile.math_reasoning
    score += req.coding * profile.coding
    score += req.long_context * profile.long_context
    score += req.chinese_writing * profile.chinese_writing
    score += req.agent_tool_use * profile.agent_tool_use
    score += req.knowledge_tech * profile.knowledge_tech
    score += req.knowledge_finance * profile.knowledge_finance
    score += req.knowledge_legal * profile.knowledge_legal
    score += req.knowledge_market * profile.knowledge_market
    score += req.logic * profile.logic
    score += req.reasoning * profile.reasoning

    # 偏好 analysis 级模型（质量优先）
    if profile.mode == "analysis":
        score *= 1.05

    # 成本惩罚：轻微偏好低成本
    score -= profile.cost_level * 2

    return score


def select_models_for_intent(
    intent: str,
    available_models: list[str],
    top_k: int = 3,
) -> list[str]:
    """为指定意图返回 top_k 个最优模型 ID（按适配分降序）

    Args:
        intent: 意图类型（general/reasoning/coding/long_text）
        available_models: 可用的模型 ID 列表
        top_k: 返回数量

    Returns:
        模型 ID 列表（按适配分降序）
    """
    req = DIRECT_CHAT_REQUIREMENTS.get(intent)
    if not req:
        return available_models[:top_k] if available_models else []

    scored: list[tuple[str, float]] = []

    for model_id in available_models:
        profile = KNOWN_MODELS.get(model_id)
        if not profile:
            parts = model_id.split("/", 1)
            profile = ModelProfile(
                provider=parts[0],
                model=parts[1] if len(parts) > 1 else model_id,
                display_name=model_id,
                mode="analysis",
            )
        s = score_model_for_agent(profile, req)

        # 健康系数：运行时动态降权故障/限速的 Provider
        try:
            from app.kernel.providers.health import get_health_tracker
            provider = model_id.split("/")[0]
            s *= get_health_tracker().health_multiplier(provider)
        except RuntimeError:
            pass

        scored.append((model_id, s))

    if not scored:
        return available_models[:top_k] if available_models else []

    scored.sort(key=lambda x: x[1], reverse=True)
    return [model_id for model_id, _ in scored[:top_k]]
