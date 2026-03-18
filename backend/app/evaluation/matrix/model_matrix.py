"""动态模型能力矩阵 — 唯一数据来源：preset_evaluations.json

═══ 评测数据导入规范 ═══

1. 唯一导入路径：
   data/preset/preset_evaluations.json
   ModelMatrix 启动时直接读取此文件，不经过 LanceDB 或其他中间存储。

2. 数据文件格式要求：
   {
     "version": "3.0",
     "generated_at": "ISO8601 时间戳",
     "models": [
       {
         "model_id": "provider/model-name",  // 必须与 config.yaml 中的 models 列表一致
         "source": "benchmark_7q",            // 数据来源标识
         "dimension_scores": {                // 12 维能力评分（0-100），全部必填
           "coding": 70.4,
           "math_reasoning": 90.0,
           "logic": 96.4,
           "instruction_following": 97.1,
           "long_context": 88.6,
           "agent_tool_use": 82.9,
           "chinese_writing": 89.3,
           "knowledge_tech": 95.0,
           "knowledge_business": 97.1,
           "knowledge_legal": 100.0,
           "knowledge_medical": 91.4,
           "reasoning": 93.2
         },
         "avg_latency_ms": 37400,             // 必填：平均响应延迟（毫秒）
         "cost_input_per_m": 2.0,             // 必填：输入价格（元/百万 Token）
         "cost_output_per_m": 3.0,            // 必填：输出价格（元/百万 Token）
         "context_window": 128000,            // 必填：上下文窗口大小（Token 数）
         "not_measured_dims": []              // 可选：未实测的维度列表
       }
     ]
   }

3. 数据完整性要求：
   - config.yaml 中每个 enabled provider 下的每个 model_id 都必须在此文件中有对应条目
   - 启动时 ModelMatrix 会自动验证并输出缺失模型的警告日志
   - ⚠️ 缺失评测数据的模型将自动从路由候选中排除，不参与评分和选择

4. 数据生成方式：
   - 由 Benchmark 评测系统自动生成，不应人为手动添加或修改
   - 每次评测产出新版本后，替换此文件并更新 version 字段
   - 启动时通过内容 hash 检测变更，自动重新加载

5. 禁止的做法：
   - ❌ 手动往 LanceDB 插入模型评测数据
   - ❌ 在代码中硬编码模型能力分数
   - ❌ 从其他路径导入评测数据
   - ❌ config.yaml 中启用了模型但不在 preset_evaluations.json 中添加评测数据

改造历史：
- V3.0: 从 LanceDB 读取评测数据（已废弃）
- V3.1: 新增 3 个规格需求维度（cost_sensitivity/speed_priority/context_need）
- V3.2: 移除旧版 4 意图路由
- V3.3: 改为直接从 preset_evaluations.json 读取，去掉 LanceDB 中转，
        新增配置一致性验证

最后更新：2026-03-15 (V3.3 唯一导入路径 + 数据规范)
"""

import json
import logging
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("evoiceclaw.evaluation.model_matrix")

# 唯一数据来源
PRESET_DATA_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "preset" / "preset_evaluations.json"

# 生成规则目录（与 rule_generator.py 保持一致）
_RULES_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "generated_rules"


# ── 能力维度字段名集合 ──
_CAPABILITY_FIELDS = {
    "math_reasoning", "coding", "long_context", "chinese_writing",
    "agent_tool_use", "knowledge_tech", "knowledge_business",
    "knowledge_legal", "knowledge_medical", "logic", "reasoning",
    "instruction_following",
}


