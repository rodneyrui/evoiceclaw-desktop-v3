"""eVoiceClaw Benchmark V2 — 技术知识维度测试用例

15 道题覆盖：AI/ML基础、数据库、架构设计、DevOps、网络安全、
分布式系统、大模型训练、向量数据库、通信协议、缓存、消息队列、
前端框架、API设计等技术领域。
"""

from __future__ import annotations

from app.evaluation.test_models import TestCase


KNOWLEDGE_TECH_TESTS: list[TestCase] = [
    TestCase(
        id="ktech_01",
        dimension="knowledge_tech",
        prompt=(
            "请简要解释以下3个AI技术概念（每个80字以内）：\n"
            "1. RAG（检索增强生成）\n"
            "2. MoE（混合专家模型）\n"
            "3. LoRA（低秩适配）"
        ),
        scoring_type="rubric",
        rubric=[
            ("RAG解释提到'检索'+'生成'的结合", 30),
            ("MoE解释提到'多专家'或'稀疏激活'", 35),
            ("LoRA解释提到'低秩'或'参数高效'或'微调'", 35),
        ],
        max_score=100,
        difficulty="easy",
    ),

    TestCase(
        id="ktech_02",
        dimension="knowledge_tech",
        prompt=(
            "请分析以下场景分别适合使用SQL数据库还是NoSQL数据库，并说明理由：\n\n"
            "场景A：电商平台的订单系统，需要强一致性事务，数据结构固定\n"
            "场景B：社交平台的用户动态Feed，数据结构灵活，读多写多，需要水平扩展\n"
            "场景C：IoT设备的时序数据，每秒写入数万条记录，查询以时间范围为主\n"
            "场景D：内容管理系统，文章结构复杂且经常变化，需要全文搜索"
        ),
        scoring_type="rubric",
        rubric=[
            ("场景A推荐SQL（如MySQL/PostgreSQL），理由涉及事务/ACID", 25),
            ("场景B推荐NoSQL（如MongoDB/Cassandra），理由涉及灵活/扩展", 25),
            ("场景C推荐时序数据库（如InfluxDB/TimescaleDB），理由涉及时序写入", 25),
            ("场景D推荐文档数据库或搜索引擎（如MongoDB/Elasticsearch），理由涉及灵活结构或全文搜索", 25),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="ktech_03",
        dimension="knowledge_tech",
        prompt=(
            "请对比微服务架构和单体架构的优缺点，并说明：\n"
            "1. 什么情况下应该选择单体架构？\n"
            "2. 什么情况下应该迁移到微服务？\n"
            "3. 微服务架构带来的主要技术挑战有哪些？"
        ),
        scoring_type="rubric",
        rubric=[
            ("列出单体架构的优点（简单/部署方便/调试容易等）", 15),
            ("列出微服务的优点（独立部署/技术栈灵活/可扩展等）", 15),
            ("单体适用场景合理（小团队/早期项目/简单业务）", 20),
            ("微服务迁移时机合理（团队变大/业务复杂/需要独立扩展）", 20),
            ("提到微服务挑战（网络延迟/分布式事务/服务治理/运维复杂）至少3项", 30),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="ktech_04",
        dimension="knowledge_tech",
        prompt=(
            "请解释以下容器化和编排概念：\n"
            "1. Docker 镜像(Image)和容器(Container)的区别是什么？\n"
            "2. Dockerfile 的作用是什么？请列出3个常用指令。\n"
            "3. Kubernetes 的 Pod、Service、Deployment 分别是什么？\n"
            "4. 为什么需要容器编排工具（如K8s）而不只用Docker？"
        ),
        scoring_type="keyword",
        expected_keywords=["镜像", "容器", "Dockerfile", "Pod", "Service", "Deployment"],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="ktech_05",
        dimension="knowledge_tech",
        prompt=(
            "请描述一个完整的 CI/CD 流水线应包含哪些阶段？\n"
            "假设项目是一个Python后端服务，部署在云服务器上。\n"
            "请按顺序列出每个阶段的名称、目的、使用的典型工具。"
        ),
        scoring_type="rubric",
        rubric=[
            ("包含代码检出/拉取阶段", 10),
            ("包含代码质量检查（lint/静态分析）阶段", 15),
            ("包含单元测试阶段", 15),
            ("包含构建/打包阶段（如Docker镜像构建）", 15),
            ("包含部署阶段（区分staging/production）", 20),
            ("提到具体工具（如GitHub Actions/Jenkins/GitLab CI等至少2个）", 15),
            ("阶段顺序合理", 10),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="ktech_06",
        dimension="knowledge_tech",
        prompt=(
            "请解释以下Web安全概念及其防御方式：\n"
            "1. XSS（跨站脚本攻击）：原理和防御\n"
            "2. CSRF（跨站请求伪造）：原理和防御\n"
            "3. SQL注入：原理和防御\n"
            "4. HTTPS相比HTTP的安全改进是什么？"
        ),
        scoring_type="keyword",
        expected_keywords=["XSS", "CSRF", "SQL注入", "HTTPS", "加密", "Token"],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="ktech_07",
        dimension="knowledge_tech",
        prompt=(
            "请解释分布式系统中的 CAP 定理：\n"
            "1. C、A、P 分别代表什么？\n"
            "2. 为什么三者不能同时满足？\n"
            "3. 请举例说明：一个系统选择 CP（牺牲可用性）的场景，和选择 AP（牺牲一致性）的场景\n"
            "4. 现实中如何通过'最终一致性'来缓解 CAP 的限制？"
        ),
        scoring_type="rubric",
        rubric=[
            ("正确解释 C（一致性）", 15),
            ("正确解释 A（可用性）", 15),
            ("正确解释 P（分区容忍性）", 15),
            ("说明三者不可兼得的原因（网络分区时必须在C和A之间选择）", 20),
            ("CP和AP场景举例合理", 20),
            ("提到最终一致性的概念和作用", 15),
        ],
        max_score=100,
        difficulty="hard",
    ),

    TestCase(
        id="ktech_08",
        dimension="knowledge_tech",
        prompt=(
            "请解释机器学习中以下概念：\n"
            "1. 什么是过拟合(Overfitting)？如何判断模型是否过拟合？\n"
            "2. 正则化(Regularization)如何缓解过拟合？请说明L1和L2正则化的区别。\n"
            "3. 交叉验证(Cross-Validation)的目的和常见方法。\n"
            "4. 偏差-方差权衡(Bias-Variance Tradeoff)是什么意思？"
        ),
        scoring_type="keyword",
        expected_keywords=["过拟合", "正则化", "L1", "L2", "交叉验证", "偏差", "方差"],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="ktech_09",
        dimension="knowledge_tech",
        prompt=(
            "请描述大语言模型(LLM)从训练到上线的完整流程，包括：\n"
            "1. 预训练(Pre-training)阶段：数据来源、训练目标、所需算力规模\n"
            "2. 有监督微调(SFT)阶段：数据格式、目的\n"
            "3. 人类反馈强化学习(RLHF)阶段：奖励模型训练、PPO 优化\n"
            "4. 推理部署阶段：常见的推理优化技术（至少列出3种）"
        ),
        scoring_type="rubric",
        rubric=[
            ("预训练阶段描述准确（提到大规模语料/自监督/next-token预测等）", 25),
            ("SFT阶段描述准确（提到指令数据/对话格式/有监督）", 20),
            ("RLHF阶段描述准确（提到奖励模型/PPO或DPO）", 25),
            ("推理优化列出≥3种（量化/KV Cache/投机采样/vLLM/TensorRT等）", 30),
        ],
        max_score=100,
        difficulty="hard",
    ),

    TestCase(
        id="ktech_10",
        dimension="knowledge_tech",
        prompt=(
            "请解释向量数据库和 Embedding 技术：\n"
            "1. 什么是文本 Embedding？它将文本转化为什么形式？\n"
            "2. 向量数据库（如 Milvus、Pinecone、Weaviate）与传统数据库的核心区别是什么？\n"
            "3. 向量相似度搜索的常见算法有哪些？（列出至少2种）\n"
            "4. 在 RAG 系统中，向量数据库扮演什么角色？"
        ),
        scoring_type="keyword",
        expected_keywords=["向量", "Embedding", "相似度", "余弦", "RAG", "检索"],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="ktech_11",
        dimension="knowledge_tech",
        prompt=(
            "请对比 WebSocket 和 HTTP 长轮询(Long Polling)两种实时通信方案：\n"
            "1. 两者的工作原理分别是什么？\n"
            "2. 在性能、资源消耗、延迟方面各有什么优劣？\n"
            "3. 分别适合什么场景？\n"
            "4. Server-Sent Events (SSE) 与前两者有何不同？什么场景下适合用 SSE？"
        ),
        scoring_type="rubric",
        rubric=[
            ("正确描述 WebSocket 工作原理（全双工、持久连接）", 20),
            ("正确描述长轮询原理（客户端等待服务器响应，超时重连）", 20),
            ("对比分析有数据或定性比较（资源消耗/延迟/复杂度）", 20),
            ("场景推荐合理（WebSocket适合聊天/游戏，长轮询适合兼容性要求高的场景）", 20),
            ("正确解释 SSE（单向推送/基于HTTP）并给出适用场景", 20),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="ktech_12",
        dimension="knowledge_tech",
        prompt=(
            "请回答关于 Redis 缓存的以下问题：\n"
            "1. Redis 常见的数据结构有哪些？各适合什么场景？\n"
            "2. 缓存穿透、缓存击穿、缓存雪崩分别是什么？如何防御？\n"
            "3. Redis 的持久化方式有哪些？各自的优缺点？\n"
            "4. 什么时候不应该使用 Redis？"
        ),
        scoring_type="rubric",
        rubric=[
            ("列出Redis数据结构≥4种（String/Hash/List/Set/Sorted Set等）", 15),
            ("正确解释缓存穿透及防御（布隆过滤器/空值缓存）", 20),
            ("正确解释缓存击穿及防御（互斥锁/热点预加载）", 15),
            ("正确解释缓存雪崩及防御（过期时间随机化/多级缓存）", 15),
            ("说明Redis持久化方式（RDB/AOF）及优缺点", 20),
            ("给出不适合使用Redis的场景（大数据量/强事务需求等）", 15),
        ],
        max_score=100,
        difficulty="hard",
    ),

    TestCase(
        id="ktech_13",
        dimension="knowledge_tech",
        prompt=(
            "请对比 Kafka 和 RabbitMQ 两种消息队列：\n"
            "1. 架构设计上有什么核心区别？\n"
            "2. 在吞吐量、延迟、消息可靠性方面各自的表现如何？\n"
            "3. 分别适合什么业务场景？\n"
            "4. 如果一个系统需要同时处理日志收集（高吞吐）和订单处理（高可靠），应该如何选择？"
        ),
        scoring_type="rubric",
        rubric=[
            ("描述 Kafka 架构特点（分布式日志/分区/消费者组）", 20),
            ("描述 RabbitMQ 架构特点（AMQP/Exchange/Queue/路由）", 20),
            ("性能对比合理（Kafka高吞吐/RabbitMQ低延迟灵活路由）", 20),
            ("场景推荐合理且有理由", 20),
            ("混合使用建议合理（日志用Kafka/订单用RabbitMQ或反之有论据）", 20),
        ],
        max_score=100,
        difficulty="hard",
    ),

    TestCase(
        id="ktech_14",
        dimension="knowledge_tech",
        prompt=(
            "请对比 React、Vue 和 Svelte 三个前端框架：\n"
            "1. 各自的核心理念/设计哲学是什么？\n"
            "2. 在性能、学习曲线、生态系统方面的对比\n"
            "3. 各自适合什么类型的项目？\n"
            "4. 6年各框架2025-202的发展趋势如何？"
        ),
        scoring_type="keyword",
        expected_keywords=["React", "Vue", "Svelte", "虚拟DOM", "编译", "组件"],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="ktech_15",
        dimension="knowledge_tech",
        prompt=(
            "请对比 RESTful API 和 GraphQL 两种 API 设计风格：\n"
            "1. 设计理念上的核心区别是什么？\n"
            "2. Over-fetching 和 Under-fetching 问题是什么？GraphQL 如何解决？\n"
            "3. 各自在缓存、错误处理、版本管理方面的表现\n"
            "4. 什么场景下应该选择 RESTful？什么场景下选择 GraphQL？"
        ),
        scoring_type="rubric",
        rubric=[
            ("正确描述 REST 核心理念（资源导向/HTTP动词/无状态）", 15),
            ("正确描述 GraphQL 核心理念（查询语言/客户端按需请求/单端点）", 15),
            ("解释 Over-fetching/Under-fetching 问题", 20),
            ("对比缓存和版本管理差异", 20),
            ("场景推荐合理且有论据", 15),
            ("提到各自的缺点（REST多端点管理/GraphQL复杂度和N+1问题等）", 15),
        ],
        max_score=100,
        difficulty="hard",
    ),
]
