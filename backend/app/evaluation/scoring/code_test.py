"""代码执行验证评分 — 提取代码块 + 沙箱执行 + 单元测试"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("benchmark.scoring.code_test")


def score_code_test(
    response: str,
    test_cases: list[dict],
) -> tuple[int, str]:
    """代码执行验证评分

    Args:
        response: 模型输出（应包含 Python 代码块）
        test_cases: 测试用例列表，每个为:
            {
                "input": "calculate_ltv(99, 0.05)",   # 测试表达式
                "expected": "1980.0",                   # 期望输出（字符串）
                "points": 25,                           # 该用例分值
            }

    Returns:
        (score, detail): 分数 0-100 和评分明细
    """
    if not test_cases:
        return 0, "无测试用例"

    # 1. 提取代码块
    code = _extract_python_code(response)
    if not code:
        return 0, "未找到 Python 代码块"

    # 2. 逐个测试用例执行
    total_points = sum(tc.get("points", 100 // len(test_cases)) for tc in test_cases)
    earned = 0
    details = []

    for i, tc in enumerate(test_cases):
        test_input = tc["input"]
        expected = str(tc["expected"])
        points = tc.get("points", 100 // len(test_cases))

        # 构建测试脚本：先执行模型生成的代码，再执行测试表达式
        # 多行 input 需要拆分：前面的行作为 setup，最后一行作为求值表达式
        if "\n" in test_input:
            input_lines = test_input.strip().split("\n")
            setup_lines = "\n".join(input_lines[:-1])
            eval_expr = input_lines[-1]
            test_script = f"""{code}

# 测试 setup
{setup_lines}

# 测试执行
try:
    result = {eval_expr}
    print(str(result))
except Exception as e:
    print(f"ERROR: {{e}}")
"""
        else:
            test_script = f"""{code}

# 测试执行
try:
    result = {test_input}
    print(str(result))
except Exception as e:
    print(f"ERROR: {{e}}")
"""

        success, output = _run_in_sandbox(test_script)

        if not success:
            details.append(f"  用例{i+1}: 执行失败 — {output[:100]}")
            continue

        output = output.strip()
        if output == expected or expected in output:
            earned += points
            details.append(f"  用例{i+1}: {test_input} -> {output} (+{points})")
        else:
            # 数值近似匹配（允许 2% 误差）
            try:
                if abs(float(output) - float(expected)) / max(abs(float(expected)), 0.001) < 0.02:
                    earned += points
                    details.append(f"  用例{i+1}: {test_input} -> {output} ≈ {expected} (+{points})")
                else:
                    details.append(f"  用例{i+1}: 期望 {expected}，实际 {output}")
            except ValueError:
                details.append(f"  用例{i+1}: 期望 {expected}，实际 {output}")

    score = int(100 * earned / total_points) if total_points > 0 else 0
    return score, "\n".join(details)


def _extract_python_code(text: str) -> str:
    """从模型输出中提取 Python 代码块

    按优先级尝试以下提取策略：
    1. 匹配 ```python ... ``` 围栏代码块
    2. 匹配 ``` ... ``` 通用围栏代码块
    3. 回退：查找缩进代码块或以 def/class 开头的行
    """
    # 优先匹配 ```python ... ```
    patterns = [
        r"```python\s*\n(.*?)```",
        r"```\s*\n(.*?)```",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            # 取最长的代码块（通常是主要实现）
            return max(matches, key=len).strip()

    # 回退：查找缩进代码块
    lines = text.split("\n")
    code_lines = []
    in_code = False
    for line in lines:
        if line.startswith("    ") or line.startswith("\t") or line.startswith("def ") or line.startswith("class "):
            in_code = True
            code_lines.append(line)
        elif in_code and line.strip() == "":
            code_lines.append(line)
        elif in_code:
            break

    return "\n".join(code_lines).strip() if code_lines else ""


def _run_in_sandbox(code: str, timeout: int = 10) -> tuple[bool, str]:
    """在沙箱中执行 Python 代码

    将代码写入临时文件，通过子进程执行，捕获标准输出和错误。

    Args:
        code: 要执行的 Python 代码
        timeout: 超时秒数（默认 10 秒，防止无限循环）

    Returns:
        (success, output): 是否成功和输出内容
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        f.flush()
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr[:500]
    except subprocess.TimeoutExpired:
        return False, "执行超时"
    except Exception as e:
        return False, str(e)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