@dataclass
class ModelProfile:
    """单个模型的能力画像"""
    provider: str
    model: str
    display_name: str

    # 12 维能力评分 (0-100)
    math_reasoning: float = 60.0
    coding: float = 60.0
    long_context: float = 60.0
    chinese_writing: float = 60.0
    agent_tool_use: float = 60.0
    knowledge_tech: float = 60.0
    knowledge_business: float = 60.0
    knowledge_legal: float = 60.0
    knowledge_medical: float = 60.0
    instruction_following: float = 60.0
    logic: float = 60.0
    reasoning: float = 60.0

    # 规格数据（原始值）
    cost_input_per_m: float = 0.0
    cost_output_per_m: float = 0.0
    cost_level: int = 3  # 1-5，派生自价格（向后兼容）
    rate_limit: int = 3
    max_context_k: int = 128
    avg_latency_ms: float = 30000.0  # 平均延迟（毫秒）
    mode: str = "analysis"
    fixed_temperature: Optional[float] = None

    # 规格维度连续评分 (0-100)，由原始值计算得出
    cost_score: float = 50.0       # 成本分：免费=100，越贵越低
    speed_score: float = 50.0      # 速度分：延迟越低越高
    context_score: float = 84.0    # 上下文分：窗口越大越高

    # 元数据
    source: str = "preset"
    not_measured_dims: List[str] = None

    def __post_init__(self):
        if self.not_measured_dims is None:
            self.not_measured_dims = []


