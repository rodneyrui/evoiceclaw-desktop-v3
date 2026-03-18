"""eVoiceClaw Benchmark V2 — 商业知识维度测试用例

15 道题覆盖：融资条款、SaaS指标、商业模式、竞品分析、财务报表、
股权激励、产品生命周期、用户增长、定价策略、投资条款、
市场规模、上市路径、VC生态、单位经济学、商业谈判。

合并了 Desktop V1 的 finance 和 market 两个子领域。
"""

from __future__ import annotations

from app.evaluation.test_models import TestCase


KNOWLEDGE_BUSINESS_TESTS: list[TestCase] = [
    TestCase(
        id="kbiz_01",
        dimension="knowledge_business",
        prompt=(
            "种子轮融资中常见的投资条款有哪些？请列出5个关键条款并简要说明其含义。\n"
            "（如：对赌协议、优先清算权，反稀释条款等）"
        ),
        scoring_type="rubric",
        rubric=[
            ("列出5个或以上的条款名称", 30),
            ("每个条款有简要说明", 30),
            ("条款选择合理且贴近种子轮场景", 20),
            ("解释准确无事实性错误", 20),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="kbiz_02",
        dimension="knowledge_business",
        prompt=(
            "请解释以下SaaS行业指标的含义和健康标准：\n"
            "1. MRR（Monthly Recurring Revenue）\n"
            "2. Churn Rate\n"
            "3. NPS（Net Promoter Score）\n"
            "4. NDR（Net Dollar Retention）"
        ),
        scoring_type="rubric",
        rubric=[
            ("MRR解释正确且提到'月经常性收入'", 20),
            ("Churn Rate解释正确且提到'流失'", 20),
            ("NPS解释正确且提到'净推荐'或评分范围", 25),
            ("NDR解释正确且提到'净收入留存'或>100%为健康", 35),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="kbiz_03",
        dimension="knowledge_business",
        prompt=(
            "请用商业模式画布(Business Model Canvas)分析一家AI SaaS公司的商业模式。\n"
            "假设这家公司提供AI客服解决方案，面向中小型电商企业。\n"
            "请完整填写9个要素，每个要素至少包含2条具体内容。"
        ),
        scoring_type="rubric",
        rubric=[
            ("包含客户细分(Customer Segments)", 10),
            ("包含价值主张(Value Propositions)", 15),
            ("包含渠道通路(Channels)", 10),
            ("包含客户关系(Customer Relationships)", 10),
            ("包含收入来源(Revenue Streams)", 15),
            ("包含核心资源(Key Resources)", 10),
            ("包含关键业务(Key Activities)", 10),
            ("包含重要合作(Key Partnerships)", 10),
            ("包含成本结构(Cost Structure)", 10),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="kbiz_04",
        dimension="knowledge_business",
        prompt=(
            "请使用波特五力模型和SWOT分析，分析中国AI大模型行业的竞争格局：\n"
            "1. 波特五力：供应商议价能力、买方议价能力、新进入者威胁、替代品威胁、行业内竞争\n"
            "2. 对一家新入场的AI创业公司做SWOT分析（优势、劣势、机会、威胁）"
        ),
        scoring_type="rubric",
        rubric=[
            ("五力分析中提到供应商议价能力（算力/芯片供应）", 15),
            ("五力分析中提到行业内竞争激烈", 10),
            ("五力分析分析合理且与AI行业实际情况相符", 15),
            ("SWOT分析包含4个象限", 20),
            ("SWOT内容具体而非泛泛而谈（与AI行业紧密相关）", 20),
            ("有基于分析的战略建议", 20),
        ],
        max_score=100,
        difficulty="hard",
    ),

    TestCase(
        id="kbiz_05",
        dimension="knowledge_business",
        prompt=(
            "请解释企业财务三大报表的核心内容和关联关系：\n"
            "1. 资产负债表(Balance Sheet)的核心等式和关键科目\n"
            "2. 利润表(Income Statement)的关键科目和计算逻辑\n"
            "3. 现金流量表(Cash Flow Statement)的三大部分\n"
            "4. 三张表之间是如何相互关联的？\n"
            "5. 为什么一家'利润表盈利'的公司可能会'现金流断裂'？"
        ),
        scoring_type="keyword",
        expected_keywords=["资产", "负债", "所有者权益", "营业收入", "净利润", "经营活动", "投资活动", "筹资活动"],
        max_score=100,
        difficulty="hard",
    ),

    TestCase(
        id="kbiz_06",
        dimension="knowledge_business",
        prompt=(
            "请解释创业公司股权激励的核心概念：\n"
            "1. 期权池(Option Pool)的常见大小和设立时机\n"
            "2. 行权价(Exercise Price/Strike Price)如何确定？\n"
            "3. 什么是 Cliff 期和 Vesting 期？常见的 Vesting Schedule 是什么？\n"
            "4. 期权和受限股(RSU)的区别是什么？\n"
            "5. 员工离职时期权如何处理？"
        ),
        scoring_type="keyword",
        expected_keywords=["期权池", "行权", "Cliff", "Vesting", "4年", "RSU"],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="kbiz_07",
        dimension="knowledge_business",
        prompt=(
            "请用产品生命周期理论分析AI语音助手这个品类：\n"
            "1. 导入期、成长期、成熟期、衰退期各有什么特征？\n"
            "2. 你认为AI语音助手目前处于哪个阶段？为什么？\n"
            "3. 处于当前阶段的企业应该采取什么竞争策略？\n"
            "4. 如何判断该品类何时进入下一个阶段？"
        ),
        scoring_type="rubric",
        rubric=[
            ("正确描述四个阶段的特征", 20),
            ("对AI语音助手当前阶段的判断有理有据", 25),
            ("竞争策略与当前阶段匹配", 25),
            ("给出阶段转换的判断指标", 15),
            ("分析有深度，非泛泛而谈", 15),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="kbiz_08",
        dimension="knowledge_business",
        prompt=(
            "请用 AARRR 海盗漏斗模型分析一款AI写作助手产品的用户增长策略：\n"
            "1. Acquisition（获取）：如何获取新用户？\n"
            "2. Activation（激活）：首次使用的关键体验是什么？\n"
            "3. Retention（留存）：如何提高留存率？\n"
            "4. Revenue（变现）：商业化路径是什么？\n"
            "5. Referral（推荐）：如何驱动用户自发传播？\n\n"
            "每个阶段请给出2-3个具体可执行的策略。"
        ),
        scoring_type="rubric",
        rubric=[
            ("Acquisition策略具体可执行（如SEO/内容营销/社交媒体等）", 20),
            ("Activation设计合理（如新手引导/免费试用/模板等）", 20),
            ("Retention策略有针对性（如个性化/习惯培养/社区等）", 20),
            ("Revenue商业化路径清晰（如freemium/订阅/API等）", 20),
            ("Referral有驱动机制（如邀请奖励/分享功能/口碑等）", 20),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="kbiz_09",
        dimension="knowledge_business",
        prompt=(
            "请分析以下三种定价策略的适用场景，并为一款AI翻译工具选择合适的定价策略：\n"
            "1. 成本加成定价(Cost-Plus Pricing)\n"
            "2. 竞争导向定价(Competitive Pricing)\n"
            "3. 价值定价(Value-Based Pricing)\n\n"
            "背景信息：\n"
            "- AI翻译工具的API调用成本约0.02元/千字\n"
            "- 竞品定价：A产品199元/月，B产品99元/月（限量），C产品按量计费0.05元/千字\n"
            "- 目标客户：跨境电商卖家，翻译质量直接影响商品转化率"
        ),
        scoring_type="rubric",
        rubric=[
            ("正确解释三种定价策略的原理", 20),
            ("分析各策略的优缺点", 20),
            ("为AI翻译工具选择了定价策略并说明理由", 20),
            ("考虑了成本、竞品和客户价值三个因素", 20),
            ("给出了具体的定价方案建议（数字/模型）", 20),
        ],
        max_score=100,
        difficulty="hard",
    ),

    TestCase(
        id="kbiz_10",
        dimension="knowledge_business",
        prompt=(
            "请对比以下投资条款书(Term Sheet)中常见的条款，说明其对创始人和投资人各自的影响：\n"
            "1. 优先清算权(Liquidation Preference)：1x non-participating vs 2x participating\n"
            "2. 反稀释条款(Anti-dilution)： Full Ratchet vs Weighted Average\n"
            "3. 董事会席位(Board Seats)：投资人要求1个董事席位\n"
            "4. 回购权(Redemption Right)：5年后投资人有权要求公司回购\n"
            "5. 知情权与否决权(Information Rights & Veto Rights)"
        ),
        scoring_type="rubric",
        rubric=[
            ("优先清算权两种模式解释正确，说明对创始人的不同影响", 25),
            ("反稀释两种方式解释正确（Full Ratchet更激进）", 25),
            ("董事会席位的影响分析合理（控制权/决策效率）", 15),
            ("回购权的风险分析到位（对创始人的资金压力）", 15),
            ("知情权和否决权的平衡分析", 10),
            ("整体立场客观（非偏向某一方）", 10),
        ],
        max_score=100,
        difficulty="hard",
    ),

    TestCase(
        id="kbiz_11",
        dimension="knowledge_business",
        prompt=(
            "请用 TAM/SAM/SOM 框架估算中国AI语音助手的市场规模：\n"
            "1. TAM（Total Addressable Market）：总可寻址市场\n"
            "2. SAM（Serviceable Available Market）：可服务市场\n"
            "3. SOM（Serviceable Obtainable Market）：可获取市场\n\n"
            "要求：\n"
            "- 给出估算的思路和计算过程（可以用假设数据）\n"
            "- 说明从 TAM 到 SAM 到 SOM 是如何逐层缩小的\n"
            "- 给出每一层的估算金额"
        ),
        scoring_type="rubric",
        rubric=[
            ("正确解释TAM/SAM/SOM三个概念", 15),
            ("TAM估算有合理依据（中国消费级AI市场总规模）", 20),
            ("SAM缩小有合理逻辑（聚焦语音助手细分）", 20),
            ("SOM缩小有合理逻辑（基于自身能力和资源）", 20),
            ("给出了具体数字（即使是假设的）", 15),
            ("三层逐级递减逻辑自洽", 10),
        ],
        max_score=100,
        difficulty="hard",
    ),

    TestCase(
        id="kbiz_12",
        dimension="knowledge_business",
        prompt=(
            "请对比以下三种上市路径的优缺点和适用条件：\n"
            "1. 传统IPO（首次公开发行）\n"
            "2. 借壳上市（反向收购）\n"
            "3. SPAC（特殊目的收购公司）\n\n"
            "对于一家估值约50亿元人民币的AI公司，你会推荐哪种路径？为什么？"
        ),
        scoring_type="rubric",
        rubric=[
            ("IPO优缺点分析到位（正规/耗时长/监管严格）", 20),
            ("借壳上市优缺点分析到位（快/壳资源质量/合规风险）", 20),
            ("SPAC优缺点分析到位（速度快/估值灵活/美股为主）", 20),
            ("对AI公司的推荐有明确理由", 20),
            ("考虑了上市地点选择（A股/港股/美股）", 20),
        ],
        max_score=100,
        difficulty="hard",
    ),

    TestCase(
        id="kbiz_13",
        dimension="knowledge_business",
        prompt=(
            "请介绍中国VC（风险投资）生态：\n"
            "1. 列出5家知名VC机构及其主要投资阶段和领域\n"
            "2. 天使轮、Pre-A、A轮、B轮、C轮的典型融资金额范围和估值倍数\n"
            "3. 2024-2025年中国VC市场的主要趋势\n"
            "4. 创业公司如何选择合适的VC？除了钱还应该看什么？"
        ),
        scoring_type="rubric",
        rubric=[
            ("列出≥5家知名VC（如红杉/高瓴/IDG/经纬/源码等）", 20),
            ("各轮次金额范围大致合理", 20),
            ("市场趋势分析与实际情况相符（如投资趋于谨慎/AI赛道热等）", 25),
            ("VC选择建议有实操价值（如看行业资源/投后服务/品牌背书等）", 20),
            ("信息基本准确无严重事实错误", 15),
        ],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="kbiz_14",
        dimension="knowledge_business",
        prompt=(
            "请解释单位经济学(Unit Economics)的核心概念，并用以下数据计算：\n\n"
            "某AI SaaS产品数据：\n"
            "- 月订阅费：199元/用户\n"
            "- 获客成本(CAC)：800元/用户\n"
            "- 月服务成本（含API调用+服务器分摊）：45元/用户\n"
            "- 月流失率(Churn Rate)：4%\n\n"
            "请计算：\n"
            "1. 每用户月净收入(Monthly Contribution Margin)\n"
            "2. 用户平均生命周期(Average Customer Lifetime)\n"
            "3. 客户生命周期价值(LTV)\n"
            "4. LTV/CAC 比值\n"
            "5. CAC 回收期(Payback Period)\n"
            "6. 基于以上数据，这个产品的单位经济模型是否健康？给出判断依据。"
        ),
        scoring_type="keyword",
        expected_keywords=["154", "25", "3850", "4.8", "5.2"],
        max_score=100,
        difficulty="medium",
    ),

    TestCase(
        id="kbiz_15",
        dimension="knowledge_business",
        prompt=(
            "请分析以下商业谈判场景并给出策略建议：\n\n"
            "场景：你是一家AI创业公司的CEO，正在与一家大型制造企业谈合作。\n"
            "对方提出以下条件：\n"
            "1. 要求独家合作权（该行业3年内不能服务竞品）\n"
            "2. 合同金额200万/年，分4个季度付款\n"
            "3. 要求源代码托管（万一你们公司倒闭可以继续用）\n"
            "4. 上线后如果效果没达到承诺的90%准确率，退还50%费用\n\n"
            "请逐条分析每个条件的利弊，给出你的谈判策略和可能的回旋方案。"
        ),
        scoring_type="rubric",
        rubric=[
            ("独家条款分析到位（收窄市场 vs 大单锁定，提出时间/范围限制的回旋方案）", 25),
            ("付款条件分析合理（现金流影响/首付比例/里程碑付款等替代方案）", 20),
            ("源代码托管应对得当（第三方托管/SaaS模式/API对接等替代方案）", 25),
            ("效果对赌应对得当（明确评估标准/数据集/免责场景等）", 20),
            ("整体谈判策略有全局观（非逐条对抗而是组合博弈）", 10),
        ],
        max_score=100,
        difficulty="hard",
    ),
]
