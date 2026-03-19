"""回复验证服务

用确定性规则判断是否需要验证（不靠 LLM 判断风险），
通过模型能力画像驱动触发条件 + 搜索交叉验证高风险声称。

验证方法：
  - legacy:              固定审核模型（默认 qwen-plus）做 JSON 事实核查
  - strong_model_review: 选择短板维度 ≥60 分的审核模型交叉验证
  - auto_search_verify:  web_search 交叉验证高风险事实声称

领域知识配置（风险词、声称模式、审核 Prompt）由规则引擎生成，
存储在 data/generated_rules/verification_config.yaml，不内置于源码。
未生成时自动回退到英文后备 Prompt，功能正常降级。

V3 适配说明：
  - 模型能力评分：0-100（V2 为 1-5），弱模型阈值改为 ≤60
  - 模型画像：get_matrix().get_model_profile() 替代 KNOWN_MODELS
  - 路由需求：本地 _INTENT_KEY_DIMS 定义验证触发维度
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("evoiceclaw.verification")

# ── 触发规则常量 ────────────────────────────────────────────

# 写操作工具（调用后的回复需要验证）
_WRITE_TOOLS = frozenset({
    "install_skill", "uninstall_skill", "save_memory", "delete_memory",
    "register_workspace", "activate_workspace", "write_file", "edit_file",
})

# 外部数据获取工具（验证 LLM 无法核实实时数据，跳过验证）
_EXTERNAL_DATA_TOOLS = frozenset({
    "http_request", "web_search", "web_fetch", "browse_url",
})

# 操作性关键词（仅英文技术命令，语言无关，无法律风险）
_ACTION_KEYWORDS = re.compile(
    r"(sudo\s|rm\s+-|chmod\s|chown\s|curl\s|wget\s"
    r"|pip\s+install|npm\s+install|apt\s+install|brew\s+install"
    r"|docker\s+run|kill\s+-|systemctl\s)",
    re.IGNORECASE,
)

# 代码块模式（含有意义内容的代码块）
_CODE_BLOCK = re.compile(r"```[\s\S]{20,}```")

# 最低回复长度（太短的回复不值得验证）
_MIN_REPLY_LENGTH = 50

# V3 能力维度（与 ModelProfile 字段对应）
_CAPABILITY_DIMS = [
    "math_reasoning", "coding", "long_context", "chinese_writing",
    "agent_tool_use", "knowledge_tech", "knowledge_business",
    "knowledge_legal", "knowledge_medical", "logic", "reasoning",
]

# V3 弱模型阈值（0-100 评分体系）
_WEAK_MODEL_THRESHOLD = 60.0

# 各意图的关键维度及其需求权重（用于验证触发判断：弱模型在高权重维度上触发审查）
_INTENT_KEY_DIMS: dict[str, dict[str, int]] = {
    "general": {},  # 通用意图无特别高权重维度
    "reasoning": {"math_reasoning": 9, "logic": 7, "reasoning": 9},
    "coding": {"coding": 9, "knowledge_tech": 6},
    "long_text": {"long_context": 8, "chinese_writing": 8},
}

# ── 后备 Prompt（当 verification_config.yaml 未生成时使用） ──────────────────

_FALLBACK_REVIEW_PROMPT = """You are a professional review assistant. Review the following AI reply for accuracy.

User question: {user_message}

AI reply: {assistant_reply}

Important context: The AI has access to tools including read_file, list_directory, write_file,
edit_file, web_search, web_fetch, http_request, execute_command, and others. References to these
tool names in the reply are valid and intentional — do NOT flag them as errors.

Check for:
1. Factual accuracy (data, references, specific claims)
2. Logical correctness
3. Code or command errors (ignore tool names like read_file, web_search — these are valid tools)
4. Misleading or materially incomplete information

Return strictly as JSON (no other text):
{{"verified": true_or_false, "confidence": "high"_or_"medium"_or_"low", "issues": ["issue1"], "summary": "one-line summary"}}

