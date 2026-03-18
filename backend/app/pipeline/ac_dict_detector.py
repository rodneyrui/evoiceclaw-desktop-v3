"""AC 自动机敏感词检测器 — 认知隔离器 Level 2

职责: 多模式匹配用户自定义敏感词，以及从实体历史中动态积累的敏感值。

特点:
  - 基于 Aho-Corasick 算法，O(n) 时间扫描
  - 支持动态添加词条（新识别的人名自动加入）
  - 词典来源：用户手动配置 + LanceDB entities 自动导入

依赖: pyahocorasick
"""

import logging

from app.domain.models import SensitivityLevel

logger = logging.getLogger("evoiceclaw.pipeline.ac_dict")


class DetectedDictItem:
    """AC 自动机检测到的敏感项"""
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
        self.source = "ac_dict"


class ACDictDetector:
    """AC 自动机敏感词检测器

    使用方式:
      1. 初始化后调用 add_word() 或 load_words() 添加词条
      2. 调用 build() 构建自动机
      3. 调用 detect() 检测文本
      4. 运行时可调用 add_word() + rebuild() 动态扩充词典
    """

    def __init__(self):
        self._automaton = None
        self._words: dict[str, tuple[str, str]] = {}  # word → (type, sensitivity)
        self._built = False

    def add_word(
        self, word: str, word_type: str = "PERSON_NAME",
        sensitivity: str = "critical",
    ) -> None:
        """添加一个敏感词

        Args:
            word: 敏感词文本
            word_type: 类型（PERSON_NAME / ID_CARD / ...）
            sensitivity: 敏感度（critical / high / medium / low）
        """
        if word and len(word) >= 2:
            self._words[word] = (word_type, sensitivity)
            self._built = False  # 需要重建

    def load_words(self, words: list[tuple[str, str, str]]) -> None:
        """批量加载敏感词

        Args:
            words: [(词, 类型, 敏感度), ...]
        """
        for word, wtype, sensitivity in words:
            self.add_word(word, wtype, sensitivity)

    def build(self) -> None:
        """构建 AC 自动机（添加完词条后调用）"""
        if not self._words:
            self._built = False
            return

        try:
            import ahocorasick
        except ImportError:
            logger.warning("[AC词典] pyahocorasick 未安装，AC 自动机不可用")
            return

        self._automaton = ahocorasick.Automaton()
        for word, (wtype, sensitivity) in self._words.items():
            self._automaton.add_word(word, (word, wtype, sensitivity))
        self._automaton.make_automaton()
        self._built = True
        logger.info("[AC词典] 自动机已构建，词条数: %d", len(self._words))

    def rebuild(self) -> None:
        """重建自动机（动态添加词条后调用）"""
        self.build()

    @property
    def word_count(self) -> int:
        return len(self._words)

    def detect(self, text: str) -> list[DetectedDictItem]:
        """检测文本中的敏感词

        Args:
            text: 待检测文本

        Returns:
            检测到的敏感项列表
        """
        if not self._built or self._automaton is None:
            return []

        detected: list[DetectedDictItem] = []
        for end_idx, (word, wtype, sensitivity) in self._automaton.iter(text):
            start = end_idx - len(word) + 1
            detected.append(DetectedDictItem(
                original=word,
                type=wtype,
                sensitivity=SensitivityLevel(sensitivity),
                start=start,
                end=end_idx + 1,
            ))

        if detected:
            logger.debug("[AC词典] 检测到 %d 个敏感词命中", len(detected))

        return detected
