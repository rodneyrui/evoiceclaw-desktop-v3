"""回复验证服务测试

覆盖范围：
- should_verify() 确定性触发规则（8 个核心场景）
- VerificationResult 数据模型
- 辅助函数：_contains_high_risk_claims, _extract_claims, select_auditor_model 降级

领域知识（risk_patterns / claim_patterns）通过 _set_verification_config_for_testing
注入，与生产环境 YAML 加载路径解耦。
"""

import pytest
from app.services.verification_service import (
    VerificationResult,
    should_verify,
    _contains_high_risk_claims,
    _extract_claims,
    select_auditor_model,
    _set_verification_config_for_testing,
)

# ── 测试配置（模拟规则引擎生成的 verification_config.yaml 内容） ────────────

_TEST_RISK_PATTERNS = (
    r"(建议[买卖持]|投资建议|不构成投资|预计[涨跌]|目标价"
    r"|处方|用药|剂量|诊断为|治疗方案"
    r"|根据《.*?法》|违反.*?条|法律责任"
    r"|据统计|数据显示|根据.*?报告|同比[增长下降].*?%)"
)

_TEST_CLAIM_PATTERNS = (
    r"(?:(?:同比|环比|增长|下降|上涨|下跌).*?\d+\.?\d*%"
    r"|(?:目标价|收盘价|市值|营收|利润|净利|收入).*?\d+"
    r"|(?:根据|据).*?(?:报告|数据|统计|公告).*?(?:显示|表明|指出)"
    r"|(?:\d{4}年.*?(?:第[一二三四]季度|上半年|下半年|全年)))"
)

_FULL_TEST_CONFIG = {
    "risk_patterns": _TEST_RISK_PATTERNS,
    "claim_patterns": _TEST_CLAIM_PATTERNS,
    "action_keywords_extra": r"(请执行|运行以下|执行以下|输入以下命令)",
}


@pytest.fixture(autouse=True)
def clear_vc_config():
    """每个测试前后清除注入的配置，确保测试隔离"""
    _set_verification_config_for_testing(None)
    yield
    _set_verification_config_for_testing(None)


@pytest.fixture
def with_full_config():
    """注入完整的测试配置（risk/claim/action 三类 pattern）"""
    _set_verification_config_for_testing(_FULL_TEST_CONFIG)
    yield


# ── 1. 短回复：不触发验证 ─────────────────────────────────────


def test_short_reply_skipped():
    """短于 MIN_REPLY_LENGTH 的回复直接跳过"""
    result, method = should_verify(
        user_message="帮我写个函数",
        assistant_reply="好的",
        tool_names_used=[],
    )
    assert result is False
    assert method == ""


def test_empty_reply_skipped():
    result, method = should_verify(
        user_message="test",
        assistant_reply="",
        tool_names_used=[],
    )
    assert result is False


# ── 2. 外部数据工具：跳过验证 ──────────────────────────────────


def test_external_data_tools_skip():
    """使用了 web_search / web_fetch 等外部数据工具时跳过验证"""
    long_reply = "根据搜索结果，今天北京天气晴，气温 25°C，空气质量良好。" * 3
    result, method = should_verify(
        user_message="今天天气怎么样",
        assistant_reply=long_reply,
        tool_names_used=["web_search"],
    )
    assert result is False


def test_http_request_tool_skip():
    long_reply = "API 返回数据显示当前价格为 100 元，已为你展示结果。" * 3
    result, method = should_verify(
        user_message="查价格",
        assistant_reply=long_reply,
        tool_names_used=["http_request"],
    )
    assert result is False


# ── 3. 写操作工具：触发 legacy 验证 ────────────────────────────


def test_write_tool_triggers_legacy():
    """save_memory / write_file 等写操作工具触发 legacy 验证"""
    long_reply = "已将你的偏好保存到记忆系统中，下次对话将优先使用中文回复。" * 2
    result, method = should_verify(
        user_message="记住我喜欢中文",
        assistant_reply=long_reply,
        tool_names_used=["save_memory"],
    )
    assert result is True
    assert method == "legacy"


def test_install_skill_triggers_legacy():
    long_reply = "Skill 已成功安装，你现在可以使用天气查询功能了，输入「查天气」即可触发。" * 2
    result, method = should_verify(
        user_message="安装天气skill",
        assistant_reply=long_reply,
        tool_names_used=["install_skill"],
    )
    assert result is True
    assert method == "legacy"


