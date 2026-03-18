"""eVoiceClaw Benchmark V2 — 工具调用维度测试用例

15 道题覆盖：基础工具调用、工具选择、拒绝调用、文件操作、
多工具串联、复杂参数、数据库查询、邮件发送、API调用、批量操作等。
"""

from __future__ import annotations

from app.evaluation.test_models import TestCase


# ── 工具定义 ──

_CALC_TOOL = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "执行数学计算，支持加减乘除和复杂表达式",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，如 '100 * 1.12 ** 5'",
                }
            },
            "required": ["expression"],
        },
    },
}

_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "搜索互联网获取最新信息",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                }
            },
            "required": ["query"],
        },
    },
}

_FILE_READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "读取指定路径的文件内容",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径",
                }
            },
            "required": ["path"],
        },
    },
}

_FILE_WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "将内容写入指定路径的文件",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的内容",
                },
            },
            "required": ["path", "content"],
        },
    },
}

_DB_QUERY_TOOL = {
    "type": "function",
    "function": {
        "name": "query_database",
        "description": "执行 SQL 查询并返回结果",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL 查询语句"},
                "database": {"type": "string", "description": "数据库名称"},
            },
            "required": ["sql"],
        },
    },
}

_SEND_EMAIL_TOOL = {
    "type": "function",
    "function": {
        "name": "send_email",
        "description": "发送电子邮件",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "收件人邮箱"},
                "subject": {"type": "string", "description": "邮件主题"},
                "body": {"type": "string", "description": "邮件正文"},
            },
            "required": ["to", "subject", "body"],
        },
    },
}

_HTTP_REQUEST_TOOL = {
    "type": "function",
    "function": {
        "name": "http_request",
        "description": "发送 HTTP 请求",
        "parameters": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "description": "HTTP 方法: GET/POST/PUT/DELETE"},
                "url": {"type": "string", "description": "请求 URL"},
                "body": {"type": "string", "description": "请求体（JSON字符串）"},
            },
            "required": ["method", "url"],
        },
    },
}


# ── 题目定义 ──

