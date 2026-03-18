"""文档类型语义检测器测试"""

import pytest
from app.pipeline.doc_type_detector import (
    DocTypeDetector,
    TemplateSensitiveFieldExtractor,
    load_templates,
)
from app.domain.models import SensitivityLevel


class TestDocTypeDetector:
    """文档类型识别测试"""

    def setup_method(self):
        self.detector = DocTypeDetector(locale="zh")

    def test_credit_report_trigger(self):
        tpl = self.detector.detect_doc_type("帮我分析张三的征信报告")
        assert tpl is not None
        assert tpl.type == "credit_report"

    def test_contract_trigger(self):
        tpl = self.detector.detect_doc_type("这份合同需要审查")
        assert tpl is not None
        assert tpl.type == "contract"

    def test_iou_trigger(self):
        tpl = self.detector.detect_doc_type("写一张借条")
        assert tpl is not None
        assert tpl.type == "iou"

    def test_medical_trigger(self):
        tpl = self.detector.detect_doc_type("看看这个病历")
        assert tpl is not None
        assert tpl.type == "medical_record"

    def test_resume_trigger(self):
        tpl = self.detector.detect_doc_type("帮我优化简历")
        assert tpl is not None
        assert tpl.type == "resume"

    def test_no_match(self):
        tpl = self.detector.detect_doc_type("今天天气怎么样")
        assert tpl is None

    def test_case_insensitive(self):
        """英文 trigger 大小写不敏感"""
        en_detector = DocTypeDetector(locale="en")
        tpl = en_detector.detect_doc_type("Please review my Credit Report")
        assert tpl is not None
        assert tpl.type == "credit_report"

    def test_get_template_by_type(self):
        tpl = self.detector.get_template("credit_report")
        assert tpl is not None
        assert len(tpl.sensitive_fields) > 0


class TestTemplateSensitiveFieldExtractor:
    """模板敏感字段提取测试"""

    def setup_method(self):
        self.detector = DocTypeDetector(locale="zh")
        self.extractor = TemplateSensitiveFieldExtractor()

    def test_extract_credit_report_fields(self):
        """征信报告中提取姓名、身份证号"""
        template = self.detector.get_template("credit_report")
        text = "个人信用报告\n姓名：穆蕴\n证件号码：110101199001011234\n开户银行：中国工商银行"
        fields = self.extractor.extract(text, template)

        types = {f.type for f in fields}
        assert "PERSON_NAME" in types
        assert "ID_CARD" in types

        names = [f for f in fields if f.type == "PERSON_NAME"]
        assert any(f.original == "穆蕴" for f in names)

    def test_extract_contract_fields(self):
        """合同中提取甲方、乙方"""
        template = self.detector.get_template("contract")
        text = "甲方：张三\n乙方：李四\n合同金额：50000元"
        fields = self.extractor.extract(text, template)

        types = {f.type for f in fields}
        assert "PERSON_NAME" in types

    def test_extract_with_colon_variants(self):
        """支持中英文冒号"""
        template = self.detector.get_template("credit_report")
        text1 = "姓名：穆蕴"
        text2 = "姓名: 穆蕴"
        fields1 = self.extractor.extract(text1, template)
        fields2 = self.extractor.extract(text2, template)
        assert len(fields1) > 0
        assert len(fields2) > 0

    def test_filter_short_values(self):
        """过滤太短的值（<2字符）"""
        template = self.detector.get_template("credit_report")
        text = "姓名：X"
        fields = self.extractor.extract(text, template)
        names = [f for f in fields if f.type == "PERSON_NAME"]
        assert len(names) == 0