# ── 4. 代码块：触发 legacy 验证 ─────────────────────────────────


def test_code_block_triggers_legacy():
    reply = (
        "下面是一个简单的 Python 函数示例：\n\n"
        "```python\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n\n"
        "print(add(1, 2))\n"
        "```\n\n"
        "你可以直接运行这段代码来验证结果。"
    )
    result, method = should_verify(
        user_message="写一个加法函数",
        assistant_reply=reply,
        tool_names_used=[],
    )
    assert result is True
    assert method == "legacy"


def test_short_code_block_not_triggered():
    """代码块内容少于 20 个字符时不触发（如 `print("hi")`）"""
    reply = "你可以用 `x=1` 来赋值。" * 5  # 无长代码块
    result, method = should_verify(
        user_message="怎么赋值",
        assistant_reply=reply,
        tool_names_used=[],
    )
    assert result is False


# ── 5. 操作性关键词：触发 legacy 验证 ──────────────────────────


def test_action_keyword_sudo():
    reply = "请执行以下命令来安装依赖：sudo apt install python3-dev 完成后重启服务。" * 2
    result, method = should_verify(
        user_message="怎么安装",
        assistant_reply=reply,
        tool_names_used=[],
    )
    assert result is True
    assert method == "legacy"


def test_action_keyword_pip():
    reply = "你需要先安装 numpy：pip install numpy 然后在代码中 import numpy as np 即可使用。" * 2
    result, method = should_verify(
        user_message="怎么用numpy",
        assistant_reply=reply,
        tool_names_used=[],
    )
    assert result is True
    assert method == "legacy"


def test_action_keyword_extra_from_config(with_full_config):
    """规则引擎生成的语言扩展关键词（中文）也能触发验证"""
    reply = "请执行以下步骤完成操作：首先备份数据，然后运行迁移脚本，最后验证结果。" * 2
    result, method = should_verify(
        user_message="怎么迁移数据库",
        assistant_reply=reply,
        tool_names_used=[],
    )
    assert result is True
    assert method == "legacy"


def test_action_keyword_extra_not_triggered_without_config():
    """未注入配置时，中文扩展关键词不触发（降级行为）"""
    reply = "请执行以下步骤完成操作：首先备份数据，然后运行迁移脚本，最后验证结果。" * 2
    result, method = should_verify(
        user_message="怎么迁移数据库",
        assistant_reply=reply,
        tool_names_used=[],
    )
    assert result is False


# ── 6. 正常回复：不触发 ─────────────────────────────────────────


def test_normal_reply_no_trigger():
    """普通长回复，无工具/代码块/关键词，不触发验证"""
    reply = (
        "Python 是一种高级编程语言，以简洁的语法和强大的标准库著称。"
        "它支持多种编程范式，包括面向对象、函数式和过程式编程。"
        "Python 广泛应用于数据科学、Web 开发、自动化脚本等领域。"
        "学习 Python 的最佳方式是从官方文档开始，结合实际项目练习。"
    )
    result, method = should_verify(
        user_message="Python 是什么",
        assistant_reply=reply,
        tool_names_used=[],
    )
    assert result is False


# ── 7. 高风险事实声称检测 ─────────────────────────────────────


def test_high_risk_medical_claim(with_full_config):
    """医疗相关声称（处方、剂量）标记为高风险"""
    reply = (
        "根据你描述的症状，初步诊断为轻度感冒，建议用药剂量如下：布洛芬 400mg，"
        "每日三次，饭后服用，疗程不超过 5 天。如症状未改善或加重，请及时就医。"
        "同时注意多饮水、充分休息，避免劳累，保持室内通风，减少外出接触传染源。"
    )
    assert len(reply) >= 100, f"测试字符串长度不足 ({len(reply)})"
    assert _contains_high_risk_claims(reply) is True


def test_high_risk_financial_claim(with_full_config):
    """金融投资建议（建议买/卖）标记为高风险"""
    reply = (
        "综合技术面和基本面分析，建议买入该股票，目标价 25 元，止损设在 18 元，"
        "预计持有周期 3-6 个月，但投资有风险，以上内容仅供参考，"
        "不代表任何机构的正式投资建议，投资者需自行评估风险承受能力并谨慎决策。"
    )
    assert len(reply) >= 100, f"测试字符串长度不足 ({len(reply)})"
    assert _contains_high_risk_claims(reply) is True


