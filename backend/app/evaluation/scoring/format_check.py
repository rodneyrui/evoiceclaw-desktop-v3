"""格式检查评分 — 检查输出的长度、格式、关键词约束

用于 instruction_following 维度，验证模型是否严格遵循格式要求。
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("benchmark.scoring.format_check")


def score_format(
    response: str,
    rules: dict,
) -> tuple[int, str]:
    """格式检查评分

    Args:
        response: 模型输出文本
        rules: 格式规则字典，支持以下字段：
            - max_length: int — 最大字符数
            - min_length: int — 最小字符数
            - must_contain: list[str] — 必须包含的关键词
            - must_not_contain: list[str] — 不能包含的关键词
            - format: str — 格式要求："json" | "markdown_table" | "numbered_list" | "bullet_list"
            - max_paragraphs: int — 最大段落数
            - min_paragraphs: int — 最小段落数
            - language: str — 语言要求："chinese" | "english"

    Returns:
        (score, detail): 分数 0-100 和评分明细
    """
    if not rules:
        return 0, "无格式规则"

    checks = []
    total_checks = 0
    passed_checks = 0

    # 长度检查
    if "max_length" in rules:
        total_checks += 1
        ok = len(response) <= rules["max_length"]
        if ok:
            passed_checks += 1
        checks.append(f"  {'通过' if ok else '未通过'} 最大长度 {rules['max_length']}（实际 {len(response)}）")

    if "min_length" in rules:
        total_checks += 1
        ok = len(response) >= rules["min_length"]
        if ok:
            passed_checks += 1
        checks.append(f"  {'通过' if ok else '未通过'} 最小长度 {rules['min_length']}（实际 {len(response)}）")

    # 必含关键词
    if "must_contain" in rules:
        for kw in rules["must_contain"]:
            total_checks += 1
            ok = kw.lower() in response.lower()
            if ok:
                passed_checks += 1
            checks.append(f"  {'通过' if ok else '未通过'} 必须包含 '{kw}'")

    # 禁止关键词
    if "must_not_contain" in rules:
        for kw in rules["must_not_contain"]:
            total_checks += 1
            ok = kw.lower() not in response.lower()
            if ok:
                passed_checks += 1
            checks.append(f"  {'通过' if ok else '未通过'} 不能包含 '{kw}'")

    # 格式检查
    if "format" in rules:
        total_checks += 1
        fmt = rules["format"]
        ok = _check_format(response, fmt)
        if ok:
            passed_checks += 1
        checks.append(f"  {'通过' if ok else '未通过'} 格式要求: {fmt}")

    # 段落数检查
    paragraphs = [p.strip() for p in response.split("\n\n") if p.strip()]
    if "max_paragraphs" in rules:
        total_checks += 1
        ok = len(paragraphs) <= rules["max_paragraphs"]
        if ok:
            passed_checks += 1
        checks.append(f"  {'通过' if ok else '未通过'} 最大段落数 {rules['max_paragraphs']}（实际 {len(paragraphs)}）")

    if "min_paragraphs" in rules:
        total_checks += 1
        ok = len(paragraphs) >= rules["min_paragraphs"]
        if ok:
            passed_checks += 1
        checks.append(f"  {'通过' if ok else '未通过'} 最小段落数 {rules['min_paragraphs']}（实际 {len(paragraphs)}）")

    # 语言检查
    if "language" in rules:
        total_checks += 1
        ok = _check_language(response, rules["language"])
        if ok:
            passed_checks += 1
        checks.append(f"  {'通过' if ok else '未通过'} 语言要求: {rules['language']}")

    score = int(100 * passed_checks / total_checks) if total_checks > 0 else 0
    return score, "\n".join(checks)


def _check_format(text: str, fmt: str) -> bool:
    """检查文本是否符合指定格式

    Args:
        text: 待检查的文本
        fmt: 格式标识，支持 "json" | "markdown_table" | "numbered_list" | "bullet_list"

    Returns:
        是否符合格式要求
    """
    if fmt == "json":
        try:
            json.loads(text.strip())
            return True
        except json.JSONDecodeError:
            # 尝试提取 JSON 围栏代码块
            match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
            if match:
                try:
                    json.loads(match.group(1).strip())
                    return True
                except json.JSONDecodeError:
                    pass
            return False

    elif fmt == "markdown_table":
        # 检查是否包含 Markdown 表格（至少一行含有多个 | 分隔符）
        return bool(re.search(r"\|.*\|.*\|", text))

    elif fmt == "numbered_list":
        # 检查是否包含编号列表（数字 + 句号/顿号/右括号 + 空格）
        return bool(re.search(r"^\s*\d+[.\u3001\uff09]\s", text, re.MULTILINE))

    elif fmt == "bullet_list":
        # 检查是否包含无序列表
        return bool(re.search(r"^\s*[-\u2022*]\s", text, re.MULTILINE))

    return False


def _check_language(text: str, language: str) -> bool:
    """简单的语言检查（基于中文字符占比）

    Args:
        text: 待检查的文本
        language: 语言标识，"chinese" 或 "english"

    Returns:
        是否符合语言要求
    """
    # 统计中文字符比例
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    total_chars = len(text.strip())
    if total_chars == 0:
        return False

    cn_ratio = cn_chars / total_chars

    if language == "chinese":
        return cn_ratio > 0.3  # 中文字符占 30% 以上
    elif language == "english":
        return cn_ratio < 0.1  # 中文字符低于 10%

    return True
