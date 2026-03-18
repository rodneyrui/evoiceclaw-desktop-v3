"""工具调用评分 — 检查工具名称和参数"""

from __future__ import annotations

import json


def score_tool_call(
    tool_calls: list | None,
    expected_name: str | None,
    expected_params: dict | None,
) -> tuple[int, str]:
    """工具调用评分

    评分规则：
      - 工具名称正确：60 分
      - 参数正确：40 分（按参数数量均分）
      - 如果不检查参数（expected_params=None），工具名正确即满分

    Args:
        tool_calls: 模型产生的工具调用列表
        expected_name: 期望的工具名称
        expected_params: 期望的参数字典（None 表示不检查参数）

    Returns:
        (score, detail): 分数 0-100 和评分明细
    """
    if not tool_calls:
        return 0, "模型未产生工具调用"

    score = 0
    details = []

    # 解析第一个工具调用
    first_call = tool_calls[0]
    call_name = ""
    call_args = {}

    if hasattr(first_call, "function"):
        # OpenAI SDK 对象格式
        call_name = first_call.function.name
        try:
            call_args = json.loads(first_call.function.arguments)
        except (json.JSONDecodeError, AttributeError):
            call_args = {}
    elif isinstance(first_call, dict):
        # 字典格式
        func = first_call.get("function", {})
        call_name = func.get("name", "")
        try:
            call_args = json.loads(func.get("arguments", "{}"))
        except json.JSONDecodeError:
            call_args = {}

    # 检查工具名称
    if expected_name:
        if call_name == expected_name:
            score += 60
            details.append(f"✓ 工具名称正确: {call_name}")
        else:
            details.append(f"✗ 工具名称错误: 期望 {expected_name}，实际 {call_name}")

    # 检查参数
    if expected_params:
        param_score = 0
        param_total = len(expected_params)
        for key, expected_val in expected_params.items():
            actual_val = call_args.get(key)
            if actual_val is not None:
                if str(expected_val).lower() in str(actual_val).lower():
                    param_score += 1
                    details.append(f"✓ 参数 {key} 正确")
                else:
                    details.append(f"△ 参数 {key}: 期望含 '{expected_val}'，实际 '{actual_val}'")
                    param_score += 0.5
            else:
                details.append(f"✗ 缺少参数 {key}")
        score += int(40 * param_score / param_total) if param_total else 40
    else:
        if call_name == expected_name:
            score = 100

    return min(score, 100), "\n".join(details) if details else "无评分明细"
