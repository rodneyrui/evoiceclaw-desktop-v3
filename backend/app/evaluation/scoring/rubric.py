"""Rubric 评分 — 用 LLM-as-Judge 评判开放性条件

对每个 rubric 条件：
1. 先尝试确定性检查（长度、数字等）
2. 若无法确定则调用 LLM judge 进行语义判断
3. 无 LLM 可用时回退到宽松关键词匹配
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("benchmark.scoring.rubric")


async def score_rubric(
    response: str,
    rubric: list[tuple[str, int]],
    config: dict | None = None,
) -> tuple[int, str]:
    """Rubric 评分

    Args:
        response: 模型输出文本
        rubric: [(条件描述, 分值), ...] 列表
        config: 应用配置（需含 providers 信息以调用 judge 模型）

    Returns:
        (score, detail): 分数 0-100 和评分明细
    """
    if not rubric:
        return 0, "无 rubric 条件"

    total = 0
    max_total = sum(pts for _, pts in rubric)
    details = []

    # 收集需要 LLM 判断的条件
    llm_conditions = []
    deterministic_results = {}

    for i, (condition, points) in enumerate(rubric):
        result = _check_deterministic(condition, response)
        if result is not None:
            deterministic_results[i] = result
        else:
            llm_conditions.append((i, condition, points))

    # 批量调用 LLM judge
    llm_results = {}
    if llm_conditions and config:
        llm_results = await _llm_judge_batch(response, llm_conditions, config)
    elif llm_conditions:
        for i, condition, _ in llm_conditions:
            llm_results[i] = _keyword_fallback(condition, response)

    # 汇总结果
    for i, (condition, points) in enumerate(rubric):
        if i in deterministic_results:
            passed = deterministic_results[i]
        else:
            passed = llm_results.get(i, False)

        if passed:
            total += points
            details.append(f"  ✓ {condition} (+{points})")
        else:
            details.append(f"  ✗ {condition} (0/{points})")

    score = int(100 * total / max_total) if max_total > 0 else 0
    return score, "\n".join(details)


def _check_deterministic(condition: str, response: str) -> bool | None:
    """确定性检查：长度、数字等可精确判断的条件。返回 None 表示需要 LLM。"""
    # 长度检查
    length_match = re.search(r"长度在(\d+)-(\d+)字", condition)
    if length_match:
        min_len, max_len = int(length_match.group(1)), int(length_match.group(2))
        return min_len <= len(response) <= max_len

    length_match2 = re.search(r"输出长度在(\d+)-(\d+)字之间", condition)
    if length_match2:
        min_len, max_len = int(length_match2.group(1)), int(length_match2.group(2))
        return min_len <= len(response) <= max_len

    # "没有调用任何工具" 检查
    if "没有调用任何工具" in condition:
        return True

    return None


def _keyword_fallback(condition: str, response: str) -> bool:
    """宽松关键词回退（无 LLM 可用时）"""
    cn_keywords = re.findall(r"[\u4e00-\u9fff]{2,4}", condition)
    stopwords = {"包含", "提到", "分析", "引用", "给出", "进行", "使用", "正确", "至少", "一项", "中的"}
    keywords = [kw for kw in cn_keywords if kw not in stopwords]
    if not keywords:
        return False
    return any(kw in response for kw in keywords)


async def _llm_judge_batch(
    response: str,
    conditions: list[tuple[int, str, int]],
    config: dict,
) -> dict[int, bool]:
    """批量调用 LLM 评判多个 rubric 条件"""
    import litellm

    results: dict[int, bool] = {}

    # 获取 judge 模型配置
    judge_config = config.get("judge", {})
    judge_model_id = judge_config.get("primary", "deepseek/deepseek-chat")

    provider_id, model_name = judge_model_id.split("/", 1)
    providers = config.get("providers", {})
    provider_config = providers.get(provider_id, {})
    api_key = provider_config.get("api_key", "")
    base_url = provider_config.get("base_url", "")

    prefixes = config.get("litellm_prefixes", {})
    prefix = prefixes.get(provider_id, "openai")
    litellm_model = f"{prefix}/{model_name}"

    # 构建 judge prompt
    condition_list = "\n".join(
        f"{idx+1}. {cond}" for idx, (_, cond, _) in enumerate(conditions)
    )

    judge_prompt = (
        "你是一个评分裁判。请判断以下「模型输出」是否满足每个评分条件。\n"
        "只需要判断内容是否覆盖了条件要求的主题/要素，不要求必须使用完全相同的措辞。\n"
        "语义相近即可判定为满足。\n\n"
        f"## 模型输出\n\n{response[:3000]}\n\n"
        f"## 评分条件\n\n{condition_list}\n\n"
        "## 要求\n"
        f"请对上述 {len(conditions)} 个条件逐一判断，每行输出一个结果，格式为：\n"
        "序号. Y 或 序号. N\n"
        "例如：\n1. Y\n2. N\n3. Y\n\n"
        "只输出判断结果，不要解释。"
    )

    try:
        resp = await litellm.acompletion(
            model=litellm_model,
            messages=[{"role": "user", "content": judge_prompt}],
            api_key=api_key,
            base_url=base_url,
            temperature=0.0,
            timeout=30,
        )
        judge_text = resp.choices[0].message.content or ""

        for idx, (orig_idx, _, _) in enumerate(conditions):
            pattern = rf"(?:^|\n)\s*{idx+1}\s*[.．、]\s*([YyNn])"
            match = re.search(pattern, judge_text)
            if match:
                results[orig_idx] = match.group(1).upper() == "Y"
            else:
                cond_text = conditions[idx][1]
                results[orig_idx] = _keyword_fallback(cond_text, response)

        logger.debug("[Judge] 评判完成: %d 个条件", len(conditions))
    except Exception as e:
        logger.warning("[Judge] LLM 评判失败，回退到关键词匹配: %s", e)
        for orig_idx, cond_text, _ in conditions:
            results[orig_idx] = _keyword_fallback(cond_text, response)

    return results
