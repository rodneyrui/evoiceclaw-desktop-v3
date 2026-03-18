"""精确匹配评分 — 检查答案中是否包含精确数字或字符串"""

from __future__ import annotations

import re


def score_exact(response: str, expected: str) -> tuple[int, str]:
    """精确匹配评分

    评分逻辑：
      1. 清理格式字符（逗号、空格）后做字符串包含检查 → 100 分
      2. 若期望值是数字，提取回答中的所有数字做近似匹配（误差<2%）→ 90 分
      3. 都不满足 → 0 分

    Args:
        response: 模型输出文本
        expected: 期望的精确答案（通常是数字）

    Returns:
        (score, detail): 分数 0-100 和评分明细
    """
    # 清理格式字符
    clean = response.replace(",", "").replace("，", "").replace(" ", "")
    if expected in clean:
        return 100, f"找到精确答案 '{expected}'"

    # 模糊匹配：允许小数点后位数差异
    try:
        expected_float = float(expected)
        numbers = re.findall(r"[\d]+\.?\d*", clean)
        for n in numbers:
            if abs(float(n) - expected_float) / max(expected_float, 0.001) < 0.02:
                return 90, f"找到近似答案 '{n}'（期望 '{expected}'，误差<2%）"
    except ValueError:
        pass

    return 0, f"未找到期望答案 '{expected}'"
