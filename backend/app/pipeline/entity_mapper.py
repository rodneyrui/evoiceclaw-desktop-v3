"""实体类别映射器（Entity Mapper）— 隐私管道第 ② 级

职责: 从清洗后的文本中识别实体，向量化后存入 LanceDB entities 表。
为后续的记忆注入和上下文压缩提供实体上下文。

输入: clean_text（经认知隔离器处理后的文本）
输出: EntityMapResult { entities, annotated_text }

实体类型:
  PERSON — 人名
  ORG    — 组织/公司
  LOCATION — 地点
  PRODUCT — 产品/品牌
  EVENT   — 事件
  OTHER   — 其他实体
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from app.domain.models import RedactionEntry

logger = logging.getLogger("evoiceclaw.pipeline.entity_mapper")


# ── 实体类型 ──

ENTITY_TYPES = frozenset([
    "PERSON", "ORG", "LOCATION", "PRODUCT", "EVENT", "OTHER",
])


@dataclass
class Entity:
    """检测到的实体。"""
    id: str
    text: str
    type: str              # PERSON / ORG / LOCATION / ...
    category: str = ""     # 细分类别
    is_new: bool = False   # 是否为首次出现的新实体


@dataclass
class EntityMapResult:
    """实体映射器的输出。"""
    entities: list[Entity] = field(default_factory=list)
    entity_count: int = 0


# ── 简单规则检测（Phase 2 初版，后续可接入 NER 模型） ──

# 中文人名模式（2-4字姓名，姓氏集合）
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


class EntityMapper:
    """隐私管道第 ② 级：实体检测与映射。

    当前实现: 基于规则的轻量检测（中文人名、组织后缀、地点后缀）。
    未来扩展: 可接入 NER 模型或 LLM 抽取实体。
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        # 已知实体缓存（避免重复向量化）
        self._known_entities: dict[str, Entity] = {}

    async def map_entities(self, text: str) -> EntityMapResult:
        """从文本中提取实体。

        Args:
            text: 清洗后的文本（已经过认知隔离器处理）

        Returns:
            EntityMapResult
        """
        if not text.strip():
            return EntityMapResult()

        detected: list[Entity] = []

        # 规则检测
        detected.extend(self._detect_by_rules(text))

        # 去重
        seen: set[str] = set()
        unique: list[Entity] = []
        for entity in detected:
            key = f"{entity.text}:{entity.type}"
            if key not in seen:
                seen.add(key)
                unique.append(entity)

        return EntityMapResult(
            entities=unique,
            entity_count=len(unique),
        )

    def entities_from_redaction_map(
        self, redaction_map: "dict[str, RedactionEntry]",
    ) -> list[Entity]:
        """从脱敏映射表中提取人名实体。

        认知隔离器 Level 0/1 已将人名替换为占位符，clean_text 中不再出现，
        需从 redaction_map 直接提取，确保 L3 实体回查能检索到这些人名。

        Args:
            redaction_map: 认知隔离器输出的占位符→条目映射表

        Returns:
            Entity 列表（仅含 PERSON 类型的条目）
        """
        entities: list[Entity] = []
        for _placeholder, entry in redaction_map.items():
            if entry.type != "PERSON_NAME":
                continue
            name = entry.original
            entities.append(Entity(
                id=str(uuid4()),
                text=name,
                type="PERSON",
                is_new=name not in self._known_entities,
            ))
            self._known_entities[name] = entities[-1]
        return entities

    async def persist_entities(self, entities: list[Entity], workspace_id: str = "global") -> int:
        """将实体持久化到 LanceDB entities 表。

        Args:
            entities: 要存储的实体列表
            workspace_id: 工作区 ID（宪法第3/6条，记忆按工作区隔离）

        Returns:
            新增/更新的实体数
        """
        if not entities:
            return 0

        try:
            from app.infrastructure.vector_db import get_table
            from app.infrastructure.embedding import get_embedding_service

            table = get_table("entities")
            embed_svc = get_embedding_service()

            # 批量向量化
            texts = [e.text for e in entities]
            vectors = await embed_svc.embed_batch(texts)

            now = datetime.now().isoformat()
            rows = []
            for entity, vector in zip(entities, vectors):
                rows.append({
                    "id": entity.id,
                    "text": entity.text,
                    "type": entity.type,
                    "category": entity.category,
                    "vector": vector,
                    "metadata": json.dumps({"source": "pipeline"}, ensure_ascii=False),
                    "last_seen": now,
                    "frequency": 1,
                    "workspace_id": workspace_id,  # 工作区隔离
                })

            # merge_insert: 按 text+type 做 upsert
            table.merge_insert("text") \
                .when_matched_update_all() \
                .when_not_matched_insert_all() \
                .execute(rows)

            logger.info("[实体映射] 持久化 %d 个实体", len(rows))
            return len(rows)

        except Exception as e:
            logger.warning("[实体映射] 持久化失败: %s", e)
            return 0

    def _detect_by_rules(self, text: str) -> list[Entity]:
        """基于规则的实体检测。"""
        entities: list[Entity] = []

        # 中文人名（保守策略：仅检测带称谓/职务的人名）
        # 模式1: 姓 + 称谓（张先生、李女士、王总 等）
        title_pattern = re.compile(
            r'([\u4e00-\u9fff])'
            r'[\u4e00-\u9fff]{0,2}'
            r'(?:先生|女士|小姐|老师|教授|医生|博士|院士|总|经理|主任|局长|处长|科长|部长|同学|同志)'
        )
        for match in title_pattern.finditer(text):
            if match.group()[0] in _SURNAME_SET:
                name = match.group()
                entities.append(Entity(
                    id=str(uuid4()),
                    text=name,
                    type="PERSON",
                    is_new=name not in self._known_entities,
                ))
                self._known_entities[name] = entities[-1]

        # 模式2: 明确引用格式（"张三"、叫张三、名叫张三）
        ref_pattern = re.compile(
            r'(?:叫|名叫|名字是|我是|他是|她是|这是)\s*'
            r'([\u4e00-\u9fff]{2,4})'
        )
        for match in ref_pattern.finditer(text):
            name = match.group(1)
            if name[0] in _SURNAME_SET and not self._is_common_word(name):
                entities.append(Entity(
                    id=str(uuid4()),
                    text=name,
                    type="PERSON",
                    is_new=name not in self._known_entities,
                ))
                self._known_entities[name] = entities[-1]

        # 组织名称（含公司/集团/大学等后缀）
        org_pattern = re.compile(
            r'[\u4e00-\u9fff]{2,10}(?:公司|集团|银行|大学|学院|医院|研究所|研究院|基金会|协会|委员会)'
        )
        for match in org_pattern.finditer(text):
            org_name = match.group()
            entities.append(Entity(
                id=str(uuid4()),
                text=org_name,
                type="ORG",
                is_new=org_name not in self._known_entities,
            ))

        # 地点（省/市/区/县/镇/村/路/街）
        loc_pattern = re.compile(
            r'[\u4e00-\u9fff]{2,6}(?:省|市|区|县|镇|村|路|街|大道|广场|小区)'
        )
        for match in loc_pattern.finditer(text):
            loc_name = match.group()
            entities.append(Entity(
                id=str(uuid4()),
                text=loc_name,
                type="LOCATION",
                is_new=loc_name not in self._known_entities,
            ))

        return entities

    @staticmethod
    def _is_common_word(word: str) -> bool:
        """检查是否为常见非人名词语，减少误检。"""
        common = frozenset([
            "我们", "你们", "他们", "她们", "什么", "怎么", "这个", "那个",
            "可以", "没有", "已经", "因为", "所以", "但是", "如果", "虽然",
            "需要", "知道", "觉得", "认为", "看到", "听到", "应该", "可能",
            "今天", "明天", "昨天", "现在", "以前", "以后", "一些", "一个",
            "这里", "那里", "这些", "那些", "哪里", "怎样", "为什么", "不是",
            "还是", "或者", "而且", "然后", "之后", "之前", "其实", "当然",
            "一直", "一样", "一起", "自己", "大家", "一定", "不会", "不要",
            "很多", "非常", "特别", "真的", "就是", "只是", "问题", "时候",
        ])
        return word in common
