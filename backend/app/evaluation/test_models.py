"""eVoiceClaw Benchmark V2 — 核心数据结构

定义评测框架中使用的所有数据模型：
- TestCase: 测试用例定义
- TestResult: 单次执行结果
- ModelReport: 单模型评测报告
- BenchmarkMeta: 评测元数据（可复现性）
"""

from dataclasses import dataclass, field


@dataclass
class TestCase:
    """测试用例定义

    每道题包含 prompt、评分方式、期望答案等信息。
    scoring_type 决定使用哪种评分器。
    """

    id: str                                             # 唯一标识，如 "coding_01"
    dimension: str                                      # 能力维度名，如 "coding"
    prompt: str                                         # 发送给模型的用户消息
    system_prompt: str = ""                             # 可选的系统提示
    tools: list[dict] | None = None                     # 工具定义（用于 agent_tool_use 维度）
    scoring_type: str = "keyword"                       # 评分方式：exact | keyword | rubric | tool_call | code_test | format_check
    expected_answer: str | None = None                  # exact 评分的标准答案
    expected_keywords: list[str] = field(default_factory=list)  # keyword 评分的必含关键词
    expected_tool_name: str | None = None               # tool_call 评分期望的工具名
    expected_tool_params: dict | None = None            # tool_call 评分期望的参数
    rubric: list[tuple[str, int]] = field(default_factory=list)  # rubric 评分条件列表，每项为 (条件描述, 分值)
    code_test_cases: list[dict] | None = None           # code_test 评分的测试用例
    format_rules: dict | None = None                    # format_check 评分规则
    max_score: int = 100                                # 满分分值
    difficulty: str = "medium"                          # 难度：easy | medium | hard


@dataclass
class TestResult:
    """单次执行结果

    记录一次 LLM 调用的完整信息：模型输出、得分、延迟等。
    """

    test_id: str                                        # 对应 TestCase.id
    dimension: str                                      # 能力维度名
    model_id: str                                       # 模型标识，如 "deepseek/deepseek-chat"
    score: int                                          # 得分 0-100
    max_score: int                                      # 满分分值
    response: str                                       # 模型原始输出文本
    tool_calls: list | None                             # 模型返回的工具调用（如有）
    latency_ms: int                                     # 调用耗时（毫秒）
    input_tokens: int = 0                               # 输入 token 数（来自 LLM usage）
    output_tokens: int = 0                              # 输出 token 数（来自 LLM usage）
    error: str | None = None                            # 错误信息（如有）
    scoring_detail: str = ""                            # 评分详情说明


@dataclass
class ModelReport:
    """单个模型的评测报告

    汇总该模型在所有维度上的得分和等级。
    dimension_scores 存储 0-100 原始分，dimension_grades 存储 1-5 等级。
    """

    model_id: str                                       # 模型标识
    dimension_scores: dict[str, float] = field(default_factory=dict)   # 维度 → 0-100 原始分
    dimension_grades: dict[str, int] = field(default_factory=dict)     # 维度 → 1-5 等级
    test_results: list[TestResult] = field(default_factory=list)       # 所有测试结果明细
    avg_latency_ms: int = 0                             # 平均延迟（毫秒）
    error_count: int = 0                                # 错误总数


@dataclass
class BenchmarkMeta:
    """评测元数据（可复现性）

    记录本次评测的环境信息，确保结果可追溯和复现。
    """

    benchmark_version: str = "2.0"                      # 框架版本
    test_hash: str = ""                                 # 题目内容 SHA256 哈希
    timestamp: str = ""                                 # 评测时间戳
    environment: dict = field(default_factory=dict)     # 运行环境（Python/litellm 版本等）
    judge_models: list[str] = field(default_factory=list)  # 裁判模型列表
    temperature: float = 0.0                            # 使用的温度参数
    runs_per_test: int = 3                              # 每题运行次数
