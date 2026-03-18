"""AC 自动机 + 实体回查 + 动态积累测试"""

from app.pipeline.ac_dict_detector import ACDictDetector
from app.domain.models import SensitivityLevel


class TestACDictDetector:
    """AC 自动机敏感词检测"""

    def test_basic_detect(self):
        """基本检测：添加词条 → 构建 → 检测"""
        ac = ACDictDetector()
        ac.add_word("穆蕴", "PERSON_NAME", "critical")
        ac.add_word("张三", "PERSON_NAME", "critical")
        ac.build()

        items = ac.detect("帮我分析穆蕴的征信报告")
        assert len(items) == 1
        assert items[0].original == "穆蕴"
        assert items[0].type == "PERSON_NAME"

    def test_multiple_matches(self):
        """多个匹配"""
        ac = ACDictDetector()
        ac.load_words([
            ("张三", "PERSON_NAME", "critical"),
            ("李四", "PERSON_NAME", "critical"),
        ])
        ac.build()

        items = ac.detect("张三和李四的合同")
        assert len(items) == 2
        names = {i.original for i in items}
        assert names == {"张三", "李四"}

    def test_no_match(self):
        """无匹配"""
        ac = ACDictDetector()
        ac.add_word("穆蕴", "PERSON_NAME", "critical")
        ac.build()

        items = ac.detect("今天天气不错")
        assert len(items) == 0

    def test_empty_dict(self):
        """空词典不报错"""
        ac = ACDictDetector()
        ac.build()
        items = ac.detect("任何文本")
        assert len(items) == 0

    def test_not_built(self):
        """未构建时检测返回空"""
        ac = ACDictDetector()
        ac.add_word("穆蕴", "PERSON_NAME", "critical")
        items = ac.detect("穆蕴的征信报告")
        assert len(items) == 0

    def test_rebuild_after_add(self):
        """动态添加后重建"""
        ac = ACDictDetector()
        ac.add_word("张三", "PERSON_NAME", "critical")
        ac.build()

        # 初始只能匹配张三
        assert len(ac.detect("穆蕴和张三")) == 1

        # 动态添加穆蕴
        ac.add_word("穆蕴", "PERSON_NAME", "critical")
        ac.rebuild()

        # 现在两个都能匹配
        assert len(ac.detect("穆蕴和张三")) == 2

    def test_word_count(self):
        ac = ACDictDetector()
        assert ac.word_count == 0
        ac.add_word("张三", "PERSON_NAME", "critical")
        assert ac.word_count == 1
        ac.add_word("李四", "PERSON_NAME", "critical")
        assert ac.word_count == 2

    def test_short_word_filtered(self):
        """单字词被过滤"""
        ac = ACDictDetector()
        ac.add_word("张", "PERSON_NAME", "critical")
        assert ac.word_count == 0

    def test_position_correct(self):
        """检测位置正确"""
        ac = ACDictDetector()
        ac.add_word("穆蕴", "PERSON_NAME", "critical")
        ac.build()

        text = "这是穆蕴的文件"
        items = ac.detect(text)
        assert len(items) == 1
        assert text[items[0].start:items[0].end] == "穆蕴"


class TestIsolatorACIntegration:
    """认知隔离器 AC 自动机集成测试"""

    def setup_method(self):
        from app.pipeline.cognitive_isolator import CognitiveIsolator
        self.isolator = CognitiveIsolator({"locale": "zh"})

    def test_dynamic_accumulation(self):
        """动态积累：Level 0 识别人名后，AC 词典自动命中"""
        from app.domain.models import SessionPrivacyContext

        ctx = SessionPrivacyContext()
        # 第一次：通过文件名识别人名
        self.isolator.isolate(
            "分析 ~/穆蕴 征信报告.pdf",
            session_ctx=ctx,
        )

        # 第二次：纯文本中的人名，AC 词典应该命中
        result = self.isolator.isolate("穆蕴最近怎么样")
        assert "穆蕴" not in result.clean_text

    def test_ac_word_added_from_template_extract(self):
        """模板提取的人名也加入 AC 词典"""
        from app.domain.models import SessionPrivacyContext

        ctx = SessionPrivacyContext(doc_type="credit_report")
        # 模板提取
        self.isolator.isolate(
            "姓名：穆蕴\n证件号码：110101199001011234",
            session_ctx=ctx,
        )

        # AC 词典应该已有 "穆蕴"
        assert self.isolator._ac_detector is not None
        assert self.isolator._ac_detector.word_count > 0