TOOL_USE_TESTS: list[TestCase] = [
    # ── tool_01 ~ tool_05：从 Desktop cases.py 复制 ──

    TestCase(
        id="tool_01",
        dimension="agent_tool_use",
        prompt="请计算：如果一个产品的成本是100元，毛利率是40%，那么售价应该是多少元？",
        tools=[_CALC_TOOL],
        scoring_type="tool_call",
        expected_tool_name="calculator",
        expected_tool_params={"expression": "100 / (1 - 0.4)"},
        max_score=100,
        difficulty="easy",
    ),

    TestCase(
        id="tool_02",
        dimension="agent_tool_use",
        prompt="请帮我搜索最近一周关于人工智能大模型融资的新闻。",
        tools=[_SEARCH_TOOL],
        scoring_type="tool_call",
        expected_tool_name="web_search",
        expected_tool_params={"query": "AI大模型 融资 新闻"},
        max_score=100,
        difficulty="easy",
    ),

    TestCase(
        id="tool_03",
        dimension="agent_tool_use",
        prompt="请解释什么是机器学习？",
        tools=[_SEARCH_TOOL, _CALC_TOOL],
        scoring_type="rubric",
        rubric=[
            ("没有调用任何工具，直接回答", 60),
            ("解释准确且清晰", 40),
        ],
        max_score=100,
        difficulty="easy",
    ),

    TestCase(
        id="tool_04",
        dimension="agent_tool_use",
        prompt="请读取 /config/app.conf 文件的内容。",
        tools=[_FILE_READ_TOOL],
        scoring_type="tool_call",
        expected_tool_name="read_file",
        expected_tool_params={"path": "/config/app.conf"},
        max_score=100,
        difficulty="easy",
    ),

    TestCase(
        id="tool_05",
        dimension="agent_tool_use",
        prompt=(
            "某公司年营收1000万元，每年增长20%，请计算5年后的年营收是多少？"
            "计算公式：1000 * (1 + 0.20) ^ 5"
        ),
        tools=[_CALC_TOOL],
        scoring_type="tool_call",
        expected_tool_name="calculator",
        expected_tool_params={"expression": "1000 * (1 + 0.20) ** 5"},
        max_score=100,
        difficulty="easy",
    ),

    # ── tool_06 ~ tool_15：新增题目 ──

    TestCase(
        id="tool_06",
        dimension="agent_tool_use",
        prompt="请查询数据库，找出过去7天内订单金额最高的10个客户。数据库名为 ecommerce。",
        tools=[_DB_QUERY_TOOL, _CALC_TOOL],
        scoring_type="tool_call",
        expected_tool_name="query_database",
        expected_tool_params={"sql": "SELECT", "database": "ecommerce"},
        max_score=100,
        difficulty="easy",
    ),

    TestCase(
        id="tool_07",
        dimension="agent_tool_use",
        prompt=(
            "请给张经理（邮箱：zhang.manager@example.com）发一封邮件，"
            "通知他明天下午3点的产品评审会议改到会议室B，"
            "并提醒他带上Q1的销售数据报告。"
        ),
        tools=[_SEND_EMAIL_TOOL, _SEARCH_TOOL],
        scoring_type="tool_call",
        expected_tool_name="send_email",
        expected_tool_params={
            "to": "zhang.manager@example.com",
            "subject": "会议",
        },
        max_score=100,
        difficulty="easy",
    ),

    TestCase(
        id="tool_08",
        dimension="agent_tool_use",
        prompt=(
            "请调用天气API获取北京今天的天气信息。\n"
            "API地址：https://api.weather.example.com/v1/current\n"
            "请求方式：GET\n"
            "需要在URL中附加查询参数 city=beijing"
        ),
        tools=[_HTTP_REQUEST_TOOL, _SEARCH_TOOL, _CALC_TOOL],
        scoring_type="tool_call",
        expected_tool_name="http_request",
        expected_tool_params={
            "method": "GET",
            "url": "api.weather.example.com",
        },
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="tool_09",
        dimension="agent_tool_use",
        prompt=(
            "请执行以下步骤：\n"
            "1. 先读取 /data/monthly_report.csv 文件的内容\n"
            "2. 然后将报告摘要通过邮件发送给 boss@company.com\n\n"
            "请先执行第一步。"
        ),
        tools=[_FILE_READ_TOOL, _SEND_EMAIL_TOOL, _FILE_WRITE_TOOL],
        scoring_type="tool_call",
        expected_tool_name="read_file",
        expected_tool_params={"path": "/data/monthly_report.csv"},
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="tool_10",
        dimension="agent_tool_use",
        prompt=(
            "请向以下API发送POST请求来创建一个新用户：\n"
            "URL: https://api.example.com/v1/users\n"
            "请求体（JSON）：\n"
            "{\n"
            '  "name": "张三",\n'
            '  "email": "zhangsan@test.com",\n'
            '  "role": "admin",\n'
            '  "permissions": ["read", "write", "delete"]\n'
            "}"
        ),
        tools=[_HTTP_REQUEST_TOOL],
        scoring_type="tool_call",
        expected_tool_name="http_request",
        expected_tool_params={
            "method": "POST",
            "url": "https://api.example.com/v1/users",
        },
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="tool_11",
        dimension="agent_tool_use",
        prompt=(
            "请帮我写一首关于春天的五言绝句。"
        ),
        tools=[_CALC_TOOL, _SEARCH_TOOL, _DB_QUERY_TOOL, _SEND_EMAIL_TOOL],
        scoring_type="rubric",
        rubric=[
            ("没有调用任何工具，直接回答", 60),
            ("写出了一首符合五言绝句格式的诗（4行，每行5字）", 20),
            ("内容与春天相关", 20),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="tool_12",
        dimension="agent_tool_use",
        prompt=(
            "我需要查看 /logs/error.log 文件中最近的错误信息。请帮我读取这个文件。"
        ),
        tools=[_FILE_READ_TOOL, _FILE_WRITE_TOOL, _DB_QUERY_TOOL, _SEND_EMAIL_TOOL, _HTTP_REQUEST_TOOL],
        scoring_type="tool_call",
        expected_tool_name="read_file",
        expected_tool_params={"path": "/logs/error.log"},
        max_score=100,
        difficulty="easy",
    ),

    TestCase(
        id="tool_13",
        dimension="agent_tool_use",
        prompt=(
            "上下文信息：当前项目使用的数据库叫做 analytics_db。\n\n"
            "请帮我查询昨天的用户注册数量。用户表名为 users，注册时间字段为 created_at。"
        ),
        tools=[_DB_QUERY_TOOL, _CALC_TOOL],
        scoring_type="tool_call",
        expected_tool_name="query_database",
        expected_tool_params={
            "database": "analytics_db",
        },
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="tool_14",
        dimension="agent_tool_use",
        prompt=(
            "请帮我发送一封邮件给所有员工，但我还没确定收件人列表，也没想好邮件内容。\n"
            "你有什么建议？"
        ),
        tools=[_SEND_EMAIL_TOOL],
        scoring_type="rubric",
        rubric=[
            ("没有贸然调用 send_email 工具（因为缺少必要参数）", 50),
            ("向用户询问收件人信息", 25),
            ("向用户询问邮件内容或主题", 25),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="tool_15",
        dimension="agent_tool_use",
        prompt=(
            "请依次读取以下3个文件的内容：\n"
            "1. /config/database.yml\n"
            "2. /config/redis.yml\n"
            "3. /config/nginx.conf\n\n"
            "请先读取第一个文件。"
        ),
        tools=[_FILE_READ_TOOL, _FILE_WRITE_TOOL],
        scoring_type="tool_call",
        expected_tool_name="read_file",
        expected_tool_params={"path": "/config/database.yml"},
        max_score=100,
        difficulty="easy",
    ),
]