def test_high_risk_legal_claim(with_full_config):
    """法律条款引用标记为高风险"""
    reply = (
        "根据《劳动合同法》第39条的规定，用人单位可以依法解除劳动合同，"
        "违反者需承担相应的法律责任和经济赔偿，如有争议可向劳动争议仲裁委员会申请劳动仲裁，"
        "同时建议咨询专业律师，了解具体的法律救济途径和维权流程及注意事项。"
    )
    assert len(reply) >= 100, f"测试字符串长度不足 ({len(reply)})"
    assert _contains_high_risk_claims(reply) is True


def test_no_high_risk_normal(with_full_config):
    """普通陈述句不被误判为高风险"""
    reply = "人工智能是计算机科学的一个重要分支，主要研究如何让机器模拟人类智能行为。"
    assert _contains_high_risk_claims(reply) is False


def test_high_risk_requires_min_length():
    """短于 100 字符的回复即使包含高风险词也跳过（无需注入配置，因为先被长度过滤）"""
    # 不注入配置：先被长度检查（<100）过滤，不会到达 pattern 检查
    assert _contains_high_risk_claims("建议买入") is False


def test_high_risk_returns_false_without_config():
    """未注入配置时（_vc_risk_pattern=None），_contains_high_risk_claims 始终返回 False"""
    long_reply = "建议买入该股票，目标价 25 元，止损设在 18 元，预计持有周期 3 个月，" * 5
    assert len(long_reply) >= 100
    # 未注入 config，_vc_risk_pattern 为 None
    assert _contains_high_risk_claims(long_reply) is False


# ── 8. 事实声称提取 ────────────────────────────────────────────


def test_extract_claims_percentage(with_full_config):
    """提取百分比增长声称"""
    reply = "该公司 2024 年营收同比增长 35.6%，净利同比下降 12%，市值突破 500 亿。"
    claims = _extract_claims(reply)
    assert len(claims) >= 1
    assert any("35.6%" in c or "增长" in c for c in claims)


def test_extract_claims_empty(with_full_config):
    """无匹配声称时返回空列表"""
    reply = "Python 是很好的编程语言，我喜欢用它做数据处理。"
    claims = _extract_claims(reply)
    assert claims == []


def test_extract_claims_returns_empty_without_config():
    """未注入配置时（_vc_claim_pattern=None），_extract_claims 返回空列表"""
    reply = "该公司 2024 年营收同比增长 35.6%，净利同比下降 12%。"
    assert _extract_claims(reply) == []


def test_extract_claims_dedup(with_full_config):
    """去重：重复声称只保留一次"""
    reply = "同比增长 10% 的背景下，同比增长 10% 的预期已被市场消化。"
    claims = _extract_claims(reply)
    texts = [c for c in claims]
    assert len(texts) == len(set(texts))


def test_extract_claims_max_3(with_full_config):
    """最多返回 3 条声称"""
    reply = (
        "同比增长 10% 同比增长 20% 同比增长 30% 同比增长 40% "
        "目标价 50 目标价 60 目标价 70 "
        "据统计数据显示增幅明显 据报告指出趋势向好"
    )
    claims = _extract_claims(reply)
    assert len(claims) <= 3


# ── 9. VerificationResult 数据模型 ───────────────────────────


def test_verification_result_fields():
    r = VerificationResult(
        verified=True,
        confidence="high",
        issues=[],
        summary="回复基本准确",
        method="legacy",
        elapsed_ms=150,
    )
    assert r.verified is True
    assert r.confidence == "high"
    assert r.issues == []
    assert r.method == "legacy"
    assert r.elapsed_ms == 150


def test_verification_result_failed():
    r = VerificationResult(
        verified=False,
        confidence="low",
        issues=["数据来源不明", "数字存疑"],
        summary="发现 2 个潜在问题",
        method="strong_model_review",
        elapsed_ms=2300,
    )
    assert r.verified is False
    assert len(r.issues) == 2


# ── 10. select_auditor_model 降级 ────────────────────────────


