"""关键词匹配评分 — 检查必含关键词的覆盖度"""

from __future__ import annotations


def score_keywords(response: str, keywords: list[str]) -> tuple[int, str]:
    """关键词评分

    评分逻辑：分数 = 100 * 找到的关键词数 / 总关键词数
    匹配时忽略大小写。

    Args:
        response: 模型输出文本
        keywords: 必须包含的关键词列表

    Returns:
        (score, detail): 分数 0-100 和评分明细
    """
    if not keywords:
        return 0, "无关键词可检查"

    found = []
    missing = []
    for kw in keywords:
        if kw.lower() in response.lower():
            found.append(kw)
        else:
            missing.append(kw)

    score = int(100 * len(found) / len(keywords))
    detail = f"找到 {len(found)}/{len(keywords)} 个关键词"
    if missing:
        detail += f"，缺少: {missing}"
    return score, detail
