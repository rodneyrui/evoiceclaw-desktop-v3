"""LanceDB 实体回查检测器 — 认知隔离器 Level 3

职责: 从 LanceDB entities 表回查已知的敏感实体（主要是 PERSON 类型），
在当前文本中搜索匹配并标记。

核心循环:
  1. 用户首次提到 "穆蕴" → Level 0/2 识别 → 脱敏 → entity_mapper 存入 LanceDB
  2. 下次 "穆蕴" 出现（即使不在文档上下文中）→ Level 3 回查命中 → 脱敏

这形成了正向积累：识别一次，永久保护。
"""

import logging

from app.domain.models import SensitivityLevel

logger = logging.getLogger("evoiceclaw.pipeline.entity_lookback")


class DetectedLookbackItem:
    """实体回查检测到的敏感项"""
    __slots__ = ("original", "type", "sensitivity", "start", "end", "source")

    def __init__(
        self, original: str, type: str, sensitivity: SensitivityLevel,
        start: int, end: int,
    ):
        self.original = original
        self.type = type
        self.sensitivity = sensitivity
        self.start = start
        self.end = end
        self.source = "entity_lookback"


class EntityLookbackDetector:
    """从 LanceDB entities 表回查已知敏感实体

    查询该工作区下所有 PERSON 类型实体，在文本中做字符串匹配。
    """

    async def detect(
        self, text: str, workspace_id: str = "global",
    ) -> list[DetectedLookbackItem]:
        """检查文本中是否包含已知的敏感实体

        Args:
            text: 待检测文本
            workspace_id: 工作区 ID

        Returns:
            检测到的敏感项列表
        """
        if not text.strip():
            return []

        try:
            from app.infrastructure.vector_db import get_table

            table = get_table("entities")
            # 查询该工作区下所有 PERSON 类型实体
            known_persons = (
                table.search()
                .where(
                    f"type = 'PERSON' AND workspace_id = '{workspace_id}'",
                    prefilter=True,
                )
                .limit(500)
                .to_list()
            )
        except Exception as e:
            logger.debug("[实体回查] 查询 LanceDB 失败（可能表不存在）: %s", e)
            return []

        detected: list[DetectedLookbackItem] = []
        for person in known_persons:
            name = person.get("text", "")
            if not name or len(name) < 2:
                continue

            # 在文本中搜索所有出现位置
            idx = text.find(name)
            while idx != -1:
                detected.append(DetectedLookbackItem(
                    original=name,
                    type="PERSON_NAME",
                    sensitivity=SensitivityLevel.CRITICAL,
                    start=idx,
                    end=idx + len(name),
                ))
                idx = text.find(name, idx + 1)

        if detected:
            logger.info(
                "[实体回查] 检测到 %d 个已知实体命中",
                len(detected),
            )

        return detected