Return verified=true if basically correct; return false only for clear, specific errors."""

_FALLBACK_CORRECT_PROMPT = """User question: {user_message}

The original reply has the following issues:
{issues}

Please provide the corrected reply (give the corrected content directly, do not explain the correction process):"""

# ── verification_config.yaml 动态加载 ──────────────────────

_VC_CONFIG_PATH = (
    Path(__file__).parent.parent.parent
    / "data" / "generated_rules" / "verification_config.yaml"
)

_vc_config_cache: dict[str, Any] | None = None
_vc_config_mtime: float = 0.0
_vc_config_override: dict[str, Any] | None = None  # 测试注入专用

# 从 YAML 编译出的动态模式（None 表示未配置，功能降级）
_vc_risk_pattern: re.Pattern | None = None
_vc_claim_pattern: re.Pattern | None = None
_vc_action_extra: re.Pattern | None = None


def _set_verification_config_for_testing(cfg: dict | None) -> None:
    """测试专用：直接注入配置，跳过 YAML 文件读取。传入 None 清除注入。"""
    global _vc_config_override
    _vc_config_override = cfg
    _compile_patterns(cfg or {})


def _compile_patterns(cfg: dict) -> None:
    """将配置中的正则字符串编译为 Pattern 对象"""
    global _vc_risk_pattern, _vc_claim_pattern, _vc_action_extra

    for attr_name, key in [
        ("_vc_risk_pattern", "risk_patterns"),
        ("_vc_claim_pattern", "claim_patterns"),
        ("_vc_action_extra", "action_keywords_extra"),
    ]:
        raw = cfg.get(key, "")
        if raw:
            try:
                globals()[attr_name] = re.compile(raw, re.IGNORECASE)
            except re.error as e:
                logger.warning("[验证] 正则编译失败 %s: %s", key, e)
                globals()[attr_name] = None
        else:
            globals()[attr_name] = None


def _get_vc_config() -> dict[str, Any]:
    """读取 verification_config.yaml，mtime 缓存；文件不存在返回 {}"""
    global _vc_config_cache, _vc_config_mtime

    if _vc_config_override is not None:
        return _vc_config_override

    try:
        mtime = _VC_CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        return {}

    if _vc_config_cache is not None and mtime == _vc_config_mtime:
        return _vc_config_cache

    try:
        import yaml
        with open(_VC_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg: dict = yaml.safe_load(f) or {}
        _vc_config_cache = cfg
        _vc_config_mtime = mtime
        _compile_patterns(cfg)
        logger.debug("[验证] 已加载 verification_config.yaml")
        return cfg
    except Exception as e:
        logger.warning("[验证] 读取 verification_config.yaml 失败: %s", e)
        return {}


def _get_review_prompt() -> str:
    """获取审核 Prompt，优先使用规则引擎生成的版本"""
    return _get_vc_config().get("review_prompt", _FALLBACK_REVIEW_PROMPT)


def _get_correct_prompt() -> str:
    """获取修正 Prompt，优先使用规则引擎生成的版本"""
    return _get_vc_config().get("correct_prompt", _FALLBACK_CORRECT_PROMPT)


def has_multiple_api_providers(config: dict) -> bool:
    """检查是否配置了多个 API provider

    验证机制需要调用独立模型进行交叉审核；若只有一个 provider，
    无法实现真正意义的交叉验证，自动禁用验证机制。

    Returns:
        True — 有 ≥2 个已启用的 API provider，验证机制可以激活
        False — 只有 0 或 1 个 provider，禁用验证机制
    """
    providers = config.get("providers", {})
    enabled_count = sum(
        1 for p in providers.values()
        if isinstance(p, dict) and p.get("enabled", False)
    )
    return enabled_count >= 2


# ── 数据模型 ────────────────────────────────────────────────

@dataclass
class VerificationResult:
    """验证结果"""
    verified: bool          # 是否通过验证
    confidence: str         # "high" | "medium" | "low"
    issues: list[str]       # 发现的问题列表
    summary: str            # 一句话总结
    method: str             # 使用的验证方法
    elapsed_ms: int         # 验证耗时（毫秒）


# ── 触发逻辑 ────────────────────────────────────────────────

def should_verify(
    user_message: str,
    assistant_reply: str,
    tool_names_used: list[str],
    model_id: str | None = None,
    intent: str | None = None,
    config: dict | None = None,
) -> tuple[bool, str]:
    """确定性规则判断是否需要验证（不用 LLM）

    Returns:
        (should_verify, method): method 为 "legacy" | "strong_model_review" |
        "auto_search_verify" | "deep_think_review" | ""
    """
    if len(assistant_reply) < _MIN_REPLY_LENGTH:
        return (False, "")

    # 使用了外部数据获取工具 → 跳过（验证 LLM 无法核实实时数据）
    if any(t in _EXTERNAL_DATA_TOOLS for t in tool_names_used):
        logger.debug("[验证] 跳过：使用了外部数据工具 %s", tool_names_used)
        return (False, "")

    # 模型能力画像触发（当 model_id 可用时）
    if model_id:
        r = _check_capability_triggers(model_id, intent, assistant_reply)
        if r:
            return r

    # 多 Agent 协同整合：consult_expert ≥ 阈值 → 深度思考模型验证
    v_cfg = config.get("verification", {}) if config else {}
    dt_cfg = v_cfg.get("deep_think", {})
    min_consult = dt_cfg.get("min_consult_count", 2) if dt_cfg else 2
    consult_count = tool_names_used.count("consult_expert")
    if consult_count >= min_consult:
        logger.info(
            "[验证] 触发(多Agent协同整合): consult_expert=%d次",
            consult_count,
        )
        return (True, "deep_think_review")

    # 传统规则：写操作工具
    if any(t in _WRITE_TOOLS for t in tool_names_used):
        logger.debug("[验证] 触发：使用了写操作工具 %s", tool_names_used)
        return (True, "legacy")

    # 传统规则：代码块
    if _CODE_BLOCK.search(assistant_reply):
        logger.debug("[验证] 触发：回复包含代码块")
        return (True, "legacy")

    # 传统规则：操作性关键词（英文固定 + 规则引擎生成的语言扩展）
    if _ACTION_KEYWORDS.search(assistant_reply):
        logger.debug("[验证] 触发：回复包含操作性关键词")
        return (True, "legacy")
    _get_vc_config()  # 确保 _vc_action_extra 已加载
    if _vc_action_extra is not None and _vc_action_extra.search(assistant_reply):
        logger.debug("[验证] 触发：回复包含扩展操作关键词（来自规则引擎）")
        return (True, "legacy")

    return (False, "")


def _check_capability_triggers(
    model_id: str,
    intent: str | None,
    assistant_reply: str,
) -> tuple[bool, str] | None:
    """检查模型能力画像触发条件"""
    try:
        from app.evaluation.matrix.model_matrix import get_matrix
    except ImportError:
        return None

    matrix = get_matrix()
    profile = matrix.get_model_profile(model_id)
    if not profile:
        return None

    # 触发 1：弱模型处理高权重专业任务（弱模型某维度 ≤60 且该意图需求权重 ≥7）
    if intent:
        key_dims = _INTENT_KEY_DIMS.get(intent, {})
        for dim, req_weight in key_dims.items():
            model_score = getattr(profile, dim, 60.0)
            if model_score <= _WEAK_MODEL_THRESHOLD and req_weight >= 7:
                    logger.info(
                        "[验证] 触发(弱模型高权重任务): model=%s %s=%.0f 需求权重=%d 意图=%s",
                        model_id, dim, model_score, req_weight, intent,
                    )
                    return (True, "strong_model_review")

    # 触发 2：高风险事实声称（内容检测，依赖规则引擎提供模式）
    if _contains_high_risk_claims(assistant_reply):
        logger.info("[验证] 触发(高风险事实声称): model=%s", model_id)
        return (True, "auto_search_verify")

    return None


def _contains_high_risk_claims(reply: str) -> bool:
    """检测回复是否包含高风险事实声称（需规则引擎提供 risk_patterns）"""
    if len(reply) < 100:
        return False
    _get_vc_config()  # 确保 _vc_risk_pattern 已加载
    if _vc_risk_pattern is None:
        return False
    return bool(_vc_risk_pattern.search(reply))


def _get_weak_dims(model_id: str, intent: str | None) -> list[str]:
    """找出弱模型的短板维度"""
    try:
        from app.evaluation.matrix.model_matrix import get_matrix
    except ImportError:
        return ["reasoning", "logic"]

    matrix = get_matrix()
    profile = matrix.get_model_profile(model_id)
    if not profile:
        return ["reasoning", "logic"]

    weak: list[str] = []
    if intent:
        key_dims = _INTENT_KEY_DIMS.get(intent, {})
        for dim, req_weight in key_dims.items():
            score = getattr(profile, dim, 60.0)
            if score <= _WEAK_MODEL_THRESHOLD and req_weight >= 7:
                weak.append(dim)
    return weak or ["reasoning", "logic"]


def select_auditor_model(
    model_id: str,
    intent: str | None,
    config: dict,
) -> str:
    """选择审核模型：在短板维度上 ≥60 分且成本适中（cost_level ≤3）"""
    try:
        from app.evaluation.matrix.model_matrix import get_matrix
        from app.kernel.router.llm_router import get_router
        matrix = get_matrix()
        router = get_router()
    except (ImportError, RuntimeError):
        return "qwen/qwen-plus"

    available = router.get_available_models(config)
    available_ids = {m["id"] for m in available if m.get("type") == "api"}

    weak_dims = _get_weak_dims(model_id, intent)
    best: str | None = None
    best_score = -1.0

    for mid in available_ids:
        if mid == model_id:
            continue
        profile = matrix.get_model_profile(mid)
        if not profile:
            continue
        if profile.cost_level > 3:
            continue
        # 短板维度均需 ≥60
        if not all(getattr(profile, d, 0.0) >= 60.0 for d in weak_dims):
            continue
        score = sum(getattr(profile, d, 0.0) for d in weak_dims)
        if score > best_score:
            best_score = score
            best = mid

    chosen = best or "qwen/qwen-plus"
    logger.info("[验证] 审核模型选择: %s → %s (短板维度=%s)", model_id, chosen, weak_dims)
    return chosen


# ── 搜索交叉验证 ─────────────────────────────────────────────

def _extract_claims(reply: str) -> list[str]:
    """从回复中提取可验证的事实声称（需规则引擎提供 claim_patterns）"""
    _get_vc_config()  # 确保 _vc_claim_pattern 已加载
    if _vc_claim_pattern is None:
        return []
    matches = _vc_claim_pattern.findall(reply)
    seen: set[str] = set()
    claims: list[str] = []
    for m in matches:
        m = m.strip()
        if m and m not in seen and len(m) >= 5:
            seen.add(m)
            claims.append(m[:80])
    return claims[:3]


async def _verify_by_search(
    assistant_reply: str,
    config: dict,
) -> VerificationResult | None:
    """搜索交叉验证"""
    start = time.monotonic()
    claims = _extract_claims(assistant_reply)
    if not claims:
        return None

    try:
        from app.kernel.tools.registry import get_tool_registry
        web_search = get_tool_registry().get("web_search")
    except Exception:
        web_search = None

    if not web_search:
        logger.info("[验证] web_search 不可用，降级到强模型审核")
        return None

    summaries: list[str] = []
    for claim in claims:
        try:
            result = await web_search.execute({"query": claim, "max_results": 3})
            if result and "未找到" not in str(result):
                summaries.append(str(result)[:200])
        except Exception as e:
            logger.debug("[验证] 搜索声称失败: %s err=%s", claim[:30], e)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    claims_text = "、".join(claims)
    summary = f"已对回答中的关键事实（{claims_text}）进行自动检索。"
    if summaries:
        brief = "；".join(s[:100] for s in summaries[:2])
        summary += f"检索摘要：{brief}。请注意信息时效性。"
    else:
        summary += "未检索到相关验证信息，请自行核实关键数据。"

    return VerificationResult(
        verified=True,
        confidence="medium",
        issues=[],
        summary=summary,
        method="auto_search_verify",
        elapsed_ms=elapsed_ms,
    )


# ── 模型审核 ──────────────────────────────────────────────────

async def _call_model_for_json(
    system: str,
    user: str,
    model_id: str,
    config: dict,
) -> dict | None:
    """调用模型获取 JSON 结果"""
    from app.domain.models import ChatMessage
    from app.kernel.router.llm_router import get_router

    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user),
    ]
    router = get_router()
    parts: list[str] = []
    raw = ""

    try:
        async for chunk in router.stream(messages, model_id, config):
            if chunk.type == "text":
                parts.append(chunk.content)
            elif chunk.type == "error":
                logger.warning("[验证] LLM 返回错误: %s", chunk.content)
                return None

        raw = "".join(parts).strip()
        json_str = raw
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", raw)
            if m:
                json_str = m.group(1).strip()
        return json.loads(json_str)
    except json.JSONDecodeError:
        logger.warning("[验证] JSON 解析失败: raw=%s", raw[:200] if raw else "empty")
        return None
    except Exception as e:
        logger.warning("[验证] 模型调用异常: %s", e)
        return None


async def _verify_by_model(
    user_message: str,
    assistant_reply: str,
    auditor_model: str,
    config: dict,
    max_reply_len: int = 3000,
) -> VerificationResult | None:
    """使用模型审核回复"""
    start = time.monotonic()
    truncated = assistant_reply[:max_reply_len]
    if len(assistant_reply) > max_reply_len:
        truncated += "\n...(已截断)"

    prompt = _get_review_prompt().format(
        user_message=user_message[:500],
        assistant_reply=truncated,
    )
    data = await _call_model_for_json(
        "You are a professional review assistant. Return only JSON, no other text.",
        prompt,
        auditor_model,
        config,
    )
    if data is None:
        return None

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return VerificationResult(
        verified=bool(data.get("verified", True)),
        confidence=data.get("confidence", "low"),
        issues=data.get("issues", []),
        summary=data.get("summary", ""),
        method="strong_model_review",
        elapsed_ms=elapsed_ms,
    )


async def _verify_by_deep_think(
    user_message: str,
    assistant_reply: str,
    config: dict,
) -> VerificationResult | None:
    """并行调用深度思考模型（Kimi K2 Thinking + DeepSeek R1）进行双模型验证

    逻辑：
    - 从配置读取深度思考模型列表，筛选出当前可用的模型
    - asyncio.gather 并行调用 _verify_by_model()
    - 合并结果：任一模型发现问题 → 整体 verified=False，issues 合并去重
    - 降级：无可用深度思考模型时返回 None（调用方降级到 strong_model_review）
    """
    import asyncio

    v_cfg = config.get("verification", {})
    dt_cfg = v_cfg.get("deep_think", {})
    dt_models = dt_cfg.get("models", [
        "deepseek/deepseek-reasoner",
        "kimi/kimi-k2-thinking",
    ])
    dt_timeout = dt_cfg.get("timeout", 300)

    # 筛选可用模型
    try:
        from app.kernel.router.llm_router import get_router
        router = get_router()
        available = router.get_available_models(config)
        available_ids = {m["id"] for m in available if m.get("type") == "api"}
    except Exception:
        available_ids = set()

    usable = [m for m in dt_models if m in available_ids]
    if not usable:
        logger.info("[验证] 无可用深度思考模型，将降级")
        return None

    logger.info("[验证] 深度思考验证启动: models=%s", usable)
    start = time.monotonic()

    # 并行调用
    tasks = [
        _verify_by_model(
            user_message, assistant_reply, model_id, config,
            max_reply_len=8000,
        )
        for model_id in usable
    ]
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=dt_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("[验证] 深度思考验证超时 (%ds)", dt_timeout)
        return None

    # 合并结果
    valid_results: list[VerificationResult] = []
    for r in results:
        if isinstance(r, VerificationResult):
            valid_results.append(r)
        elif isinstance(r, Exception):
            logger.warning("[验证] 深度思考模型调用异常: %s", r)

    if not valid_results:
        return None

    elapsed_ms = int((time.monotonic() - start) * 1000)

    # 任一模型发现问题 → 整体不通过
    all_verified = all(r.verified for r in valid_results)
    # 合并 issues 去重
    seen_issues: set[str] = set()
    merged_issues: list[str] = []
    for r in valid_results:
        for issue in r.issues:
            if issue not in seen_issues:
                seen_issues.add(issue)
                merged_issues.append(issue)

    # 置信度取最低
    confidence_order = {"high": 2, "medium": 1, "low": 0}
    min_confidence = min(
        valid_results,
        key=lambda r: confidence_order.get(r.confidence, 0),
    ).confidence

    summaries = [r.summary for r in valid_results if r.summary]
    merged_summary = " | ".join(summaries) if summaries else ""

    return VerificationResult(
        verified=all_verified,
        confidence=min_confidence,
        issues=merged_issues,
        summary=merged_summary,
        method="deep_think_review",
        elapsed_ms=elapsed_ms,
    )


async def verify_response(
    user_message: str,
    assistant_reply: str,
    config: dict,
    method: str = "legacy",
    model_id: str | None = None,
    intent: str | None = None,
) -> VerificationResult | None:
    """验证回复，支持多种方法

    Returns:
        VerificationResult 或 None（验证出错时静默返回 None）
    """
    v_cfg = config.get("verification", {})

    if method == "deep_think_review":
        result = await _verify_by_deep_think(user_message, assistant_reply, config)
        if result is not None:
            return result
        logger.info("[验证] 深度思考验证不可用，降级为强模型审核")
        method = "strong_model_review"

    if method == "auto_search_verify":
        result = await _verify_by_search(assistant_reply, config)
        if result is not None:
            return result
        logger.info("[验证] 搜索验证不可用，降级为强模型审核")
        method = "strong_model_review"

    if method == "strong_model_review":
        auditor = select_auditor_model(model_id or "", intent, config)
        return await _verify_by_model(user_message, assistant_reply, auditor, config)

    # legacy：使用配置中指定的审核模型
    auditor = v_cfg.get("model", "qwen/qwen-plus")
    result = await _verify_by_model(user_message, assistant_reply, auditor, config)
    if result:
        result.method = "legacy"
    return result


async def correct_response(
    user_message: str,
    original_reply: str,
    issues: list[str],
    model_id: str,
    config: dict,
) -> str | None:
    """基于审核发现的问题自动修正回复

    Returns:
        修正后的回复字符串，或 None（修正失败时）
    """
    from app.domain.models import ChatMessage
    from app.kernel.router.llm_router import get_router

    issues_text = "\n".join(f"- {issue}" for issue in issues)
    prompt = _get_correct_prompt().format(
        user_message=user_message[:500],
        issues=issues_text,
    )
    messages = [
        ChatMessage(role="user", content=prompt),
    ]
    router = get_router()
    parts: list[str] = []

    try:
        async for chunk in router.stream(messages, model_id, config):
            if chunk.type == "text":
                parts.append(chunk.content)
            elif chunk.type == "error":
                logger.warning("[验证] 修正 LLM 返回错误: %s", chunk.content)
                return None
        corrected = "".join(parts).strip()
        return corrected if corrected else None
    except Exception as e:
        logger.warning("[验证] 修正调用异常: %s", e)
        return None
