# eVoiceClaw Desktop 使用教程
# eVoiceClaw Desktop User Guide

> 适用版本：eVoiceClaw Desktop v3
> Applies to: eVoiceClaw Desktop v3

---

## 目录 / Table of Contents

1. [快速开始 / Quick Start](#快速开始)
2. [对话示例：工作与事务 / Conversation Examples](#对话示例)
3. [选择模型 / Choosing a Model](#选择模型)
4. [工作区管理 / Workspace Management](#工作区管理)
5. [工具能力 / Built-in Tools](#工具能力)
6. [Skills 扩展 / Skills Extension](#skills-扩展)
7. [隐私保护 / Privacy Protection](#隐私保护)
8. [常见问题 / FAQ](#常见问题)

---

## 快速开始 / Quick Start

打开浏览器访问 eVoiceClaw Desktop，界面分为左侧导航栏和右侧对话区。
Open eVoiceClaw Desktop in your browser. The interface has a left navigation bar and a right conversation area.

**第一步：选择模型 / Step 1: Select a Model**

在对话框顶部的模型选择器中选择一个模型，或保持默认的 `Auto`（系统自动根据任务选择最合适的模型）。
Select a model from the model selector at the top of the chat area, or keep the default `Auto` (the system selects the best model for your task automatically).

**第二步：开始对话 / Step 2: Start Chatting**

在底部输入框输入消息，按回车或点击发送。
Type your message in the input box at the bottom and press Enter or click Send.

---

## 对话示例 / Conversation Examples

### 文档处理 / Document Processing

**读取和分析文件 / Reading and Analyzing Files**

```
帮我读取 /Users/rodney/Documents/合同草稿.pdf，总结主要条款和潜在风险。
```
```
Please read /Users/rodney/Documents/contract_draft.pdf and summarize the key terms and potential risks.
```

**整理征信报告 / Organizing a Credit Report**

```
请读取这份征信报告 /Users/rodney/Downloads/征信报告2026.pdf，
列出所有贷款机构的名称、剩余还款期数、未还金额，以及每家机构的客服电话。
```
```
Please read the credit report at /Users/rodney/Downloads/credit_report.pdf,
list all lending institutions, remaining repayment periods, outstanding amounts, and their customer service numbers.
```

**分析合同 / Contract Analysis**

```
帮我分析 /Users/rodney/Documents/劳动合同.pdf，重点看：
1. 试用期条款
2. 竞业禁止条款
3. 违约金条款
有没有对我不利的地方？
```
```
Analyze /Users/rodney/Documents/employment_contract.pdf, focusing on:
1. Probation period terms
2. Non-compete clauses
3. Penalty clauses
Are there any terms unfavorable to me?
```

---

### 研究与搜索 / Research and Search

**政策申报 / Policy Application**

```
搜索上海科技小巨人企业资质的最新申请条件和截止日期。
```
```
Search for the latest eligibility requirements and deadlines for Shanghai "Technology Little Giant" enterprise qualification.
```

**竞品分析 / Competitor Analysis**

```
帮我搜索国内主流 AI 助手产品（文心一言、豆包、智谱清言）的最新功能更新，
整理成对比表格。
```
```
Search for the latest feature updates of major domestic AI assistants (Wenxin Yiyan, Doubao, Zhipu Qingyan) and organize them into a comparison table.
```

**行业报告 / Industry Research**

```
帮我调研2025年中国消费金融市场规模、主要参与者和监管动态，
提炼成一份500字的摘要。
```
```
Research the 2025 China consumer finance market size, major players, and regulatory developments.
Summarize in 500 words.
```

---

### 代码与技术 / Code and Tech

**代码审查 / Code Review**

```
帮我审查这段 Python 代码，找出潜在的性能问题和安全漏洞：
[粘贴代码]
```
```
Review this Python code for performance issues and security vulnerabilities:
[paste code here]
```

**技术选型 / Tech Stack Decision**

```
我需要为一个日活10万用户的聊天应用选择消息队列方案，
对比 RabbitMQ、Kafka、Redis Pub/Sub 的适用场景和成本。
```
```
I need to choose a message queue for a chat app with 100k DAU.
Compare RabbitMQ, Kafka, and Redis Pub/Sub in terms of use cases and cost.
```

---

### 写作与文案 / Writing and Copywriting

**商业邮件 / Business Email**

```
帮我写一封催款邮件，对方是供应商，逾期未支付货款60天，
语气要专业但不失礼，需要在邮件末尾提到如不回复将采取法律途径。
```
```
Write a payment reminder email to a supplier who is 60 days overdue.
Tone should be professional but firm, and mention legal action if no response.
```

**申请材料 / Application Materials**

```
帮我起草一份科技小巨人申报材料的"技术创新能力"板块，
公司主要做企业级 AI 助手，核心技术是多模型路由和隐私计算，
字数控制在800字以内。
```
```
Draft the "Technical Innovation Capability" section of a Technology Little Giant application.
The company builds enterprise AI assistants. Core technologies: multi-model routing and privacy computing.
Keep it under 800 words.
```

---

### 数据与表格 / Data and Spreadsheets

**整理数据 / Organizing Data**

```
帮我把以下21家金融机构的联系方式整理成表格，包含：机构名称、客服电话、所在城市：
[粘贴列表]
```
```
Organize the following 21 financial institutions' contact information into a table
with columns: Institution Name, Customer Service Number, City:
[paste list]
```

**生成报表 / Generating Reports**

```
根据以下销售数据，帮我生成一份月度销售分析报告，
包含同比增长率、TOP5 产品、和下月预测：
[粘贴数据]
```
```
Based on the following sales data, generate a monthly sales analysis report
including YoY growth rate, TOP 5 products, and next month's forecast:
[paste data]
```

---

## 选择模型 / Choosing a Model

| 场景 / Use Case | 推荐模型 / Recommended Model |
|---|---|
| 日常对话、快速问答 / Casual chat, quick Q&A | Auto 或 DeepSeek Chat |
| 深度推理、复杂分析 / Deep reasoning, complex analysis | DeepSeek R1 |
| 长文档处理 / Long document processing | Kimi 128K |
| 代码生成 / Code generation | DeepSeek Chat / Claude |
| 中文写作 / Chinese writing | 通义千问 / Kimi |

**自然语言切换模型 / Switch Models with Natural Language**

你也可以直接在对话中指定模型：
You can also specify a model directly in your message:

```
让 R1 来分析这份合同的法律风险。
```
```
让 Kimi 来读取这份 200 页的报告。
```
```
@deepseek 帮我写一段 Python 爬虫代码。
```

---

## 工作区管理 / Workspace Management

工作区让 AI 自动感知你的项目上下文，无需每次手动粘贴文件路径。
Workspaces let the AI automatically understand your project context, so you don't need to manually paste file paths each time.

**注册工作区 / Register a Workspace**

1. 点击左侧导航栏的「工作区」/ Click "Workspace" in the left navigation
2. 点击「注册工作区」/ Click "Register Workspace"
3. 输入项目路径（如 `/Users/rodney/Projects/myapp`）/ Enter project path
4. 点击「激活」使其成为当前工作区 / Click "Activate"

**激活后的效果 / After Activation**

```
帮我看一下这个项目的代码结构，有没有明显的架构问题？
```
> AI 会自动读取工作区文件树，无需你指定路径。
> The AI will automatically read the workspace file tree without you specifying paths.

---

## 工具能力 / Built-in Tools

AI 在对话中可以自动调用以下工具完成任务：
The AI can automatically use the following tools during conversation:

| 工具 / Tool | 功能 / Function |
|---|---|
| 网络搜索 | 搜索最新资讯、政策、价格等 |
| Web search | Search for news, policies, prices, etc. |
| 网页抓取 | 获取指定 URL 的页面内容 |
| Web fetch | Fetch content from a specific URL |
| 读取文件 | 读取本地文本、代码文件 |
| Read file | Read local text and code files |
| 读取 PDF | 读取 PDF 文件，含扫描件 OCR 识别 |
| Read PDF | Read PDF files, including scanned OCR |
| 列出目录 | 查看文件夹结构 |
| List directory | View folder structure |
| 写入/编辑文件 | 在工作区内创建或修改文件 |
| Write/edit file | Create or modify files in the workspace |
| 代码审查 | 安全分析代码文件 |
| Code review | Security analysis of code files |
| 数据库查询 | 查询本地 SQLite 数据库 |
| Database query | Query local SQLite databases |

---

## Skills 扩展 / Skills Extension

Skills 是可安装的扩展能力，经过安全审查后，AI 可以执行更复杂的任务。
Skills are installable extensions. After security review, the AI can perform more complex tasks.

**安装 Skill / Installing a Skill**

1. 点击左侧「Skills」导航 / Click "Skills" in the navigation
2. 点击「安装 Skill」/ Click "Install Skill"
3. 粘贴 SKILL.md 内容 / Paste the SKILL.md content
4. 系统自动进行安全审查 / The system performs automatic security review
5. 审查通过后即可使用 / Available after approval

---

## 隐私保护 / Privacy Protection

eVoiceClaw Desktop 内置隐私管道，保护你的个人信息。
eVoiceClaw Desktop has a built-in privacy pipeline to protect your personal information.

**自动脱敏 / Automatic Redaction**

当 AI 读取含有个人信息的本地文件时（如征信报告、合同），以下信息在发送给云端模型前会自动被替换为占位符：
When the AI reads local files containing personal information (e.g., credit reports, contracts), the following are automatically replaced before sending to cloud models:

- 身份证号 / ID card numbers
- 银行卡号 / Bank card numbers
- 姓名 / Names
- 住址 / Addresses

**你看到的始终是原始内容 / You Always See the Original Content**

AI 的回复会自动还原，你在界面上看到的内容不会被替换。
AI responses are automatically restored — what you see in the interface is never replaced.

> 注：机构电话（如 95188、400-xxx）、公开信息不会被脱敏。
> Note: Institution hotlines (e.g., 95188, 400-xxx) and public information are not redacted.

**开启/关闭隐私管道 / Enable/Disable Privacy Pipeline**

在「设置 → 隐私管道」中可以控制是否启用，以及调整敏感度级别（低/中/高）。
Go to "Settings → Privacy Pipeline" to toggle it and adjust the sensitivity level (Low / Medium / High).

---

## 常见问题 / FAQ

**Q：AI 回复很慢怎么办？**
**Q: What if the AI response is slow?**

A：深度推理模型（如 R1）处理复杂任务时本身较慢，属正常现象。若任务不需要深度推理，切换到 DeepSeek Chat 或 Qwen 会更快。
A: Deep reasoning models (e.g., R1) are inherently slower for complex tasks. Switch to DeepSeek Chat or Qwen for faster responses when deep reasoning isn't needed.

---

**Q：读取大 PDF 文件时超时怎么办？**
**Q: What if reading a large PDF times out?**

A：使用 `pages` 参数分段读取，例如：
A: Use the `pages` parameter to read in segments, e.g.:

```
请读取 /path/to/file.pdf，pages 参数设为 1-20
```

---

**Q：如何让 AI 直接使用某个模型？**
**Q: How do I make the AI use a specific model?**

A：在消息中自然语言指定，例如"让 R1 来分析..."、"@kimi 帮我读..."，或在顶部模型选择器中手动选择。
A: Specify it naturally in your message, e.g., "Let R1 analyze...", "@kimi help me read...", or manually select from the model selector at the top.

---

**Q：工作区里的文件会上传到云端吗？**
**Q: Are workspace files uploaded to the cloud?**

A：不会。文件始终在本地读取，AI 工具在本地执行，只有文本内容（经过脱敏处理）会发送给云端模型。
A: No. Files are always read locally. AI tools run locally. Only text content (after redaction) is sent to cloud models.

---

*文档版本：v3.0 | 更新日期：2026-03-13*
*Document Version: v3.0 | Last Updated: 2026-03-13*