class TestFilenameExtraction:
    """文件名人名提取测试"""

    def setup_method(self):
        self.detector = DocTypeDetector(locale="zh")

    def test_name_before_trigger(self):
        """穆蕴 征信报告 2026 0105.pdf → 提取 '穆蕴'"""
        fields, tpl = self.detector.extract_names_from_filename(
            "帮我分析 ~/docs/穆蕴 征信报告 2026 0105.pdf"
        )
        assert len(fields) > 0
        assert fields[0].original == "穆蕴"
        assert fields[0].type == "PERSON_NAME"
        assert tpl is not None
        assert tpl.type == "credit_report"

    def test_name_after_trigger(self):
        """征信报告 穆蕴 2026.pdf → 提取 '穆蕴'"""
        fields, tpl = self.detector.extract_names_from_filename(
            "分析 ~/征信报告 穆蕴 2026.pdf"
        )
        assert len(fields) > 0
        assert fields[0].original == "穆蕴"

    def test_name_with_spaces(self):
        """张三 征信报告.pdf"""
        fields, tpl = self.detector.extract_names_from_filename(
            "看看 ~/张三 征信报告.pdf"
        )
        assert len(fields) > 0
        assert fields[0].original == "张三"

    def test_no_name_in_filename(self):
        """征信报告.pdf — 没有人名，只有文档类型"""
        fields, tpl = self.detector.extract_names_from_filename(
            "分析 ~/征信报告.pdf"
        )
        assert len(fields) == 0
        assert tpl is not None  # 文档类型仍然命中

    def test_contract_filename(self):
        """合同类文件名"""
        fields, tpl = self.detector.extract_names_from_filename(
            "审查 ~/李四 合同 20260301.pdf"
        )
        assert tpl is not None
        assert tpl.type == "contract"
        assert len(fields) > 0
        assert fields[0].original == "李四"

    def test_no_file_path(self):
        """纯文本没有文件路径"""
        fields, tpl = self.detector.extract_names_from_filename(
            "帮我分析征信报告"
        )
        assert len(fields) == 0
        assert tpl is None


class TestIsolatorWithDocType:
    """认知隔离器集成 Level 0 测试"""

    def setup_method(self):
        from app.pipeline.cognitive_isolator import CognitiveIsolator
        self.isolator = CognitiveIsolator({"locale": "zh"})

    def test_isolate_filename_name(self):
        """用户输入含文件路径 → 文件名中的人名被脱敏"""
        from app.domain.models import SessionPrivacyContext
        ctx = SessionPrivacyContext()
        result = self.isolator.isolate(
            "帮我分析 ~/穆蕴 征信报告 2026.pdf",
            session_ctx=ctx,
        )
        assert "穆蕴" not in result.clean_text
        assert ctx.doc_type == "credit_report"
        assert ctx.privacy_notice is not None  # 隐私提醒已设置

    def test_isolate_credit_report_content(self):
        """工具返回：征信报告内容 → 姓名/证件号被脱敏"""
        from app.domain.models import SessionPrivacyContext
        ctx = SessionPrivacyContext(doc_type="credit_report")
        text = "个人信用报告\n姓名：穆蕴\n证件号码：110101199001011234"
        result = self.isolator.isolate(text, session_ctx=ctx)
        assert "穆蕴" not in result.clean_text
        assert "110101199001011234" not in result.clean_text

    def test_isolate_backward_compatible(self):
        """不传 session_ctx 时向后兼容"""
        result = self.isolator.isolate("我的手机号是13800138000")
        assert "13800138000" not in result.clean_text

    def test_session_ctx_doc_type_persists(self):
        """session_ctx 中的 doc_type 在首次识别后持久化"""
        from app.domain.models import SessionPrivacyContext
        ctx = SessionPrivacyContext()
        assert ctx.doc_type is None

        self.isolator.isolate("分析征信报告", session_ctx=ctx)
        assert ctx.doc_type == "credit_report"

        # 后续调用即使文本中没有 trigger，也能使用已识别的 doc_type
        result = self.isolator.isolate(
            "姓名：穆蕴\n证件号码：110101199001011234",
            session_ctx=ctx,
        )
        assert "穆蕴" not in result.clean_text

    def test_privacy_notice_set_on_first_trigger(self):
        """首次命中文档类型时设置 privacy_notice"""
        from app.domain.models import SessionPrivacyContext
        ctx = SessionPrivacyContext()
        self.isolator.isolate("看看这个病历", session_ctx=ctx)
        assert ctx.privacy_notice is not None
        assert "病历" in ctx.privacy_notice

    def test_privacy_notice_not_set_without_ctx(self):
        """不传 session_ctx 时不报错"""
        result = self.isolator.isolate("看看这个病历")
        assert result.clean_text == "看看这个病历"