def _parse_model_entry(model: dict) -> ModelProfile:
    """将 preset_evaluations.json 中的单个模型条目转换为 ModelProfile

    Args:
        model: JSON 中的单个模型字典

    Returns:
        ModelProfile 实例
    """
    model_id = model["model_id"]
    parts = model_id.split("/", 1)
    provider = parts[0]
    model_name = parts[1] if len(parts) > 1 else model_id

    scores = model.get("dimension_scores", {})
    not_measured = model.get("not_measured_dims", [])

    # 价格
    cost_input = model.get("cost_input_per_m", 0.0)
    cost_output = model.get("cost_output_per_m", 0.0)
    avg_cost = (cost_input + cost_output) / 2

    # cost_level (1-5，向后兼容)
    if avg_cost == 0:
        cost_level = 1
    elif avg_cost < 2:
        cost_level = 2
    elif avg_cost < 5:
        cost_level = 3
    elif avg_cost < 15:
        cost_level = 4
    else:
        cost_level = 5

    # 连续成本分 (0-100)
    cost_score = max(10.0, 100.0 - avg_cost * 6.0)

    # 延迟 → 速度分
    avg_latency = model.get("avg_latency_ms", 30000.0)
    speed_score = max(10.0, 100.0 - avg_latency / 1500.0)

    # 上下文窗口 → 上下文分
    context_window = model.get("context_window", 128000)
    ctx_k = max(1, context_window // 1000)
    context_score = min(100.0, math.log2(ctx_k) * 12.0)

    # 推断 mode
    mode = "analysis" if context_window >= 128000 or cost_level >= 3 else "fast"

    return ModelProfile(
        provider=provider,
        model=model_name,
        display_name=model_id,
        math_reasoning=scores.get("math_reasoning", 60.0),
        coding=scores.get("coding", 60.0),
        long_context=scores.get("long_context", 60.0),
        chinese_writing=scores.get("chinese_writing", 60.0),
        agent_tool_use=scores.get("agent_tool_use", 60.0),
        knowledge_tech=scores.get("knowledge_tech", 60.0),
        knowledge_business=scores.get("knowledge_business", 60.0),
        knowledge_legal=scores.get("knowledge_legal", 60.0),
        knowledge_medical=scores.get("knowledge_medical", 60.0),
        instruction_following=scores.get("instruction_following", 60.0),
        logic=scores.get("logic", 60.0),
        reasoning=scores.get("reasoning", 60.0),
        cost_input_per_m=cost_input,
        cost_output_per_m=cost_output,
        cost_level=cost_level,
        rate_limit=3,
        max_context_k=ctx_k,
        avg_latency_ms=avg_latency,
        mode=mode,
        cost_score=cost_score,
        speed_score=speed_score,
        context_score=context_score,
        source=model.get("source", "preset"),
        not_measured_dims=not_measured,
    )


class ModelMatrix:
    """动态模型能力矩阵

    唯一数据来源：data/preset/preset_evaluations.json
    启动时一次性加载到内存，不依赖 LanceDB。
    """

    def __init__(self):
        self._cache: Dict[str, ModelProfile] = {}
        self._loaded = False

    def _load_preset(self) -> None:
        """从 preset_evaluations.json 加载模型数据（唯一导入路径）"""
        if not PRESET_DATA_PATH.exists():
            logger.error(
                "[ModelMatrix] 评测数据文件不存在: %s — "
                "SmartRouter 将无法正确路由，请确保评测系统已生成此文件",
                PRESET_DATA_PATH,
            )
            self._cache = {}
            self._loaded = True
            return

        try:
            with open(PRESET_DATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            models = data.get("models", [])
            version = data.get("version", "unknown")
            new_cache: Dict[str, ModelProfile] = {}

            for model in models:
                try:
                    model_id = model["model_id"]
                    profile = _parse_model_entry(model)
                    new_cache[model_id] = profile
                except Exception as e:
                    logger.warning("[ModelMatrix] 解析模型数据失败: %s", e)

            self._cache = new_cache
            self._loaded = True
            logger.info(
                "[ModelMatrix] 评测数据加载完成 (v%s)，共 %d 个模型",
                version, len(new_cache),
            )

        except Exception as e:
            logger.error("[ModelMatrix] 加载评测数据失败: %s", e, exc_info=True)
            self._cache = {}
            self._loaded = True

    def _ensure_loaded(self) -> None:
        """确保数据已加载"""
        if not self._loaded:
            self._load_preset()

    def get_model_profile(self, model_id: str) -> Optional[ModelProfile]:
        """获取单个模型的能力画像"""
        self._ensure_loaded()
        return self._cache.get(model_id)

    def get_all_models(self) -> Dict[str, ModelProfile]:
        """获取所有模型的能力画像"""
        self._ensure_loaded()
        return self._cache.copy()

    def force_refresh(self) -> None:
        """强制重新加载数据（用于评测数据更新后）"""
        logger.info("[ModelMatrix] 收到刷新信号，重新加载评测数据")
        self._loaded = False
        self._load_preset()

    def validate_against_config(self, config: dict) -> None:
        """验证配置中启用的模型是否都有评测数据

        在 main.py 启动时调用。对缺失评测数据的模型输出警告，
        不阻止启动（缺失的模型使用默认低分，仍可路由但不利于被选中）。
        """
        self._ensure_loaded()

        providers = config.get("providers", {})
        configured_models: set[str] = set()
        for provider_id, pcfg in providers.items():
            if not pcfg.get("enabled"):
                continue
            for model_id in pcfg.get("models", []):
                configured_models.add(model_id)

        evaluated_models = set(self._cache.keys())

        # 在配置中启用但无评测数据的模型
        missing = configured_models - evaluated_models
        if missing:
            logger.warning(
                "[ModelMatrix] ⚠️ 以下 %d 个模型在 config.yaml 中启用但无评测数据，"
                "这些模型将被自动排除在路由候选之外（请补充评测后重启）:\n  %s",
                len(missing), "\n  ".join(sorted(missing)),
            )

        # 有评测数据但未在配置中启用的模型（仅 debug 级别提示）
        unused = evaluated_models - configured_models
        if unused:
            logger.debug(
                "[ModelMatrix] %d 个模型有评测数据但未在 config.yaml 中启用: %s",
                len(unused), sorted(unused),
            )


# ── 全局单例 ──
_matrix_instance: Optional[ModelMatrix] = None


def get_matrix() -> ModelMatrix:
    """获取全局 ModelMatrix 单例"""
    global _matrix_instance
    if _matrix_instance is None:
        _matrix_instance = ModelMatrix()
    return _matrix_instance


# ── V3 动态需求向量路由（R1 设计） ──

# 需求向量维度名集合（与 ALL_DIMS 在 smart_router 中一致）
_REQ_DIMS = [
    "math_reasoning", "coding", "long_context", "chinese_writing",
    "agent_tool_use", "knowledge_tech", "knowledge_business",
    "knowledge_legal", "knowledge_medical", "logic", "reasoning",
    "instruction_following",
    # 规格需求维度（V3.1 新增）
    "cost_sensitivity", "speed_priority", "context_need",
]


def score_model_for_requirement_dict(
    profile: ModelProfile, req: Dict[str, int],
) -> float:
    """用动态需求向量计算模型适配分

    V3.1 变更：cost_sensitivity/speed_priority/context_need 三个规格维度
    替代了原来的硬编码成本惩罚（cost_level * 2）和 mode 加成（analysis * 1.05）。

    Args:
        profile: 模型能力画像（0-100 评分）
        req: 需求向量（0-10 权重），包含 12 能力维度 + 3 规格维度

    Returns:
        加权适配分（越高越好）
    """
    # 归一化到 0-5 范围
    def normalize(score: float) -> float:
        return score / 20.0  # 100 → 5, 60 → 3

    score = 0.0
    for dim in _REQ_DIMS:
        weight = req.get(dim, 0)
        if weight <= 0:
            continue

        # 规格维度：直接用 ModelProfile 上的连续评分 (0-100)
        if dim == "cost_sensitivity":
            model_score = profile.cost_score
            score += weight * normalize(model_score)
        elif dim == "speed_priority":
            model_score = profile.speed_score
            score += weight * normalize(model_score)
        elif dim == "context_need":
            model_score = profile.context_score
            score += weight * normalize(model_score)
        else:
            # 能力维度：直接用 ModelProfile 上的 0-100 评分
            model_score = getattr(profile, dim, 50.0)
            score += weight * normalize(model_score)

    return score


def select_models_by_requirements(
    requirements: Dict[str, int],
    available_models: List[str],
    top_k: int = 3,
) -> List[str]:
    """用动态需求向量选择 top_k 个最优模型

    自动排除不支持工具的模型（当 agent_tool_use 需求 > 3 时）。

    Args:
        requirements: 15 维需求向量 {dim: 0-10}（12 能力 + 3 规格）
        available_models: 可用模型 ID 列表
        top_k: 返回数量

    Returns:
        模型 ID 列表（按适配分降序）
    """
    # 当工具需求显著时，过滤不支持工具的模型
    tool_need = requirements.get("agent_tool_use", 0)
    if tool_need > 3:
        from app.kernel.providers.api_provider import _NO_TOOLS_MODELS
        candidates = [
            m for m in available_models
            if (m.split("/", 1)[-1] if "/" in m else m) not in _NO_TOOLS_MODELS
        ]
        if not candidates:
            candidates = available_models  # 回退
    else:
        candidates = available_models

    matrix = get_matrix()
    scored: List[tuple[str, float]] = []

    for model_id in candidates:
        profile = matrix.get_model_profile(model_id)
        if not profile:
            # 无评测数据的模型自动排除，不参与路由
            logger.debug("[动态路由] 跳过无评测数据的模型: %s", model_id)
            continue

        s = score_model_for_requirement_dict(profile, requirements)

        # 评分噪声：±5% 随机扰动，让分数接近的模型有机会被选中
        noise = random.uniform(-0.05, 0.05)
        s *= (1.0 + noise)

        # 健康系数
        try:
            from app.kernel.providers.health import get_health_tracker
            provider = model_id.split("/")[0]
            s *= get_health_tracker().health_multiplier(provider)
        except RuntimeError:
            pass

        scored.append((model_id, s))

    if not scored:
        return candidates[:top_k] if candidates else []

    scored.sort(key=lambda x: x[1], reverse=True)
    result = [model_id for model_id, _ in scored[:top_k]]

    logger.info(
        "[动态路由] 需求=%s → 候选=%s",
        {k: v for k, v in requirements.items() if v > 0}, result,
    )
    return result


# ── 向后兼容：导出 KNOWN_MODELS（从缓存读取） ──

def get_known_models() -> Dict[str, ModelProfile]:
    """获取所有已知模型（兼容旧版 KNOWN_MODELS 字典）"""
    return get_matrix().get_all_models()


# 模拟旧版的 KNOWN_MODELS 全局变量（延迟加载）
class _KnownModelsProxy:
    """代理对象，模拟 KNOWN_MODELS 字典"""
    def __getitem__(self, key: str) -> Optional[ModelProfile]:
        return get_matrix().get_model_profile(key)

    def get(self, key: str, default=None) -> Optional[ModelProfile]:
        result = get_matrix().get_model_profile(key)
        return result if result is not None else default

    def __contains__(self, key: str) -> bool:
        return get_matrix().get_model_profile(key) is not None

    def items(self):
        return get_matrix().get_all_models().items()

    def keys(self):
        return get_matrix().get_all_models().keys()

    def values(self):
        return get_matrix().get_all_models().values()


KNOWN_MODELS = _KnownModelsProxy()
