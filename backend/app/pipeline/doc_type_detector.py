"""文档类型语义检测器（Doc Type Detector）— 认知隔离器 Level 0

职责: 识别文本中的文档类型，按预定义模板搜索敏感字段并标记。

核心思路:
  不用通用 NER 去"猜"哪个词是人名。文档类型本身就是敏感字段的索引——
  通过识别文档类型，推断出里面一定包含哪些敏感字段，然后按模板搜索替换。

人名识别策略:
  用户输入阶段 — 从文件路径/附件文件名中提取（文件名去掉 trigger、日期、扩展名 = 人名）
  工具返回阶段 — 按文档类型模板搜索 "姓名：" 等标签后的值

输入: 文本 + 可选的会话上下文
输出: list[DetectedSensitiveField] — 检测到的敏感字段
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import yaml

from app.domain.models import SensitivityLevel

if TYPE_CHECKING:
    from app.infrastructure.embedding import EmbeddingService

logger = logging.getLogger("evoiceclaw.pipeline.doc_type_detector")

# ── 配置目录 ──
_CONFIGS_DIR = Path(__file__).parent.parent.parent / "data" / "configs"


# ── 数据结构 ──

@dataclass
class SensitiveFieldDef:
    """敏感字段定义"""
    labels: list[str]
    type: str               # PERSON_NAME / ID_CARD / BANK_CARD / ...
    sensitivity: str         # critical / high / medium / low


@dataclass
class DocTypeTemplate:
    """文档类型模板"""
    type: str                           # credit_report / contract / ...
    triggers: list[str]                 # 触发关键词
    sensitive_fields: list[SensitiveFieldDef] = field(default_factory=list)


@dataclass
class DetectedSensitiveField:
    """检测到的敏感字段（Level 0 输出）"""
    original: str
    type: str
    sensitivity: SensitivityLevel
    start: int
    end: int
    source: str = "doc_type_semantic"   # 检测来源标识


# ── 模板加载 ──

def load_templates(locale: str = "zh") -> list[DocTypeTemplate]:
    """从 YAML 配置文件加载文档类型模板

    Args:
        locale: 语言代码（zh / en）
    """
    config_path = _CONFIGS_DIR / locale / "doc_type_templates.yaml"
    if not config_path.exists():
        logger.warning("[DocType] 模板文件不存在: %s", config_path)
        return []

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    templates = []
    for item in data.get("templates", []):
        fields = []
        for fd in item.get("sensitive_fields", []):
            fields.append(SensitiveFieldDef(
                labels=fd["labels"],
                type=fd["type"],
                sensitivity=fd["sensitivity"],
            ))
        templates.append(DocTypeTemplate(
            type=item["type"],
            triggers=item["triggers"],
            sensitive_fields=fields,
        ))

    logger.info("[DocType] 加载 %d 个文档类型模板 (locale=%s)", len(templates), locale)
    return templates


# ── 中文姓氏集合（用于 trigger 附近人名搜索） ──

_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
    "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
    "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
    "虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚"
    "程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓"
    "牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙"
    "叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴欧"
)
_SURNAME_SET = frozenset(_SURNAMES)


# ── 向量相似度 ──

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── 向量匹配阈值 ──
_VECTOR_MATCH_THRESHOLD = 0.65


# ── 核心类 ──

class DocTypeDetector:
    """文档类型检测器

    通过关键词触发识别文档类型，返回对应的敏感字段模板。
    """

    def __init__(self, locale: str = "zh"):
        self._locale = locale
        self._templates = load_templates(locale)
        # trigger → template 快速索引
        self._trigger_index: dict[str, DocTypeTemplate] = {}
        for tpl in self._templates:
            for trigger in tpl.triggers:
                self._trigger_index[trigger.lower()] = tpl

        # 向量反向匹配（异步预热后可用）
        self._trigger_vectors: dict[str, list[float]] = {}  # trigger → embedding
        self._vectors_ready = False

    def detect_doc_type(self, text: str) -> DocTypeTemplate | None:
        """关键词触发检测文档类型（<1ms）"""
        text_lower = text.lower()
        for trigger, tpl in self._trigger_index.items():
            if trigger in text_lower:
                logger.debug("[DocType] 命中: '%s' → %s", trigger, tpl.type)
                return tpl
        return None

    def get_template(self, doc_type: str) -> DocTypeTemplate | None:
        """按类型名获取模板"""
        for tpl in self._templates:
            if tpl.type == doc_type:
                return tpl
        return None

    @property
    def vectors_ready(self) -> bool:
        """向量预热是否完成"""
        return self._vectors_ready

    async def warmup_vectors(self, embed_svc: EmbeddingService) -> None:
        """预计算所有 trigger 关键词的向量表示

        Args:
            embed_svc: Embedding 服务实例
        """
        triggers = list(self._trigger_index.keys())
        if not triggers:
            return

        vectors = await embed_svc.embed_batch(triggers)
        for trigger, vec in zip(triggers, vectors):
            self._trigger_vectors[trigger] = vec

        self._vectors_ready = True
        logger.info(
            "[DocType] 向量预热完成: %d 个 trigger 已向量化",
            len(triggers),
        )

    async def detect_by_vector(
        self, text: str, embed_svc: EmbeddingService,
    ) -> DocTypeTemplate | None:
        """向量反向匹配文档类型（语义路径）

        当关键词触发未命中时，将用户输入向量化，
        与预存的 trigger 向量做余弦相似度匹配。

        Args:
            text: 用户输入文本
            embed_svc: Embedding 服务实例

        Returns:
            匹配的文档类型模板，未命中返回 None
        """
        if not self._vectors_ready:
            return None

        # 向量化用户输入
        query_vec = await embed_svc.embed(text)

        # 找最高相似度的 trigger
        best_sim = 0.0
        best_trigger = ""
        for trigger, vec in self._trigger_vectors.items():
            sim = _cosine_similarity(query_vec, vec)
            if sim > best_sim:
                best_sim = sim
                best_trigger = trigger

        if best_sim >= _VECTOR_MATCH_THRESHOLD:
            tpl = self._trigger_index[best_trigger]
            logger.info(
                "[DocType] 向量匹配: '%s' → %s (sim=%.3f, trigger='%s')",
                text[:30], tpl.type, best_sim, best_trigger,
            )
            return tpl

        logger.debug(
            "[DocType] 向量匹配未达阈值: best_sim=%.3f (阈值=%.2f)",
            best_sim, _VECTOR_MATCH_THRESHOLD,
        )
        return None

    def extract_names_from_filename(
        self, text: str,
    ) -> tuple[list[DetectedSensitiveField], DocTypeTemplate | None]:
        """从用户消息中的文件路径/文件名提取人名

        策略：
          1. 从文本中提取文件路径（~/xxx/穆蕴 征信报告.pdf）
          2. 取文件名部分，去掉扩展名
          3. 文件名中命中文档类型 trigger → 去掉 trigger、日期数字 → 剩余部分即人名

        Returns:
            (检测到的敏感字段列表, 命中的文档类型模板)
        """
        detected: list[DetectedSensitiveField] = []
        matched_template: DocTypeTemplate | None = None

        # 提取文件路径（支持 ~/xxx、/xxx、C:\\xxx、以及纯文件名.pdf/.docx 等）
        file_paths = re.findall(
            r'(?:[~/][\w\u4e00-\u9fff./\\: -]+\.(?:pdf|docx?|xlsx?|txt|csv|png|jpg))'
            r'|(?:[\w\u4e00-\u9fff -]+\.(?:pdf|docx?|xlsx?|txt|csv))',
            text, re.IGNORECASE,
        )

        for fpath in file_paths:
            # 取文件名（去路径、去扩展名）
            fname = PurePosixPath(fpath).stem
            fname_lower = fname.lower()

            # 在文件名中搜索 trigger
            for trigger, tpl in self._trigger_index.items():
                if trigger in fname_lower:
                    matched_template = tpl
                    # 用原始大小写版本去掉所有 trigger 变体
                    remaining_original = fname
                    for t in tpl.triggers:
                        remaining_original = remaining_original.replace(t, "")

                    # 去掉日期数字（2026、0105、20260105 等）
                    remaining_original = re.sub(
                        r'\d{4,8}', '', remaining_original,
                    ).strip()
                    # 去掉多余的空格和分隔符
                    remaining_original = re.sub(
                        r'[\s_\-]+', ' ', remaining_original,
                    ).strip()

                    if remaining_original and len(remaining_original) >= 2:
                        # 找到这个名字在原始文本中的位置
                        name_start = text.find(remaining_original)
                        if name_start == -1:
                            name_start = text.find(fpath)
                        name_end = name_start + len(remaining_original) if name_start >= 0 else 0

                        detected.append(DetectedSensitiveField(
                            original=remaining_original,
                            type="PERSON_NAME",
                            sensitivity=SensitivityLevel.CRITICAL,
                            start=max(0, name_start),
                            end=max(0, name_end),
                            source="filename_extraction",
                        ))
                        logger.info(
                            "[DocType] 文件名提取人名: '%s' (from '%s', doc_type=%s)",
                            remaining_original, fname, tpl.type,
                        )
                    break  # 一个文件名只匹配一个 trigger

        return detected, matched_template


class TemplateSensitiveFieldExtractor:
    """按文档类型模板提取敏感字段值

    在工具返回的长文本中，按模板定义的 label 搜索 "标签：值" 模式，
    提取标签后面的值作为敏感数据。
    """

    def extract(self, text: str, template: DocTypeTemplate) -> list[DetectedSensitiveField]:
        """从文本中按模板搜索敏感字段

        Args:
            text: 待搜索文本（通常是工具返回的 PDF 内容）
            template: 文档类型模板
        """
        detected: list[DetectedSensitiveField] = []

        for field_def in template.sensitive_fields:
            sensitivity = SensitivityLevel(field_def.sensitivity)
            for label in field_def.labels:
                # 搜索 "标签：值" 或 "标签: 值" 或 "标签 值" 模式
                pattern = re.compile(
                    rf'{re.escape(label)}\s*[:：\s]\s*(.+?)(?:\s{{2,}}|，|,|。|；|;|\n|$)'
                )
                for match in pattern.finditer(text):
                    value = match.group(1).strip()
                    # 过滤太短或太长的值（避免误匹配）
                    if len(value) < 2 or len(value) > 50:
                        continue
                    detected.append(DetectedSensitiveField(
                        original=value,
                        type=field_def.type,
                        sensitivity=sensitivity,
                        start=match.start(1),
                        end=match.end(1),
                        source="doc_type_template",
                    ))

        if detected:
            logger.info(
                "[DocType] 模板提取: doc_type=%s 检测到 %d 个敏感字段",
                template.type, len(detected),
            )
        return detected
