"""评分引擎 — 根据 scoring_type 分发到具体评分模块"""

from __future__ import annotations

from app.evaluation.scoring.exact import score_exact
from app.evaluation.scoring.keyword import score_keywords
from app.evaluation.scoring.tool_call import score_tool_call
from app.evaluation.scoring.rubric import score_rubric
from app.evaluation.scoring.code_test import score_code_test
from app.evaluation.scoring.format_check import score_format


async def score_test(
    test,
    response: str,
    tool_calls: list | None = None,
    config: dict | None = None,
) -> tuple[int, str]:
    """根据测试类型评分

    Args:
        test: TestCase 实例
        response: 模型的文本输出
        tool_calls: 模型的工具调用结果（tool_call 评分时使用）
        config: 应用配置（rubric 评分需要用来调用 judge 模型）

    Returns:
        (score, detail): 分数 0-100 和评分明细字符串
    """
    if test.scoring_type == "exact":
        return score_exact(response, test.expected_answer or "")
    elif test.scoring_type == "keyword":
        return score_keywords(response, test.expected_keywords)
    elif test.scoring_type == "rubric":
        return await score_rubric(response, test.rubric, config=config)
    elif test.scoring_type == "tool_call":
        return score_tool_call(tool_calls, test.expected_tool_name, test.expected_tool_params)
    elif test.scoring_type == "code_test":
        return score_code_test(response, test.code_test_cases or [])
    elif test.scoring_type == "format_check":
        fmt_score, fmt_detail = score_format(response, test.format_rules or {})
        # 如果同时设置了 rubric，组合评分（format 占 60%，rubric 占 40%）
        if test.rubric:
            rubric_score, rubric_detail = await score_rubric(response, test.rubric, config=config)
            combined = int(fmt_score * 0.6 + rubric_score * 0.4)
            return combined, f"[格式 {fmt_score}]\n{fmt_detail}\n[内容 {rubric_score}]\n{rubric_detail}"
        return fmt_score, fmt_detail
    else:
        return 0, f"未知评分类型: {test.scoring_type}"