def test_select_auditor_model_fallback_no_router():
    """无法 import router 时降级到 qwen/qwen-plus"""
    # 传入空 config，router.get_available_models 会失败 → 降级
    auditor = select_auditor_model("deepseek/deepseek-chat", "coding", {})
    # 不论成功与否，都应返回非空字符串
    assert isinstance(auditor, str)
    assert len(auditor) > 0


# ── 11. 多 Agent 协同整合：consult_expert 触发深度思考验证 ──────


def test_consult_expert_2_triggers_deep_think():
    """consult_expert 出现 2 次 → 触发 deep_think_review"""
    long_reply = "综合两位专家的意见，该论文的方法论存在以下问题：样本量不足、对照组缺失。" * 3
    result, method = should_verify(
        user_message="帮我分析这篇论文",
        assistant_reply=long_reply,
        tool_names_used=["consult_expert", "consult_expert"],
    )
    assert result is True
    assert method == "deep_think_review"


def test_consult_expert_3_triggers_deep_think():
    """consult_expert 出现 3 次也触发"""
    long_reply = "三位专家分别从不同角度分析了该技术方案的可行性，结论如下。" * 3
    result, method = should_verify(
        user_message="评估这个方案",
        assistant_reply=long_reply,
        tool_names_used=["consult_expert", "consult_expert", "consult_expert"],
    )
    assert result is True
    assert method == "deep_think_review"


def test_consult_expert_1_no_trigger():
    """consult_expert 仅 1 次不触发 deep_think_review"""
    long_reply = "根据专家意见，该方案基本可行，但需要注意以下几个细节问题。" * 3
    result, method = should_verify(
        user_message="问问专家",
        assistant_reply=long_reply,
        tool_names_used=["consult_expert"],
    )
    # 不应触发 deep_think_review（可能触发其他规则或不触发）
    assert method != "deep_think_review"


def test_consult_expert_with_custom_threshold():
    """通过 config 自定义 min_consult_count 阈值"""
    long_reply = "综合多位专家意见，结论如下，该方案在技术上可行但成本偏高。" * 3
    config = {"verification": {"deep_think": {"min_consult_count": 3}}}
    # 2 次不够（阈值为 3）
    result, method = should_verify(
        user_message="分析方案",
        assistant_reply=long_reply,
        tool_names_used=["consult_expert", "consult_expert"],
        config=config,
    )
    assert method != "deep_think_review"

    # 3 次达到阈值
    result, method = should_verify(
        user_message="分析方案",
        assistant_reply=long_reply,
        tool_names_used=["consult_expert", "consult_expert", "consult_expert"],
        config=config,
    )
    assert result is True
    assert method == "deep_think_review"


def test_consult_expert_mixed_with_external_tools():
    """consult_expert + 外部数据工具 → 外部数据工具优先跳过验证"""
    long_reply = "根据搜索和专家意见，该数据基本准确，来源可靠。" * 3
    result, method = should_verify(
        user_message="验证数据",
        assistant_reply=long_reply,
        tool_names_used=["consult_expert", "consult_expert", "web_search"],
    )
    # web_search 在 _EXTERNAL_DATA_TOOLS 中，优先跳过
    assert result is False


# ── 12. _verify_by_deep_think 单元测试 ──────────────────────────


@pytest.mark.asyncio
async def test_verify_by_deep_think_no_available_models():
    """无可用深度思考模型时返回 None"""
    from app.services.verification_service import _verify_by_deep_think

    # 空 config → router 不可用 → 返回 None
    result = await _verify_by_deep_think("问题", "回复" * 50, {})
    assert result is None


# ── 13. verify_response deep_think_review 分支 ──────────────────


@pytest.mark.asyncio
async def test_verify_response_deep_think_degrades_to_strong():
    """deep_think_review 不可用时降级到 strong_model_review"""
    from unittest.mock import patch, AsyncMock
    from app.services.verification_service import verify_response

    mock_result = VerificationResult(
        verified=True, confidence="medium", issues=[],
        summary="mock 审核通过", method="strong_model_review", elapsed_ms=100,
    )

    # 深度思考模型不可用 → 降级到 strong_model_review → mock _verify_by_model
    with patch(
        "app.services.verification_service._verify_by_model",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await verify_response(
            user_message="测试问题",
            assistant_reply="测试回复" * 50,
            config={"verification": {"enabled": True}, "providers": {}},
            method="deep_think_review",
        )
    assert result is not None
    assert isinstance(result, VerificationResult)
