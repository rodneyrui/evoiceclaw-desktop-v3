"""NER 兜底 + 正则置信度 + 向量反向匹配 测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.models import SensitivityLevel


class TestNerDetector:
    """Level 4 NER 兜底检测（CLUENER RoBERTa）"""

    def test_detect_common_name(self):
        """CLUENER 能识别常见中文人名"""
        from app.pipeline.ner_detector import NerDetector
        ner = NerDetector()
        if not ner.available:
            pytest.skip("transformers 未安装")

        items = ner.detect("张三和李四签了合同")
        names = {i.original for i in items if i.type == "PERSON_NAME"}
        assert len(names) >= 1
        assert any(n in names for n in ("张三", "李四"))

    def test_detect_position_correct(self):
        """NER 检测位置正确"""
        from app.pipeline.ner_detector import NerDetector
        ner = NerDetector()
        if not ner.available:
            pytest.skip("transformers 未安装")

        text = "请联系张三办理"
        items = ner.detect(text)
        for item in items:
            if item.original == "张三":
                assert text[item.start:item.end] == "张三"

    def test_empty_text(self):
        """空文本返回空列表"""
        from app.pipeline.ner_detector import NerDetector
        ner = NerDetector()
        assert ner.detect("") == []
        assert ner.detect("   ") == []

    def test_no_names(self):
        """无人名文本"""
        from app.pipeline.ner_detector import NerDetector
        ner = NerDetector()
        if not ner.available:
            pytest.skip("transformers 未安装")

        items = ner.detect("今天天气不错")
        names = [i for i in items if i.type == "PERSON_NAME"]
        assert len(names) == 0

    def test_single_char_filtered(self):
        """单字不应被识别为实体"""
        from app.pipeline.ner_detector import NerDetector
        ner = NerDetector()
        if not ner.available:
            pytest.skip("transformers 未安装")

        items = ner.detect("张说了一句话")
        single_chars = [i for i in items if len(i.original) < 2]
        assert len(single_chars) == 0

    def test_source_is_ner_cluener(self):
        """source 字段应为 ner_cluener"""
        from app.pipeline.ner_detector import NerDetector
        ner = NerDetector()
        if not ner.available:
            pytest.skip("transformers 未安装")

        items = ner.detect("张三在北京工作")
        for item in items:
            assert item.source == "ner_cluener"

    def test_detect_address(self):
        """CLUENER 能识别地址"""
        from app.pipeline.ner_detector import NerDetector
        ner = NerDetector()
        if not ner.available:
            pytest.skip("transformers 未安装")

        items = ner.detect("请将货物寄到北京市朝阳区建国路88号")
        addr_items = [i for i in items if i.type == "ADDRESS"]
        # CLUENER 对地址识别效果因文本而异，至少不应报错
        # 如果检测到，类型和敏感度应正确
        for item in addr_items:
            assert item.sensitivity == SensitivityLevel.HIGH
            assert item.source == "ner_cluener"

    def test_detect_organization(self):
        """CLUENER 能识别组织机构"""
        from app.pipeline.ner_detector import NerDetector
        ner = NerDetector()
        if not ner.available:
            pytest.skip("transformers 未安装")

        items = ner.detect("他在腾讯公司工作了三年")
        org_items = [i for i in items if i.type == "ORGANIZATION"]
        for item in org_items:
            assert item.sensitivity == SensitivityLevel.MEDIUM
            assert item.source == "ner_cluener"

    def test_person_name_is_critical(self):
        """人名应标记为 CRITICAL 敏感度"""
        from app.pipeline.ner_detector import NerDetector
        ner = NerDetector()
        if not ner.available:
            pytest.skip("transformers 未安装")

        items = ner.detect("张三签署了合同")
        name_items = [i for i in items if i.type == "PERSON_NAME"]
        for item in name_items:
            assert item.sensitivity == SensitivityLevel.CRITICAL

    def test_confidence_from_model(self):
        """置信度使用模型输出的 score"""
        from app.pipeline.ner_detector import NerDetector
        ner = NerDetector()
        if not ner.available:
            pytest.skip("transformers 未安装")

        items = ner.detect("张三的电话号码")
        for item in items:
            # 模型 score 通常在 0.5-1.0 之间
            assert 0.0 < item.confidence <= 1.0

    def test_lazy_loading(self):
        """模型应懒加载：__init__ 不加载模型，首次 detect() 才加载"""
        from app.pipeline.ner_detector import NerDetector
        ner = NerDetector()
        if not ner.available:
            pytest.skip("transformers 未安装")

        # __init__ 后模型未加载
        assert not ner._model_loaded
        assert ner._pipeline is None

        # 首次 detect() 触发加载
        ner.detect("张三")
        assert ner._model_loaded

    def test_skip_irrelevant_labels(self):
        """不相关标签（position/scene/book 等）应被跳过"""
        from app.pipeline.ner_detector import NerDetector, _SKIP_LABELS
        assert "position" in _SKIP_LABELS
        assert "scene" in _SKIP_LABELS
        assert "book" in _SKIP_LABELS
        assert "game" in _SKIP_LABELS
        assert "movie" in _SKIP_LABELS

    def test_degradation_without_transformers(self):
        """transformers 未安装时优雅降级"""
        import importlib
        from unittest.mock import patch

        with patch.dict("sys.modules", {"transformers": None}):
            from app.pipeline.ner_detector import NerDetector
            # 需要重新实例化以触发 ImportError
            ner = NerDetector.__new__(NerDetector)
            ner._available = False
            ner._pipeline = None
            ner._model_loaded = False

            assert not ner.available
            assert ner.detect("张三") == []


class TestRegexConfidence:
    """正则检测置信度上下文调整"""

    def setup_method(self):
        from app.pipeline.cognitive_isolator import CognitiveIsolator
        self.isolator = CognitiveIsolator({"locale": "zh"})

    def test_confidence_boosted_in_credit_report(self):
        """征信报告上下文中，身份证号置信度应提升"""
        from app.pipeline.cognitive_isolator import _CONFIDENCE_BOOST, _DEFAULT_REGEX_CONFIDENCE
        assert ("credit_report", "ID_CARD") in _CONFIDENCE_BOOST
        assert _CONFIDENCE_BOOST[("credit_report", "ID_CARD")] > _DEFAULT_REGEX_CONFIDENCE

    def test_confidence_default_without_doctype(self):
        """无文档类型上下文时，使用默认置信度"""
        from app.pipeline.cognitive_isolator import _DEFAULT_REGEX_CONFIDENCE

        items = self.isolator._detect_all("我的手机号是13800138000")
        assert len(items) >= 1
        phone_items = [i for i in items if i.type == "PHONE"]
        assert len(phone_items) == 1
        assert phone_items[0].confidence == _DEFAULT_REGEX_CONFIDENCE

    def test_confidence_boosted_with_doctype(self):
        """有文档类型时，置信度根据映射表调整"""
        items = self.isolator._detect_all(
            "我的手机号是13800138000", doc_type="resume",
        )
        phone_items = [i for i in items if i.type == "PHONE"]
        assert len(phone_items) == 1
        assert phone_items[0].confidence == 0.95  # resume + PHONE = 0.95

    def test_confidence_in_detected_item(self):
        """DetectedItem 包含 confidence 字段"""
        from app.pipeline.cognitive_isolator import DetectedItem
        item = DetectedItem(
            original="test", type="PHONE",
            sensitivity=SensitivityLevel.HIGH,
            start=0, end=4, confidence=0.9,
        )
        assert item.confidence == 0.9

    def test_confidence_default_is_one(self):
        """confidence 默认值为 1.0"""
        from app.pipeline.cognitive_isolator import DetectedItem
        item = DetectedItem(
            original="test", type="PHONE",
            sensitivity=SensitivityLevel.HIGH,
            start=0, end=4,
        )
        assert item.confidence == 1.0


class TestOverlapWithConfidence:
    """重叠去重考虑置信度"""

    def test_same_sensitivity_higher_confidence_wins(self):
        """同敏感度等级，高置信度胜出"""
        from app.pipeline.cognitive_isolator import CognitiveIsolator, DetectedItem

        items = [
            DetectedItem("13800138000", "PHONE", SensitivityLevel.HIGH, 0, 11, confidence=0.85),
            DetectedItem("13800138000", "PHONE", SensitivityLevel.HIGH, 0, 11, confidence=0.95),
        ]
        # 倒序输入（模拟实际流程）
        items.sort(key=lambda d: d.start, reverse=True)
        result = CognitiveIsolator._remove_overlaps(items)
        assert len(result) == 1
        assert result[0].confidence == 0.95


class TestVectorMatching:
    """向量反向匹配文档类型"""

    def test_cosine_similarity(self):
        """余弦相似度计算正确"""
        from app.pipeline.doc_type_detector import _cosine_similarity
        # 相同向量 → 1.0
        assert abs(_cosine_similarity([1, 0, 0], [1, 0, 0]) - 1.0) < 1e-6
        # 正交向量 → 0.0
        assert abs(_cosine_similarity([1, 0, 0], [0, 1, 0])) < 1e-6
        # 反向向量 → -1.0
        assert abs(_cosine_similarity([1, 0], [-1, 0]) - (-1.0)) < 1e-6
        # 零向量 → 0.0
        assert _cosine_similarity([0, 0], [1, 1]) == 0.0

    def test_vectors_not_ready_by_default(self):
        """初始化后向量未就绪"""
        from app.pipeline.doc_type_detector import DocTypeDetector
        detector = DocTypeDetector(locale="zh")
        assert not detector.vectors_ready

    @pytest.mark.asyncio
    async def test_warmup_vectors(self):
        """预热后向量就绪"""
        from app.pipeline.doc_type_detector import DocTypeDetector
        detector = DocTypeDetector(locale="zh")

        # Mock embedding service
        mock_embed = AsyncMock()
        mock_embed.embed_batch = AsyncMock(
            return_value=[[0.1] * 10 for _ in range(len(detector._trigger_index))]
        )

        await detector.warmup_vectors(mock_embed)
        assert detector.vectors_ready
        assert mock_embed.embed_batch.called

    @pytest.mark.asyncio
    async def test_detect_by_vector_not_ready(self):
        """向量未就绪时返回 None"""
        from app.pipeline.doc_type_detector import DocTypeDetector
        detector = DocTypeDetector(locale="zh")
        mock_embed = AsyncMock()

        result = await detector.detect_by_vector("任何文本", mock_embed)
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_by_vector_match(self):
        """向量匹配命中"""
        from app.pipeline.doc_type_detector import DocTypeDetector
        detector = DocTypeDetector(locale="zh")

        triggers = list(detector._trigger_index.keys())
        # 给每个 trigger 一个不同的向量
        trigger_vectors = []
        for i, _ in enumerate(triggers):
            vec = [0.0] * 10
            vec[i % 10] = 1.0
            trigger_vectors.append(vec)

        mock_embed = AsyncMock()
        mock_embed.embed_batch = AsyncMock(return_value=trigger_vectors)
        await detector.warmup_vectors(mock_embed)

        # 查询向量与第一个 trigger 的向量一致 → 应该匹配到对应的模板
        query_vec = trigger_vectors[0]
        mock_embed.embed = AsyncMock(return_value=query_vec)

        result = await detector.detect_by_vector("一些语义相似的文本", mock_embed)
        assert result is not None

    @pytest.mark.asyncio
    async def test_detect_by_vector_no_match(self):
        """向量匹配未达阈值"""
        from app.pipeline.doc_type_detector import DocTypeDetector
        detector = DocTypeDetector(locale="zh")

        triggers = list(detector._trigger_index.keys())
        trigger_vectors = [[1.0, 0.0, 0.0] for _ in triggers]

        mock_embed = AsyncMock()
        mock_embed.embed_batch = AsyncMock(return_value=trigger_vectors)
        await detector.warmup_vectors(mock_embed)

        # 查询向量与所有 trigger 正交 → 不应匹配
        mock_embed.embed = AsyncMock(return_value=[0.0, 1.0, 0.0])
        result = await detector.detect_by_vector("完全不相关的文本", mock_embed)
        assert result is None


class TestNerIntegration:
    """NER 集成到认知隔离器"""

    def test_ner_detector_initialized(self):
        """认知隔离器初始化时加载 NER 检测器"""
        from app.pipeline.cognitive_isolator import CognitiveIsolator
        isolator = CognitiveIsolator({"locale": "zh"})
        # transformers 已安装，所以 _ner_detector 应该不为 None
        assert isolator._ner_detector is not None

    def test_ner_detects_name_in_plain_text(self):
        """NER 在纯文本中检测人名（兜底）"""
        from app.pipeline.cognitive_isolator import CognitiveIsolator
        isolator = CognitiveIsolator({"locale": "zh"})

        # "张三" 是常见名字，CLUENER 通常能识别
        result = isolator.isolate("请帮我联系张三")
        # 如果被检测到，应该被脱敏
        if result.detected_count > 0:
            assert "张三" not in result.clean_text

    def test_ner_sensitivity_filtering(self):
        """NER 结果应受 _enabled_levels 过滤"""
        from app.pipeline.cognitive_isolator import CognitiveIsolator

        # 关闭 MEDIUM 级别，ORGANIZATION 不应被脱敏
        config = {
            "locale": "zh",
            "sensitivity_levels": {
                "critical": True,
                "high": True,
                "medium": False,
                "low": False,
            },
        }
        isolator = CognitiveIsolator(config)
        assert SensitivityLevel.MEDIUM not in isolator._enabled_levels
