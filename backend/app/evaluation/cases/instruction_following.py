"""instruction_following 维度 — 15 道指令遵循题

测试模型严格遵循用户指令的能力，覆盖以下 5 类：
A. 格式控制（4 题）：JSON / Markdown 表格 / 编号列表 / Bullet list
B. 长度约束（3 题）：一句话 / 段落数 / 最低字数
C. 内容约束（3 题）：禁用词 / 引用数字 / 极简回答
D. 角色扮演（3 题）：律师 / 小孩 / Python 解释器
E. 多条件组合（2 题）：多条件同时满足
"""

from __future__ import annotations

from app.evaluation.test_models import TestCase


INSTRUCTION_FOLLOWING_TESTS: list[TestCase] = [
    # ============================================================
    # A. 格式控制（4 题）
    # ============================================================

    # instruct_01: 纯 JSON 输出
    TestCase(
        id="instruct_01",
        dimension="instruction_following",
        prompt=(
            "请列出中国四大一线城市及其2024年GDP排名。\n\n"
            "【格式要求】只输出 JSON 格式，不要任何其他文字、代码块标记或解释。"
            "JSON 格式为：[{\"city\": \"城市名\", \"rank\": 排名}]"
        ),
        scoring_type="format_check",
        format_rules={
            "format": "json",
        },
        difficulty="easy",
    ),

    # instruct_02: Markdown 表格
    TestCase(
        id="instruct_02",
        dimension="instruction_following",
        prompt=(
            "请用 Markdown 表格展示以下信息：\n"
            "- Python: 1991年发布，创始人 Guido van Rossum，主要用途 Web/AI\n"
            "- Java: 1995年发布，创始人 James Gosling，主要用途 企业应用\n"
            "- JavaScript: 1995年发布，创始人 Brendan Eich，主要用途 前端开发\n\n"
            "【格式要求】必须使用标准 Markdown 表格格式（含表头和分隔行），"
            "不要使用代码块包裹，不要添加任何额外说明。"
        ),
        scoring_type="format_check",
        format_rules={
            "format": "markdown_table",
        },
        difficulty="easy",
    ),

    # instruct_03: 编号列表 + 单条长度限制
    TestCase(
        id="instruct_03",
        dimension="instruction_following",
        prompt=(
            "请列出5个提高编程效率的建议。\n\n"
            "【格式要求】\n"
            "1. 使用编号列表（1. 2. 3. ...）\n"
            "2. 每条建议不超过20个字\n"
            "3. 不要写任何开头语或总结"
        ),
        scoring_type="format_check",
        format_rules={
            "format": "numbered_list",
            "max_length": 200,
        },
        difficulty="medium",
    ),

    # instruct_04: 纯 bullet list
    TestCase(
        id="instruct_04",
        dimension="instruction_following",
        prompt=(
            "请列出学习英语的6个有效方法。\n\n"
            "【格式要求】\n"
            "- 使用无序列表（bullet point）格式\n"
            "- 不要写标题、开头语或结尾总结\n"
            "- 直接从第一个要点开始"
        ),
        scoring_type="format_check",
        format_rules={
            "format": "bullet_list",
            "must_not_contain": ["总结", "以上", "总之", "综上"],
        },
        difficulty="easy",
    ),

    # ============================================================
    # B. 长度约束（3 题）
    # ============================================================

    # instruct_05: 一句话回答，不超过30字
    TestCase(
        id="instruct_05",
        dimension="instruction_following",
        prompt=(
            "什么是量子计算？\n\n"
            "【格式要求】用一句话回答，不超过30个字。不要分点、不要换行。"
        ),
        scoring_type="format_check",
        format_rules={
            "max_length": 30,
        },
        difficulty="medium",
    ),

    # instruct_06: 段落数和总长度约束
    TestCase(
        id="instruct_06",
        dimension="instruction_following",
        prompt=(
            "请介绍人工智能的发展历程。\n\n"
            "【格式要求】\n"
            "- 写3段话（用空行分隔）\n"
            "- 总长度在150到300字之间\n"
            "- 不要使用列表或标题"
        ),
        scoring_type="format_check",
        format_rules={
            "min_paragraphs": 3,
            "max_paragraphs": 3,
            "min_length": 150,
            "max_length": 300,
        },
        difficulty="hard",
    ),

    # instruct_07: 最低字数要求
    TestCase(
        id="instruct_07",
        dimension="instruction_following",
        prompt=(
            "请详细分析远程办公的优势和劣势。\n\n"
            "【格式要求】回答不少于500字，请充分展开论述。"
        ),
        scoring_type="format_check",
        format_rules={
            "min_length": 500,
        },
        difficulty="medium",
    ),

    # ============================================================
    # C. 内容约束（3 题）
    # ============================================================

    # instruct_08: 禁用词 + rubric 质量检查
    TestCase(
        id="instruct_08",
        dimension="instruction_following",
        prompt=(
            "请解释什么是机器学习，它有哪些常见的应用场景。\n\n"
            "【特别要求】在整个回答中不要提到「神经网络」这个词。"
            "你可以使用其他术语来描述相关概念。"
        ),
        scoring_type="format_check",
        format_rules={
            "must_not_contain": ["神经网络"],
            "min_length": 100,
        },
        rubric=[
            ("回答解释了机器学习的定义或核心概念", 30),
            ("提到了至少2个具体应用场景", 30),
        ],
        difficulty="medium",
    ),

    # instruct_09: 必须引用具体数字（rubric 检查）
    TestCase(
        id="instruct_09",
        dimension="instruction_following",
        prompt=(
            "请介绍全球气候变化的现状。\n\n"
            "【特别要求】在回答中必须引用至少3个具体的数字或统计数据"
            "（如温度变化、排放量、年份等），用数据说话。"
        ),
        scoring_type="rubric",
        rubric=[
            ("回答中包含至少3个具体数字或统计数据", 50),
            ("数字引用在合理范围内，没有明显编造", 25),
            ("回答围绕气候变化主题展开，内容相关", 25),
        ],
        difficulty="medium",
    ),

    # instruct_10: 极简回答
    TestCase(
        id="instruct_10",
        dimension="instruction_following",
        prompt=(
            "太阳是恒星吗？\n\n"
            "【格式要求】只回答「是」或「否」，不要添加任何解释、标点或额外文字。"
        ),
        scoring_type="format_check",
        format_rules={
            "max_length": 5,
        },
        difficulty="easy",
    ),

    # ============================================================
    # D. 角色扮演（3 题）
    # ============================================================

    # instruct_11: 律师角色
    TestCase(
        id="instruct_11",
        dimension="instruction_following",
        prompt=(
            "我和邻居因为噪音问题产生了纠纷，他每天深夜大声放音乐。我该怎么办？\n\n"
            "【角色要求】你是一名执业律师，请只用法律术语和法律框架来回答。"
            "引用相关法律条款或法规，给出专业的法律建议。"
        ),
        scoring_type="rubric",
        rubric=[
            ("回答中使用了法律术语（如：侵权、相邻权、民法典、治安管理处罚法等）", 40),
            ("引用了具体法律条款或法规名称", 30),
            ("给出了可操作的法律建议步骤", 30),
        ],
        difficulty="medium",
    ),

    # instruct_12: 5 岁小孩角色
    TestCase(
        id="instruct_12",
        dimension="instruction_following",
        prompt=(
            "请解释什么是人工智能。\n\n"
            "【角色要求】你是一个5岁的小孩子。请用一个5岁小朋友能理解的方式来解释，"
            "使用简单的词汇和生动的比喻，不要使用任何专业术语。"
        ),
        scoring_type="rubric",
        rubric=[
            ("语言风格简单活泼，像小孩子说话", 35),
            ("使用了生动的比喻或类比来解释概念", 35),
            ("没有使用专业术语（如：算法、模型、深度学习、训练等）", 30),
        ],
        difficulty="medium",
    ),

    # instruct_13: Python 解释器角色
    TestCase(
        id="instruct_13",
        dimension="instruction_following",
        prompt=(
            "```python\nprint(2 + 3)\nprint('hello' + ' ' + 'world')\nprint(len([1, 2, 3, 4]))\n```\n\n"
            "【角色要求】你是一个Python解释器，只输出上述代码的执行结果。"
            "不要输出任何解释、注释或额外文字，只输出程序的标准输出。"
        ),
        scoring_type="format_check",
        format_rules={
            "must_not_contain": ["print", "代码", "输出", "结果是", "执行", "解释", "python", "Python"],
            "must_contain": ["5", "hello world", "4"],
        },
        difficulty="medium",
    ),

    # ============================================================
    # E. 多条件组合（2 题）
    # ============================================================

    # instruct_14: 英文 + 长度 + 关键词 + 格式
    TestCase(
        id="instruct_14",
        dimension="instruction_following",
        prompt=(
            "What are the advantages of remote work?\n\n"
            "【Format requirements】\n"
            "1. Answer in English only\n"
            "2. Use exactly 3 bullet points\n"
            "3. Must include the words 'however' and 'therefore'\n"
            "4. Total length must not exceed 300 characters"
        ),
        scoring_type="format_check",
        format_rules={
            "language": "english",
            "format": "bullet_list",
            "must_contain": ["however", "therefore"],
            "max_length": 300,
        },
        difficulty="hard",
    ),

    # instruct_15: 首字母 + 句子数（rubric 检查）
    TestCase(
        id="instruct_15",
        dimension="instruction_following",
        prompt=(
            "请介绍健康饮食的重要性。\n\n"
            "【特别要求】\n"
            "1. 至少写5个句子\n"
            "2. 每个句子必须以不同的汉字开头（即5个句子的第一个字不能重复）\n"
            "3. 每个句子之间用句号分隔"
        ),
        scoring_type="rubric",
        rubric=[
            ("回答包含至少5个完整句子", 30),
            ("每个句子以不同的汉字开头（前5句的首字无重复）", 40),
            ("内容围绕健康饮食主题展开", 30),
        ],
        difficulty="hard",
    ),
]
