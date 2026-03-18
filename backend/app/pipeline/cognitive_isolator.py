"""认知隔离器（Cognitive Isolator）— 隐私管道第 ① 级

职责: 检测用户消息中的敏感数据，替换为 UUID 占位符，生成 redaction_map。
策略: 多级检测引擎 —
  Level 0: 文档类型语义驱动（关键词触发 + 向量反向匹配 + 按模板搜索标签后的值）
  Level 1: 正则快速扫描（身份证/银行卡/密码/手机/邮箱/金额）+ 文档类型置信度调整
  Level 2: AC 自动机词典（动态积累）
  Level 3: LanceDB entities 回查
  Level 4: NER 模型（CLUENER RoBERTa 兜底：人名/地址/组织）

输入: 用户原始消息 / 工具返回内容
输出: IsolationResult { clean_text, redaction_map, stats }

敏感度等级:
  CRITICAL — 身份证/银行卡/密码/人名 → UUID 占位符
  HIGH     — 手机号/邮箱/金额       → UUID 占位符
  MEDIUM   — 日期/IP地址            → 标记后通过（当前版本不替换）
  LOW      — 公开信息               → 直接通过
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

from app.domain.models import RedactionEntry, SensitivityLevel

if TYPE_CHECKING:
    from app.domain.models import SessionPrivacyContext

logger = logging.getLogger("evoiceclaw.pipeline.isolator")

# ── 占位符格式 ──

_PLACEHOLDER_PREFIX = "__REDACTED_"
_PLACEHOLDER_SUFFIX = "__"


def _make_placeholder() -> str:
    """生成唯一 UUID 占位符。"""
    return f"{_PLACEHOLDER_PREFIX}{uuid4().hex[:12]}{_PLACEHOLDER_SUFFIX}"


# ── 正则模式定义 ──

# CRITICAL 级: 身份证号（18位，最后一位可能是X）
_RE_ID_CARD = re.compile(
    r"(?<!\d)"
    r"[1-9]\d{5}"                          # 地区码
    r"(?:19|20)\d{2}"                      # 年份
    r"(?:0[1-9]|1[0-2])"                   # 月份
    r"(?:0[1-9]|[12]\d|3[01])"             # 日期
    r"\d{3}[\dXx]"                         # 顺序码+校验
    r"(?!\d)"
)

# CRITICAL 级: 银行卡号（16-19位连续数字，允许空格/短横线分隔）
_RE_BANK_CARD = re.compile(
    r"(?<!\d)"
    r"(?:\d{4}[\s-]?){3,4}\d{1,4}"
    r"(?!\d)"
)

# CRITICAL 级: 密码/密钥模式（password=xxx, secret=xxx, token=xxx 等）
_RE_SECRET = re.compile(
    r"(?:password|passwd|密码|口令|secret|token|api[_-]?key)"
    r"\s*[:=：]\s*"
    r"(\S{4,})",
    re.IGNORECASE,
)

# HIGH 级: 中国手机号（1开头11位）
# 排除：400/800 客服热线、9开头的5位短号（95188等）、10开头的运营商号码
_RE_PHONE = re.compile(
    r"(?<!\d)"
    r"1[3-9]\d{9}"
    r"(?!\d)"
)

# HIGH 级: 固定电话（区号-号码）
# 排除：400/800 免费客服热线（公开机构号码）
_RE_LANDLINE = re.compile(
    r"(?<!\d)"
    r"0\d{2,3}[-\s]?\d{7,8}"
    r"(?!\d)"
)

# HIGH 级: 邮箱
_RE_EMAIL = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)

# HIGH 级: 金额（带货币符号或单位）
_RE_MONEY = re.compile(
    r"(?:[\$¥￥€£])\s?\d[\d,]*\.?\d*"     # 前置货币符号
    r"|"
    r"\d[\d,]*\.?\d*\s?(?:元|万元|亿元|美元|美金|欧元|英镑|块钱|块|RMB|CNY|USD|EUR)",
    re.IGNORECASE,
)

# 所有检测规则（按优先级排序）
_DETECTION_RULES: list[tuple[re.Pattern, str, SensitivityLevel]] = [
    # CRITICAL
    (_RE_ID_CARD,   "ID_CARD",      SensitivityLevel.CRITICAL),
    (_RE_SECRET,    "SECRET",       SensitivityLevel.CRITICAL),
    (_RE_BANK_CARD, "BANK_CARD",    SensitivityLevel.CRITICAL),
    # HIGH
    (_RE_PHONE,     "PHONE",        SensitivityLevel.HIGH),
    (_RE_LANDLINE,  "LANDLINE",     SensitivityLevel.HIGH),
    (_RE_EMAIL,     "EMAIL",        SensitivityLevel.HIGH),
    (_RE_MONEY,     "MONEY",        SensitivityLevel.HIGH),
]

# ── 文档类型上下文置信度调整 ──
# (doc_type, entity_type) → 置信度
# 未命中此表时使用默认置信度 _DEFAULT_REGEX_CONFIDENCE

_DEFAULT_REGEX_CONFIDENCE = 0.85

_CONFIDENCE_BOOST: dict[tuple[str, str], float] = {
    # 征信报告：身份证号、银行卡号几乎确定；电话号码是机构客服热线（公开信息），不脱敏
    ("credit_report", "ID_CARD"):   0.99,
    ("credit_report", "BANK_CARD"): 0.95,
    ("credit_report", "MONEY"):     0.92,
    ("credit_report", "PHONE"):     0.0,      # 征信报告无用户手机号，电话均为机构客服
    ("credit_report", "LANDLINE"):  0.0,      # 同上
    # 合同
    ("contract", "MONEY"):          0.95,
    ("contract", "BANK_CARD"):      0.92,
    ("contract", "PHONE"):          0.90,
    ("contract", "EMAIL"):          0.90,
    # 借条
    ("iou", "ID_CARD"):             0.99,
    ("iou", "MONEY"):               0.95,
    # 简历
    ("resume", "PHONE"):            0.95,
    ("resume", "EMAIL"):            0.95,
    # 病历
    ("medical_record", "PHONE"):    0.88,
    # 发票
    ("invoice", "MONEY"):           0.95,
    # 银行流水
    ("bank_statement", "BANK_CARD"): 0.98,
    ("bank_statement", "MONEY"):     0.95,
}


# ── 银行卡号验证（Luhn 算法） ──

def _luhn_check(num_str: str) -> bool:
    """Luhn 校验，过滤误检（如普通长数字序列）。"""
    digits = [int(d) for d in num_str if d.isdigit()]
    if len(digits) < 16 or len(digits) > 19:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


# ── 检测结果 ──

@dataclass
class DetectedItem:
    """检测到的单个敏感数据项。"""
    original: str
    type: str
    sensitivity: SensitivityLevel
    start: int                     # 在原始文本中的起始位置
    end: int                       # 在原始文本中的结束位置
    confidence: float = 1.0        # 置信度（0.0~1.0），文档类型上下文可调整


@dataclass
class IsolationResult:
    """认知隔离器的输出。"""
    clean_text: str                                        # 替换占位符后的文本
    redaction_map: dict[str, RedactionEntry] = field(default_factory=dict)
    detected_count: int = 0                                # 检测到的总敏感项数
    stats: dict[str, int] = field(default_factory=dict)    # 按类型统计


# ── 认知隔离器 ──

class CognitiveIsolator:
    """隐私管道第 ① 级：多级检测引擎。

    Level 0: 文档类型语义驱动（关键词触发 + 向量反向匹配 + 模板搜索）
    Level 1: 正则硬模式检测（身份证/银行卡/密码/手机/邮箱/金额）+ 置信度调整
    Level 2: AC 自动机词典（动态积累）
    Level 3: LanceDB entities 回查
    Level 4: NER 模型（CLUENER RoBERTa 兜底：人名/地址/组织）
    """

    def __init__(self, config: dict | None = None):
        """初始化隔离器。

        Args:
            config: 隐私配置（来自 config.yaml 的 privacy 段）
        """
        self._config = config or {}
        self._enabled = self._config.get("enabled", True)
        self._strategy = self._config.get("anonymization_strategy", "uuid")

        # 解析启用的敏感度级别
        levels_cfg = self._config.get("sensitivity_levels", {})
        self._enabled_levels: set[SensitivityLevel] = set()
        if levels_cfg.get("critical", True):
            self._enabled_levels.add(SensitivityLevel.CRITICAL)
        if levels_cfg.get("high", True):
            self._enabled_levels.add(SensitivityLevel.HIGH)
        if levels_cfg.get("medium", True):
            self._enabled_levels.add(SensitivityLevel.MEDIUM)
        if levels_cfg.get("low", False):
            self._enabled_levels.add(SensitivityLevel.LOW)

        # Level 0: 文档类型语义检测器
        self._doc_type_detector = None
        self._field_extractor = None
        try:
            from app.pipeline.doc_type_detector import (
                DocTypeDetector, TemplateSensitiveFieldExtractor,
            )
            locale = self._config.get("locale", "zh")
            self._doc_type_detector = DocTypeDetector(locale)
            self._field_extractor = TemplateSensitiveFieldExtractor()
            logger.info("[隔离器] Level 0 文档类型检测器已加载 (locale=%s)", locale)
        except Exception as e:
            logger.warning("[隔离器] Level 0 加载失败，降级为纯正则: %s", e)

        # Level 2: AC 自动机敏感词检测
        self._ac_detector = None
        try:
            from app.pipeline.ac_dict_detector import ACDictDetector
            self._ac_detector = ACDictDetector()
            # 初始词典为空，运行时通过 add_sensitive_word() 动态积累
            logger.info("[隔离器] Level 2 AC 自动机已初始化")
        except Exception as e:
            logger.warning("[隔离器] Level 2 AC 自动机加载失败: %s", e)

        # Level 3: LanceDB 实体回查
        self._entity_lookback = None
        try:
            from app.pipeline.entity_lookback import EntityLookbackDetector
            self._entity_lookback = EntityLookbackDetector()
            logger.info("[隔离器] Level 3 实体回查已初始化")
        except Exception as e:
            logger.warning("[隔离器] Level 3 实体回查加载失败: %s", e)

        # Level 4: NER 兜底（CLUENER RoBERTa）
        self._ner_detector = None
        try:
            from app.pipeline.ner_detector import NerDetector
            self._ner_detector = NerDetector()
            if self._ner_detector.available:
                logger.info("[隔离器] Level 4 NER 兜底已初始化")
            else:
                self._ner_detector = None
        except Exception as e:
            logger.warning("[隔离器] Level 4 NER 加载失败: %s", e)

    def set_anonymization_strategy(self, strategy: str) -> None:
        """设置脱敏策略（R2 预留接口）。

        Args:
            strategy: "uuid"（UUID 占位符）或 "contextual"（上下文保留）
        """
        self._strategy = strategy
        logger.info("[隔离器] 脱敏策略已切换: %s", strategy)

    def add_sensitive_word(
        self, word: str, word_type: str = "PERSON_NAME",
        sensitivity: str = "critical",
    ) -> None:
        """动态添加敏感词到 AC 自动机词典

        用于运行时积累：Level 0 识别出人名后，自动加入 AC 词典，
        下次出现时 Level 2 直接命中。

        Args:
            word: 敏感词文本
            word_type: 类型
            sensitivity: 敏感度
        """
        if self._ac_detector and word and len(word) >= 2:
            self._ac_detector.add_word(word, word_type, sensitivity)
            self._ac_detector.rebuild()
            logger.debug("[隔离器] AC 词典新增: '%s' (%s)", word, word_type)

    def isolate(
        self,
        text: str,
        session_ctx: SessionPrivacyContext | None = None,
    ) -> IsolationResult:
        """执行多级敏感数据检测与隔离。

        Args:
            text: 用户原始消息或工具返回内容
            session_ctx: 会话级隐私上下文（含已识别的文档类型）

        Returns:
            IsolationResult 包含 clean_text 和 redaction_map
        """
        if not self._enabled or not text.strip():
            return IsolationResult(clean_text=text)

        # 第一步: 多级检测
        detected = self._detect_all_levels(text, session_ctx)

        if not detected:
            return IsolationResult(clean_text=text)

        # 第二步: 按位置倒序排列（从后往前替换，避免偏移量变化）
        detected.sort(key=lambda d: d.start, reverse=True)

        # 去重: 重叠区间只保留优先级更高的（位置靠前的优先）
        detected = self._remove_overlaps(detected)

        # 第三步: 替换为占位符
        redaction_map: dict[str, RedactionEntry] = {}
        clean = text
        stats: dict[str, int] = {}

        for item in detected:
            placeholder = _make_placeholder()
            entry = RedactionEntry(
                original=item.original,
                type=item.type,
                sensitivity=item.sensitivity,
                placeholder=placeholder,
            )
            redaction_map[placeholder] = entry

            # 替换文本
            clean = clean[:item.start] + placeholder + clean[item.end:]

            # 统计
            stats[item.type] = stats.get(item.type, 0) + 1

        logger.info(
            "[隔离器] 检测到 %d 项敏感数据: %s",
            len(redaction_map), stats,
        )

        return IsolationResult(
            clean_text=clean,
            redaction_map=redaction_map,
            detected_count=len(redaction_map),
            stats=stats,
        )

    def _detect_all_levels(
        self,
        text: str,
        session_ctx: SessionPrivacyContext | None = None,
    ) -> list[DetectedItem]:
        """多级检测引擎：按优先级执行各级检测器。"""
        all_detected: list[DetectedItem] = []
        doc_type: str | None = None

        # Level 0: 文档类型语义检测
        if self._doc_type_detector and self._field_extractor:
            doc_type = session_ctx.doc_type if session_ctx else None
            template = None

            if doc_type:
                # 会话中已识别过文档类型，直接使用
                template = self._doc_type_detector.get_template(doc_type)
            else:
                # 尝试从当前文本识别文档类型
                template = self._doc_type_detector.detect_doc_type(text)
                if template and session_ctx:
                    doc_type = template.type
                    session_ctx.doc_type = template.type
                    # 首次命中文档类型 → 设置隐私提醒，让 LLM 自然表达
                    session_ctx.privacy_notice = (
                        f"用户提交的内容涉及「{template.triggers[0]}」类文档，"
                        "可能包含个人隐私信息。请在回复中自然地告知用户你会保护好隐私信息再处理，"
                        "不要用系统通知的语气，像朋友一样说就好。"
                    )

            if template:
                from app.pipeline.doc_type_detector import DetectedSensitiveField

                # 从文件路径/文件名中提取人名（用户输入阶段）
                name_fields, _ = self._doc_type_detector.extract_names_from_filename(text)
                for nf in name_fields:
                    all_detected.append(DetectedItem(
                        original=nf.original,
                        type=nf.type,
                        sensitivity=nf.sensitivity,
                        start=nf.start,
                        end=nf.end,
                        confidence=0.95,
                    ))

                # 按模板搜索标签后的敏感值（工具返回的长文本）
                doc_fields = self._field_extractor.extract(text, template)
                for df in doc_fields:
                    all_detected.append(DetectedItem(
                        original=df.original,
                        type=df.type,
                        sensitivity=df.sensitivity,
                        start=df.start,
                        end=df.end,
                        confidence=0.95,
                    ))

        # Level 1: 正则检测（带文档类型置信度调整）
        all_detected.extend(self._detect_all(text, doc_type=doc_type))

        # Level 2: AC 自动机词典
        if self._ac_detector:
            ac_items = self._ac_detector.detect(text)
            for item in ac_items:
                all_detected.append(DetectedItem(
                    original=item.original,
                    type=item.type,
                    sensitivity=item.sensitivity,
                    start=item.start,
                    end=item.end,
                    confidence=0.90,
                ))

        # Level 3: LanceDB 回查（同步包装，因为 isolate() 本身是同步的）
        # 注：实际异步调用在 pipeline 层面处理，这里跳过
        # entity_lookback 的 detect() 是 async，需要在调用方 await

        # Level 4: NER 兜底（CLUENER RoBERTa）
        if self._ner_detector:
            ner_items = self._ner_detector.detect(text)
            for item in ner_items:
                # 敏感度过滤：用户可关闭 medium/high 级别
                if item.sensitivity not in self._enabled_levels:
                    continue
                all_detected.append(DetectedItem(
                    original=item.original,
                    type=item.type,
                    sensitivity=item.sensitivity,
                    start=item.start,
                    end=item.end,
                    confidence=item.confidence,
                ))

        # 动态积累：将本次检测到的人名加入 AC 词典
        for item in all_detected:
            if item.type == "PERSON_NAME":
                self.add_sensitive_word(item.original, item.type, item.sensitivity.value)

        return all_detected

    def _detect_all(self, text: str, doc_type: str | None = None) -> list[DetectedItem]:
        """使用所有正则规则检测敏感数据，按文档类型上下文调整置信度。"""
        detected: list[DetectedItem] = []

        for pattern, entity_type, sensitivity in _DETECTION_RULES:
            # 跳过未启用的敏感度级别
            if sensitivity not in self._enabled_levels:
                continue

            for match in pattern.finditer(text):
                # SECRET 类型使用第一个捕获组（密码值本身）
                if entity_type == "SECRET" and match.lastindex:
                    original = match.group(1)
                    start = match.start(1)
                    end = match.end(1)
                else:
                    original = match.group()
                    start = match.start()
                    end = match.end()

                # 银行卡号额外 Luhn 校验
                if entity_type == "BANK_CARD":
                    digits_only = re.sub(r"[\s-]", "", original)
                    if not _luhn_check(digits_only):
                        continue
                    # 去除 16 位以下的匹配（可能是普通数字）
                    if len(digits_only) < 16:
                        continue

                # 文档类型上下文置信度调整
                if doc_type:
                    confidence = _CONFIDENCE_BOOST.get(
                        (doc_type, entity_type), _DEFAULT_REGEX_CONFIDENCE,
                    )
                else:
                    confidence = _DEFAULT_REGEX_CONFIDENCE

                # 置信度为 0 表示该文档类型下此实体类型不应脱敏（如征信报告中的电话号码）
                if confidence <= 0:
                    continue

                detected.append(DetectedItem(
                    original=original,
                    type=entity_type,
                    sensitivity=sensitivity,
                    start=start,
                    end=end,
                    confidence=confidence,
                ))

        return detected

    @staticmethod
    def _remove_overlaps(items: list[DetectedItem]) -> list[DetectedItem]:
        """去除重叠检测项（保留优先级更高的）。

        items 已按 start 倒序排列。
        优先级: CRITICAL > HIGH > MEDIUM > LOW，同级别时按 confidence 选高的。
        """
        _priority = {
            SensitivityLevel.CRITICAL: 4,
            SensitivityLevel.HIGH: 3,
            SensitivityLevel.MEDIUM: 2,
            SensitivityLevel.LOW: 1,
        }

        def _score(item: DetectedItem) -> tuple[int, float]:
            """(敏感度优先级, 置信度) 用于比较。"""
            return (_priority[item.sensitivity], item.confidence)

        # 按 start 正序处理
        items_sorted = sorted(items, key=lambda d: d.start)
        result: list[DetectedItem] = []

        for item in items_sorted:
            # 找出所有与 item 有重叠的已接受项
            overlapping = [
                a for a in result
                if item.start < a.end and item.end > a.start
            ]

            if not overlapping:
                # 无冲突，直接加入
                result.append(item)
            elif all(_score(item) > _score(a) for a in overlapping):
                # 新项优先级高于所有冲突项 → 移除全部冲突项，加入新项
                for a in overlapping:
                    result.remove(a)
                result.append(item)
            # else: 至少一个已接受项的优先级 ≥ 新项，跳过

        # 恢复倒序（用于从后往前替换）
        result.sort(key=lambda d: d.start, reverse=True)
        return result

    # ── 异步接口（向量反向匹配文档类型） ──

    async def warmup_vectors(self) -> None:
        """预热：预计算文档类型 trigger 的向量表示。

        应在应用启动后、Embedding 服务初始化完成后调用。
        """
        if not self._doc_type_detector:
            return
        try:
            from app.infrastructure.embedding import get_embedding_service
            embed_svc = get_embedding_service()
            await self._doc_type_detector.warmup_vectors(embed_svc)
            logger.info("[隔离器] Level 0 向量预热完成")
        except RuntimeError:
            logger.debug("[隔离器] Embedding 服务未初始化，跳过向量预热")
        except Exception as e:
            logger.warning("[隔离器] 向量预热失败: %s", e)

    async def detect_doc_type_async(self, text: str) -> str | None:
        """异步文档类型检测（关键词 + 向量反向匹配）。

        在 chat_service 调用 sync isolate() 之前调用此方法，
        将结果写入 session_ctx.doc_type，isolate() 会直接使用。

        Returns:
            文档类型标识（如 "credit_report"），未命中返回 None
        """
        if not self._doc_type_detector:
            return None

        # 先试关键词匹配（sync，极快）
        tpl = self._doc_type_detector.detect_doc_type(text)
        if tpl:
            return tpl.type

        # 关键词未命中 → 尝试向量反向匹配
        try:
            from app.infrastructure.embedding import get_embedding_service
            embed_svc = get_embedding_service()
            tpl = await self._doc_type_detector.detect_by_vector(text, embed_svc)
            if tpl:
                logger.info("[隔离器] 向量反向匹配命中: %s", tpl.type)
                return tpl.type
        except RuntimeError:
            pass  # Embedding 未初始化
        except Exception as e:
            logger.debug("[隔离器] 向量检测失败: %s", e)

        return None
