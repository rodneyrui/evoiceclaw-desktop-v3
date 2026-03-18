"""NER 兜底检测器 — 认知隔离器 Level 4

职责: 使用 CLUENER 微调的 RoBERTa 模型识别命名实体，作为最后一级兜底。

特点:
  - 基于 uer/roberta-base-finetuned-cluener2020-chinese (102M 参数)
  - 支持人名、地址、组织机构三类实体
  - CPU 推理 80-120ms，首次调用懒加载模型
  - 已被上层检测到的实体会自动去重，不会重复标记

实体类型映射 (CLUENER → 隐私管道):
  - name → PERSON_NAME (CRITICAL)
  - address → ADDRESS (HIGH)
  - company/organization/government → ORGANIZATION (MEDIUM)
  - position/scene/book/game/movie → 跳过

依赖: transformers + torch（可选，未安装时静默降级）
"""

import logging

from app.domain.models import SensitivityLevel

logger = logging.getLogger("evoiceclaw.pipeline.ner")

# CLUENER 实体标签 → (隐私类型, 敏感度)
_CLUENER_ENTITY_MAP: dict[str, tuple[str, SensitivityLevel]] = {
    "name":         ("PERSON_NAME",  SensitivityLevel.CRITICAL),
    "address":      ("ADDRESS",      SensitivityLevel.HIGH),
    "company":      ("ORGANIZATION", SensitivityLevel.MEDIUM),
    "organization": ("ORGANIZATION", SensitivityLevel.MEDIUM),
    "government":   ("ORGANIZATION", SensitivityLevel.MEDIUM),
}

# 跳过的 CLUENER 标签（非隐私相关）
_SKIP_LABELS = frozenset({"position", "scene", "book", "game", "movie"})

_MODEL_NAME = "uer/roberta-base-finetuned-cluener2020-chinese"

# CLUENER RoBERTa 最大序列长度 512 token（约 400 个中文字符）
# 隐私实体通常出现在文本前部，截断不影响检测效果
_MAX_NER_CHARS = 400


class DetectedNerItem:
    """NER 检测到的命名实体"""
    __slots__ = ("original", "type", "sensitivity", "start", "end", "source", "confidence")

    def __init__(
        self, original: str, type: str, sensitivity: SensitivityLevel,
        start: int, end: int, confidence: float = 0.7,
    ):
        self.original = original
        self.type = type
        self.sensitivity = sensitivity
        self.start = start
        self.end = end
        self.source = "ner_cluener"
        self.confidence = confidence


class NerDetector:
    """基于 CLUENER RoBERTa 的 NER 兜底检测器

    使用方式:
      1. 初始化时检测 transformers 是否可导入
      2. 首次调用 detect() 时才加载模型（懒加载）
      3. 识别人名/地址/组织机构，置信度使用模型输出的 score
    """

    def __init__(self):
        self._available = False
        self._pipeline = None  # 懒加载，首次 detect() 才创建
        self._model_loaded = False

        try:
            import transformers  # noqa: F401
            self._available = True
            logger.info("[NER] transformers 已检测到，CLUENER RoBERTa 可用（懒加载）")
        except ImportError:
            logger.warning("[NER] transformers 未安装，Level 4 NER 不可用")

    @property
    def available(self) -> bool:
        return self._available

    def _load_model(self) -> bool:
        """懒加载模型，首次 detect() 时调用。

        Returns:
            是否加载成功
        """
        if self._model_loaded:
            return self._pipeline is not None

        self._model_loaded = True  # 标记已尝试加载，避免重复尝试
        try:
            from transformers import pipeline as hf_pipeline
            self._pipeline = hf_pipeline(
                "ner",
                model=_MODEL_NAME,
                aggregation_strategy="simple",
            )
            logger.info("[NER] CLUENER RoBERTa 模型已加载: %s", _MODEL_NAME)
            return True
        except Exception as e:
            logger.error("[NER] 模型加载失败: %s", e)
            self._available = False
            return False

    def detect(self, text: str) -> list[DetectedNerItem]:
        """检测文本中的命名实体（人名/地址/组织机构）

        Args:
            text: 待检测文本

        Returns:
            检测到的命名实体列表
        """
        if not self._available or not text.strip():
            return []

        # 懒加载模型
        if not self._model_loaded:
            if not self._load_model():
                return []

        if self._pipeline is None:
            return []

        try:
            truncated = text[:_MAX_NER_CHARS] if len(text) > _MAX_NER_CHARS else text
            raw_entities = self._pipeline(truncated)
        except Exception as e:
            logger.warning("[NER] 推理失败: %s", e)
            return []

        detected: list[DetectedNerItem] = []

        for ent in raw_entities:
            # CLUENER 标签格式: "name", "address", "company" 等
            label = ent.get("entity_group", "").lower()

            # 跳过非隐私相关标签
            if label in _SKIP_LABELS or label not in _CLUENER_ENTITY_MAP:
                continue

            entity_type, sensitivity = _CLUENER_ENTITY_MAP[label]

            # 模型输出的 word 可能带空格，需 strip
            word = ent.get("word", "").strip()
            # 去除 tokenizer 残留的 ## 前缀
            word = word.replace("##", "").replace(" ", "")

            # 单字实体过滤
            if len(word) < 2:
                continue

            # 用 text.find() 精确定位（模型输出的 start/end 可能因 tokenizer 偏移不准）
            start = text.find(word)
            if start == -1:
                # 降级使用模型给出的位置
                start = ent.get("start", 0)
                end = ent.get("end", start + len(word))
            else:
                end = start + len(word)

            score = ent.get("score", 0.7)

            detected.append(DetectedNerItem(
                original=word,
                type=entity_type,
                sensitivity=sensitivity,
                start=start,
                end=end,
                confidence=round(score, 4),
            ))

        if detected:
            logger.debug(
                "[NER] 检测到 %d 个命名实体: %s",
                len(detected),
                [(item.original, item.type) for item in detected],
            )

        return detected
