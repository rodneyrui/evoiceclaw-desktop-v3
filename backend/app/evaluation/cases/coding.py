"""测试用例 — coding 维度（15 题）

保留 Desktop 版原有 5 题（code_01 ~ code_05），新增 10 题（code_06 ~ code_15）。
新增题目覆盖：递归/DP、正则、OOP 类设计、错误处理、文件操作、API 设计、
数据结构、测试编写、性能优化、复杂 SQL。
其中 code_06、code_08、code_13 使用 code_test 评分方式。
"""

from app.evaluation.test_models import TestCase


CODING_TESTS: list[TestCase] = [
    # ────────────────────────────────────────
    # 原有 5 题（从 Desktop 迁移，内容不变）
    # ────────────────────────────────────────
    TestCase(
        id="code_01_function",
        dimension="coding",
        prompt=(
            "写一个 Python 函数 `calculate_ltv(arpu: float, churn_rate: float) -> float`，\n"
            "计算客户生命周期价值。公式：LTV = ARPU / churn_rate\n"
            "要求：参数验证（churn_rate > 0），类型提示，docstring。"
        ),
        scoring_type="keyword",
        expected_keywords=["def calculate_ltv", "arpu", "churn_rate", "return"],
        max_score=100,
        difficulty="easy",
    ),
    TestCase(
        id="code_02_debug",
        dimension="coding",
        prompt=(
            "以下 Python 代码有 bug，请找出并修复：\n\n"
            "```python\n"
            "def merge_sorted_lists(a: list[int], b: list[int]) -> list[int]:\n"
            "    result = []\n"
            "    i, j = 0, 0\n"
            "    while i < len(a) and j < len(b):\n"
            "        if a[i] <= b[j]:\n"
            "            result.append(a[i])\n"
            "            i += 1\n"
            "        else:\n"
            "            result.append(b[j])\n"
            "            j += 1\n"
            "    return result\n"
            "```\n\n"
            "提示：当一个列表遍历完后，另一个列表的剩余元素没有处理。"
        ),
        scoring_type="keyword",
        expected_keywords=["result.extend", "a[i:]", "b[j:]"],
        max_score=100,
        difficulty="easy",
    ),
    TestCase(
        id="code_03_async_pattern",
        dimension="coding",
        prompt=(
            "写一个 Python async 函数，并发请求多个 API 并收集结果：\n\n"
            "```python\n"
            "async def fetch_all(urls: list[str]) -> list[dict]:\n"
            "    # 使用 aiohttp 并发请求所有 url\n"
            "    # 返回所有响应的 JSON 结果\n"
            "    # 任何单个请求失败不影响其他请求\n"
            "    pass\n"
            "```\n"
            "请实现这个函数。"
        ),
        scoring_type="keyword",
        expected_keywords=["asyncio.gather", "aiohttp", "async with"],
        max_score=100,
        difficulty="medium",
    ),
    TestCase(
        id="code_04_data_processing",
        dimension="coding",
        prompt=(
            "写一个 Python 函数，处理以下格式的用户行为日志：\n\n"
            "```\n"
            "logs = [\n"
            '    {"user_id": "u1", "action": "click", "timestamp": 1000},\n'
            '    {"user_id": "u2", "action": "purchase", "timestamp": 1001},\n'
            '    {"user_id": "u1", "action": "purchase", "timestamp": 1002},\n'
            '    {"user_id": "u3", "action": "click", "timestamp": 1003},\n'
            '    {"user_id": "u1", "action": "click", "timestamp": 1004},\n'
            "]\n"
            "```\n\n"
            "要求：\n"
            "1. 统计每个用户的操作次数\n"
            "2. 计算整体的购买转化率（有purchase的用户数/总用户数）\n"
            "3. 返回结果字典包含 `user_stats` 和 `conversion_rate`"
        ),
        scoring_type="keyword",
        expected_keywords=["def ", "user_stats", "conversion_rate"],
        max_score=100,
        difficulty="medium",
    ),
    TestCase(
        id="code_05_sql",
        dimension="coding",
        prompt=(
            "写一个 SQL 查询，从 `orders` 表中找出最近30天内：\n"
            "1. 每个客户的总消费金额\n"
            "2. 按总消费金额降序排列\n"
            "3. 只返回消费超过1000元的客户\n"
            "4. 关联 `customers` 表获取客户名称\n\n"
            "表结构：\n"
            "- orders: id, customer_id, amount, created_at\n"
            "- customers: id, name, email"
        ),
        scoring_type="keyword",
        expected_keywords=["SELECT", "JOIN", "GROUP BY", "HAVING", "ORDER BY"],
        max_score=100,
        difficulty="medium",
    ),

    # ────────────────────────────────────────
    # 新增 10 题（code_06 ~ code_15）
    # ────────────────────────────────────────

    # code_06: 递归/动态规划 — 0/1 背包问题（code_test 评分）
    TestCase(
        id="code_06_dp_knapsack",
        dimension="coding",
        prompt=(
            "请用 Python 实现 0/1 背包问题的动态规划解法。\n\n"
            "函数签名：\n"
            "```python\n"
            "def knapsack(capacity: int, weights: list[int], values: list[int]) -> int:\n"
            "    \"\"\"返回在不超过 capacity 重量限制下能获得的最大价值。\n"
            "    \n"
            "    Args:\n"
            "        capacity: 背包容量\n"
            "        weights: 每个物品的重量列表\n"
            "        values: 每个物品的价值列表\n"
            "    Returns:\n"
            "        最大价值（整数）\n"
            "    \"\"\"\n"
            "```\n\n"
            "示例：\n"
            "- knapsack(10, [2, 3, 4, 5], [3, 4, 5, 6]) 应返回 13\n"
            "  （选第2、3、4个物品，重量3+4+5=12>10，不行；选1、2、4，重量2+3+5=10，价值3+4+6=13）\n"
            "- knapsack(0, [1, 2], [10, 20]) 应返回 0\n"
            "- knapsack(5, [], []) 应返回 0\n\n"
            "要求使用动态规划（非递归暴力搜索），时间复杂度 O(n*capacity)。"
        ),
        scoring_type="code_test",
        code_test_cases=[
            {"input": "knapsack(10, [2, 3, 4, 5], [3, 4, 5, 6])", "expected": "13"},
            {"input": "knapsack(0, [1, 2], [10, 20])", "expected": "0"},
            {"input": "knapsack(5, [], [])", "expected": "0"},
            {"input": "knapsack(7, [1, 3, 4, 5], [1, 4, 5, 7])", "expected": "9"},
            {"input": "knapsack(3, [5, 6, 7], [10, 20, 30])", "expected": "0"},
            {"input": "knapsack(50, [10, 20, 30], [60, 100, 120])", "expected": "220"},
        ],
        max_score=100,
        difficulty="medium",
    ),

    # code_07: 字符串处理 — 正则表达式提取信息（keyword 评分）
    TestCase(
        id="code_07_regex_extract",
        dimension="coding",
        prompt=(
            "写一个 Python 函数，使用正则表达式从一段混合文本中提取所有信息：\n\n"
            "```python\n"
            "def extract_contacts(text: str) -> dict:\n"
            '    """从文本中提取联系信息。\n'
            "    \n"
            "    返回字典包含：\n"
            "    - emails: 所有邮箱地址列表\n"
            "    - phones: 所有手机号码列表（中国大陆11位手机号，1开头）\n"
            "    - urls: 所有 URL 列表（http 或 https 开头）\n"
            '    """\n'
            "```\n\n"
            "测试文本示例：\n"
            '```\n'
            '"请联系张三 zhangsan@example.com 或拨打 13812345678，\n'
            '  官网 https://www.example.com，备用邮箱 lisi@test.org，\n'
            '  李四手机 15900001111，文档地址 http://docs.example.com/api"\n'
            '```\n\n'
            "要求：\n"
            "1. 使用 `re` 模块\n"
            "2. 邮箱正则要支持常见格式（xxx@xxx.xxx）\n"
            "3. 手机号正则匹配 1 开头的 11 位数字\n"
            "4. URL 正则匹配 http:// 或 https:// 开头的完整地址"
        ),
        scoring_type="keyword",
        expected_keywords=["import re", "re.findall", "emails", "phones", "urls"],
        max_score=100,
        difficulty="medium",
    ),

    # code_08: OOP 类设计 — LRU 缓存类（code_test 评分）
    TestCase(
        id="code_08_lru_cache",
        dimension="coding",
        prompt=(
            "请用 Python 实现一个 LRU（最近最少使用）缓存类，不使用 functools.lru_cache。\n\n"
            "```python\n"
            "class LRUCache:\n"
            '    """LRU 缓存实现。\n'
            "    \n"
            "    支持 O(1) 时间复杂度的 get 和 put 操作。\n"
            "    当缓存满时，淘汰最近最少使用的键值对。\n"
            '    """\n'
            "    \n"
            "    def __init__(self, capacity: int):\n"
            '        """初始化缓存，capacity 为最大容量。"""\n'
            "        pass\n"
            "    \n"
            "    def get(self, key: str) -> int:\n"
            '        """获取键对应的值，不存在则返回 -1。"""\n'
            "        pass\n"
            "    \n"
            "    def put(self, key: str, value: int) -> None:\n"
            '        """插入或更新键值对。缓存满时淘汰最久未使用的。"""\n'
            "        pass\n"
            "```\n\n"
            "示例：\n"
            "```python\n"
            "cache = LRUCache(2)\n"
            'cache.put("a", 1)\n'
            'cache.put("b", 2)\n'
            'cache.get("a")      # 返回 1\n'
            'cache.put("c", 3)   # 淘汰 key "b"\n'
            'cache.get("b")      # 返回 -1（已被淘汰）\n'
            'cache.get("c")      # 返回 3\n'
            "```\n\n"
            "要求：使用 OrderedDict 或自己实现双向链表 + 哈希表。"
        ),
        scoring_type="code_test",
        code_test_cases=[
            {
                "input": (
                    "cache = LRUCache(2)\n"
                    "cache.put('a', 1)\n"
                    "cache.put('b', 2)\n"
                    "cache.get('a')"
                ),
                "expected": "1",
            },
            {
                "input": (
                    "cache = LRUCache(2)\n"
                    "cache.put('a', 1)\n"
                    "cache.put('b', 2)\n"
                    "cache.get('a')\n"
                    "cache.put('c', 3)\n"
                    "cache.get('b')"
                ),
                "expected": "-1",
            },
            {
                "input": (
                    "cache = LRUCache(2)\n"
                    "cache.put('a', 1)\n"
                    "cache.put('b', 2)\n"
                    "cache.get('a')\n"
                    "cache.put('c', 3)\n"
                    "cache.get('c')"
                ),
                "expected": "3",
            },
            {
                "input": (
                    "cache = LRUCache(1)\n"
                    "cache.put('x', 10)\n"
                    "cache.put('y', 20)\n"
                    "cache.get('x')"
                ),
                "expected": "-1",
            },
            {
                "input": (
                    "cache = LRUCache(2)\n"
                    "cache.put('a', 1)\n"
                    "cache.put('a', 99)\n"
                    "cache.get('a')"
                ),
                "expected": "99",
            },
        ],
        max_score=100,
        difficulty="hard",
    ),

    # code_09: 错误处理 — retry 装饰器（code_test 评分）
    TestCase(
        id="code_09_retry_decorator",
        dimension="coding",
        prompt=(
            "请用 Python 实现一个通用的 retry 装饰器：\n\n"
            "```python\n"
            "def retry(max_retries: int = 3, delay: float = 0, exceptions: tuple = (Exception,)):\n"
            '    """重试装饰器。\n'
            "    \n"
            "    Args:\n"
            "        max_retries: 最大重试次数（不含首次调用）\n"
            "        delay: 每次重试之间的等待秒数（设为0则不等待）\n"
            "        exceptions: 需要捕获并重试的异常类型元组\n"
            "    \n"
            "    行为：\n"
            "    - 首次调用失败后，最多重试 max_retries 次\n"
            "    - delay > 0 时，每次重试前等待 delay 秒（使用 time.sleep）\n"
            "    - 只捕获 exceptions 中指定的异常类型\n"
            "    - 所有重试都失败后，抛出最后一次的异常\n"
            "    - 使用 functools.wraps 保持被装饰函数的元信息\n"
            '    """\n'
            "```\n\n"
            "要求：\n"
            "1. 使用三层嵌套函数（装饰器工厂模式）\n"
            "2. 导入并使用 `functools.wraps`\n"
            "3. 支持被装饰函数的任意参数（*args, **kwargs）\n"
            "4. delay 默认为 0（测试时不实际等待）"
        ),
        scoring_type="code_test",
        code_test_cases=[
            {
                "input": (
                    "@retry(max_retries=3, delay=0, exceptions=(ValueError,))\n"
                    "def fail_once():\n"
                    "    if not hasattr(fail_once, 'called'):\n"
                    "        fail_once.called = True\n"
                    "        raise ValueError('first fail')\n"
                    "    return 'success'\n"
                    "fail_once()"
                ),
                "expected": "success",
            },
            {
                "input": (
                    "@retry(max_retries=3, delay=0, exceptions=(ValueError,))\n"
                    "def always_fail():\n"
                    "    raise ValueError('always fail')\n"
                    "try:\n"
                    "    always_fail()\n"
                    "except ValueError as e:\n"
                    "    print('caught')"
                ),
                "expected": "caught",
            },
            {
                "input": (
                    "@retry(max_retries=0, delay=0, exceptions=(ValueError,))\n"
                    "def no_retry():\n"
                    "    raise ValueError('no retry')\n"
                    "try:\n"
                    "    no_retry()\n"
                    "except ValueError as e:\n"
                    "    print('direct catch')"
                ),
                "expected": "direct catch",
            },
        ],
        max_score=100,
        difficulty="medium",
    ),

    # code_10: 文件操作 — CSV 读写+数据聚合（keyword 评分）
    TestCase(
        id="code_10_csv_aggregation",
        dimension="coding",
        prompt=(
            "写一个 Python 函数，读取一个 CSV 文件并按指定列进行数据聚合，将结果写入新 CSV。\n\n"
            "```python\n"
            "def aggregate_csv(\n"
            "    input_path: str,\n"
            "    output_path: str,\n"
            "    group_by: str,\n"
            "    agg_column: str,\n"
            "    agg_func: str = 'sum'\n"
            ") -> dict:\n"
            '    """读取 CSV，按 group_by 列分组，对 agg_column 列执行聚合。\n'
            "    \n"
            "    Args:\n"
            "        input_path: 输入 CSV 文件路径\n"
            "        output_path: 输出 CSV 文件路径\n"
            "        group_by: 分组列名\n"
            "        agg_column: 聚合列名\n"
            "        agg_func: 聚合函数，支持 'sum'、'avg'、'count'、'max'、'min'\n"
            "    \n"
            "    Returns:\n"
            "        聚合结果字典 {分组值: 聚合值}\n"
            '    """\n'
            "```\n\n"
            "输入 CSV 示例（sales.csv）：\n"
            "```\n"
            "region,product,amount\n"
            "华东,手机,5000\n"
            "华北,电脑,8000\n"
            "华东,电脑,6000\n"
            "华北,手机,3000\n"
            "华东,手机,4500\n"
            "```\n\n"
            "调用 `aggregate_csv('sales.csv', 'result.csv', 'region', 'amount', 'sum')` 后，\n"
            "result.csv 内容应为：\n"
            "```\n"
            "region,amount_sum\n"
            "华东,15500\n"
            "华北,11000\n"
            "```\n\n"
            "要求：\n"
            "1. 使用 `csv` 标准库（不使用 pandas）\n"
            "2. 聚合函数支持 sum/avg/count/max/min 五种\n"
            "3. 正确处理文件编码（utf-8）"
        ),
        scoring_type="keyword",
        expected_keywords=["import csv", "csv.reader", "csv.writer", "group_by", "agg_func"],
        max_score=100,
        difficulty="medium",
    ),

    # code_11: API 设计 — FastAPI 端点（keyword 评分）
    TestCase(
        id="code_11_fastapi_endpoint",
        dimension="coding",
        prompt=(
            "请用 FastAPI 设计一个简单的待办事项（Todo）API，包含以下端点：\n\n"
            "1. `POST /todos` — 创建待办事项\n"
            "   - 请求体：`{\"title\": \"...\", \"description\": \"...\", \"priority\": 1-5}`\n"
            "   - 返回：创建的待办事项（含自动生成的 id 和 created_at）\n\n"
            "2. `GET /todos` — 获取待办列表\n"
            "   - 支持查询参数：`priority`（可选，按优先级过滤）、`done`（可选，按完成状态过滤）\n"
            "   - 返回：待办事项列表\n\n"
            "3. `PUT /todos/{todo_id}` — 更新待办事项\n"
            "   - 请求体：可部分更新 title、description、priority、done\n"
            "   - 不存在时返回 404\n\n"
            "4. `DELETE /todos/{todo_id}` — 删除待办事项\n"
            "   - 不存在时返回 404\n\n"
            "要求：\n"
            "1. 使用 Pydantic BaseModel 定义请求和响应模型\n"
            "2. 使用内存字典存储数据（不需要数据库）\n"
            "3. 包含合理的状态码（201 创建成功、404 不存在等）\n"
            "4. 添加类型注解"
        ),
        scoring_type="keyword",
        expected_keywords=[
            "FastAPI",
            "BaseModel",
            "POST",
            "GET",
            "PUT",
            "DELETE",
            "@app.",
            "todo_id",
            "HTTPException",
            "status_code",
        ],
        max_score=100,
        difficulty="medium",
    ),

    # code_12: 数据结构 — 最小堆实现（keyword 评分）
    TestCase(
        id="code_12_min_heap",
        dimension="coding",
        prompt=(
            "请用 Python 手动实现一个最小堆（Min Heap），不使用 heapq 模块。\n\n"
            "```python\n"
            "class MinHeap:\n"
            '    """最小堆实现。\n'
            "    \n"
            "    支持以下操作：\n"
            "    - push(val): 插入元素\n"
            "    - pop(): 弹出并返回最小元素\n"
            "    - peek(): 查看最小元素（不弹出）\n"
            "    - size(): 返回堆中元素数量\n"
            '    """\n'
            "    \n"
            "    def __init__(self):\n"
            "        self._data = []\n"
            "    \n"
            "    def push(self, val: int) -> None:\n"
            '        """插入元素并上浮调整。"""\n'
            "        pass\n"
            "    \n"
            "    def pop(self) -> int:\n"
            '        """弹出最小元素并下沉调整。堆为空时抛出 IndexError。"""\n'
            "        pass\n"
            "    \n"
            "    def peek(self) -> int:\n"
            '        """返回最小元素。堆为空时抛出 IndexError。"""\n'
            "        pass\n"
            "    \n"
            "    def size(self) -> int:\n"
            '        """返回堆中元素数量。"""\n'
            "        pass\n"
            "```\n\n"
            "要求：\n"
            "1. 使用数组实现（self._data 列表）\n"
            "2. push 操作：添加到末尾后执行上浮（sift up / bubble up）\n"
            "3. pop 操作：将末尾元素移到根节点后执行下沉（sift down / bubble down）\n"
            "4. 父子节点索引关系：parent = (i-1)//2, left = 2*i+1, right = 2*i+2\n"
            "5. 实现 `_sift_up` 和 `_sift_down` 辅助方法"
        ),
        scoring_type="keyword",
        expected_keywords=[
            "class MinHeap",
            "_sift_up",
            "_sift_down",
            "self._data",
            "def push",
            "def pop",
            "def peek",
        ],
        max_score=100,
        difficulty="hard",
    ),

    # code_13: 测试编写 — 给函数写 pytest 测试（keyword 评分）
    TestCase(
        id="code_13_pytest_tests",
        dimension="coding",
        prompt=(
            "以下是一个密码强度检测函数，请为它编写完整的 pytest 测试：\n\n"
            "```python\n"
            "def check_password_strength(password: str) -> dict:\n"
            '    """检测密码强度，返回评分和详细信息。\n'
            "    \n"
            "    评分规则（每项 20 分，满分 100）：\n"
            "    - 长度 >= 8: +20\n"
            "    - 包含大写字母: +20\n"
            "    - 包含小写字母: +20\n"
            "    - 包含数字: +20\n"
            "    - 包含特殊字符(!@#$%^&*): +20\n"
            "    \n"
            "    返回：\n"
            "    {\n"
            '        "score": int,          # 0-100\n'
            '        "level": str,          # "weak"(0-40) / "medium"(41-60) / "strong"(61-100)\n'
            '        "has_upper": bool,\n'
            '        "has_lower": bool,\n'
            '        "has_digit": bool,\n'
            '        "has_special": bool,\n'
            '        "long_enough": bool\n'
            "    }\n"
            '    """\n'
            "    result = {\n"
            '        "has_upper": any(c.isupper() for c in password),\n'
            '        "has_lower": any(c.islower() for c in password),\n'
            '        "has_digit": any(c.isdigit() for c in password),\n'
            '        "has_special": any(c in "!@#$%^&*" for c in password),\n'
            '        "long_enough": len(password) >= 8,\n'
            "    }\n"
            "    score = sum(20 for v in result.values() if v)\n"
            '    result["score"] = score\n'
            "    if score <= 40:\n"
            '        result["level"] = "weak"\n'
            "    elif score <= 60:\n"
            '        result["level"] = "medium"\n'
            "    else:\n"
            '        result["level"] = "strong"\n'
            "    return result\n"
            "```\n\n"
            "请写出完整的 pytest 测试文件，要求：\n"
            "1. 至少覆盖 6 个测试用例\n"
            "2. 覆盖弱/中/强三个等级\n"
            "3. 测试边界情况（空字符串、刚好8位）\n"
            "4. 使用 `@pytest.mark.parametrize` 参数化至少一组测试\n"
            "5. 函数命名遵循 `test_xxx` 格式"
        ),
        scoring_type="keyword",
        expected_keywords=[
            "import pytest",
            "def test_",
            "check_password_strength",
            "assert",
            "parametrize",
            "weak",
            "strong",
        ],
        max_score=100,
        difficulty="medium",
    ),

    # code_14: 性能优化 — 优化低效代码（keyword 评分）
    TestCase(
        id="code_14_optimization",
        dimension="coding",
        prompt=(
            "以下 Python 代码实现了一个查找两数之和的功能，但性能很差（O(n^2)）。\n"
            "请优化到 O(n) 时间复杂度，并解释优化思路。\n\n"
            "原始代码：\n"
            "```python\n"
            "def find_two_sum(nums: list[int], target: int) -> tuple[int, int] | None:\n"
            '    """找到列表中两个数使其和等于 target，返回它们的索引。\n'
            "    如果不存在则返回 None。\n"
            '    """\n'
            "    for i in range(len(nums)):\n"
            "        for j in range(i + 1, len(nums)):\n"
            "            if nums[i] + nums[j] == target:\n"
            "                return (i, j)\n"
            "    return None\n"
            "```\n\n"
            "要求：\n"
            "1. 优化后时间复杂度为 O(n)\n"
            "2. 使用哈希表（字典）来实现\n"
            "3. 保持相同的函数签名和返回格式\n"
            "4. 解释为什么优化后是 O(n)"
        ),
        scoring_type="keyword",
        expected_keywords=["dict", "target - ", "O(n)", "def find_two_sum"],
        max_score=100,
        difficulty="easy",
    ),

    # code_15: 复杂 SQL — 窗口函数+子查询（keyword 评分）
    TestCase(
        id="code_15_advanced_sql",
        dimension="coding",
        prompt=(
            "请编写一个 SQL 查询，满足以下需求：\n\n"
            "表结构：\n"
            "- `employees`: id, name, department, salary, hire_date\n"
            "- `departments`: id, name, budget\n\n"
            "需求：\n"
            "1. 查询每个部门的员工工资排名（使用窗口函数 RANK 或 ROW_NUMBER）\n"
            "2. 只返回每个部门工资前3名的员工\n"
            "3. 同时显示该员工的工资与部门平均工资的差值\n"
            "4. 结果包含：员工姓名、部门名称、工资、部门内排名、与部门均值的差值\n"
            "5. 按部门名称升序、排名升序排列\n\n"
            "请使用标准 SQL 语法（兼容 PostgreSQL）。"
        ),
        scoring_type="keyword",
        expected_keywords=[
            "RANK()",
            "OVER",
            "PARTITION BY",
            "AVG(",
            "JOIN",
            "WHERE",
        ],
        max_score=100,
        difficulty="hard",
    ),
]
