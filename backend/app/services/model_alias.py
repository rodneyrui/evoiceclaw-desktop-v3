"""模型别名检测：从自然语言消息中识别用户指定的 LLM 模型"""

import logging
import re

from app.kernel.router.llm_router import get_router

logger = logging.getLogger("evoiceclaw.chat")

# ── 自然语言模型指定：别名映射 ──
_MODEL_ALIASES: dict[str, str] = {}  # 懒加载

# 匹配模式：「让XX来做」「让XX来」「用XX来」「使用XX」「XX请帮我」「XX帮我」「@model」
_EXPLICIT_MODEL_PATTERNS = [
    # 「让 R1 来完成/做...」— 来后跟动词
    re.compile(r"(?:我想)?让\s*(.+?)\s*(?:来|去)\s*(?:完成|做|处理|执行|回答|分析|写|帮)", re.IGNORECASE),
    # 「让 R1 来」— 来后直接跟任务（句末或逗号/换行）
    re.compile(r"(?:我想)?让\s*(.+?)\s*来\s*[,，。\n]", re.IGNORECASE),
    # 「让 R1」— 后面直接跟任务（无"来"字）
    re.compile(r"(?:我想)?让\s*(.+?)\s*[,，。\n：:]", re.IGNORECASE),
    re.compile(r"(?:请)?用\s*(.+?)\s*(?:来|去)?(?:完成|做|处理|执行|回答|分析|写|帮)", re.IGNORECASE),
    re.compile(r"(?:请)?使用\s*(.+?)\s*(?:来|去)?(?:完成|做|处理|执行|回答|分析|写|帮)", re.IGNORECASE),
    # 模型名在句首 + 请帮我 / 帮我 / 请
    re.compile(r"^(.+?)[,，]?\s*(?:请帮我|帮我|请你?)\s*(?:完成|做|处理|执行|回答|分析|写|帮|来)", re.IGNORECASE),
    re.compile(r"@\s*(\S+)\s+", re.IGNORECASE),
]


def _build_model_aliases(config: dict) -> dict[str, str]:
    """构建模型别名 → model_id 映射"""
    aliases: dict[str, str] = {}
    router = get_router()
    models = router.get_available_models(config)
    for m in models:
        model_id = m["id"]
        name = m.get("name", "").lower().strip()
        if name:
            aliases[name] = model_id
        aliases[model_id.lower()] = model_id
        if "/" in model_id:
            short = model_id.split("/", 1)[1].lower()
            aliases[short] = model_id
    # 手动补充常见别名
    _extra: dict[str, str] = {
        "deepseek": "deepseek/deepseek-chat",
        "deepseek v3": "deepseek/deepseek-chat",
        "r1": "deepseek/deepseek-reasoner",
        "deepseek r1": "deepseek/deepseek-reasoner",
        "minimax": "minimax/MiniMax-M2.5",
        "minimax m2.5": "minimax/MiniMax-M2.5",
        "m2.5": "minimax/MiniMax-M2.5",
        "qwen": "qwen/qwen-max",
        "通义千问": "qwen/qwen-max",
        "千问": "qwen/qwen-max",
        "kimi": "kimi/kimi-k2.5",
        "kimi k2.5": "kimi/kimi-k2.5",
        "k2.5": "kimi/kimi-k2.5",
    }
    available_ids = {m["id"] for m in models}
    for alias, mid in _extra.items():
        if mid in available_ids:
            aliases[alias] = mid
    return aliases


def _detect_explicit_model(message: str, config: dict) -> tuple[str | None, str]:
    """检测消息中是否显式指定了模型。

    策略：
    1. 先用正则匹配结构化句式（让XX完成、用XX、XX请帮我 等）
    2. 兜底：检查消息开头是否以已知模型别名开头

    Returns:
        (model_id, original_message) — model_id 为 None 表示未检测到。
    """
    global _MODEL_ALIASES
    if not _MODEL_ALIASES:
        _MODEL_ALIASES = _build_model_aliases(config)

    # 策略 1：正则匹配
    for pattern in _EXPLICIT_MODEL_PATTERNS:
        match = pattern.search(message)
        if match:
            candidate = match.group(1).strip().lower()
            if candidate in _MODEL_ALIASES:
                return _MODEL_ALIASES[candidate], message

    # 策略 2：兜底 — 检查消息开头是否以已知模型别名开头
    msg_lower = message.strip().lower()
    # 按别名长度降序排列，优先匹配长别名（避免 "deepseek" 匹配 "deepseek r1" 场景）
    for alias in sorted(_MODEL_ALIASES.keys(), key=len, reverse=True):
        if msg_lower.startswith(alias):
            # 确认别名后面跟的是分隔符（空格、逗号、句号、冒号等），而非更长的单词
            rest = msg_lower[len(alias):]
            if rest and rest[0] in (" ", ",", "，", ":", "：", "、", "\n", "请", "帮"):
                return _MODEL_ALIASES[alias], message
    return None, message
