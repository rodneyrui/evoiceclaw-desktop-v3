# eVoiceClaw Desktop v3 — AI 操作系统

[English](README.md)

> **每一个花在不需要它的任务上的 token，都是浪费。我们自动将每个请求路由到最合适的模型。**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61dafb)](https://react.dev/)

## 问题：Token 黑洞

AI OS 把大语言模型当作 CPU——每次用户交互、工具调用、推理步骤都消耗 token。但与传统 CPU 不同，**模型越强，每个"时钟周期"越贵**。用顶级模型跑所有请求，就会形成 token 黑洞：成本随用量线性增长，很快不可持续。

简单粗暴的方案——选一个强模型，什么都扔给它——就像造一台只有高性能核心、没有能效核心的电脑。能用，但你在为不需要高端智能的任务支付高端价格。

## 什么时候协作才真正有意义？

不是每个任务都需要多模型编排。以下是它真正产生差异的场景：

| 场景 | 单模型 | 多模型编排 |
|------|--------|-----------|
| "今天天气怎么样？" | 能回答（但用顶级模型就是浪费钱） | 路由到免费/低价模型——同样结果，约 0 成本 |
| "总结这份 PDF" | 能做 | 路由到中端模型——同等质量，更低成本 |
| "分析这份法律合同并检查合规性" | 一个模型包揽——法律推理质量看运气 | 法律专家模型分析 → 合规模型交叉检查 → 综合模型撰写报告 |
| "审查我的投资计划" | 金融声称有幻觉风险 | 强模型起草 → 联网搜索验证声称 → 纠正循环 |
| 每天 100 个请求，复杂度混合 | 全部命中顶级模型：$$$$ | ~90% 命中低价模型，~10% 命中顶级：$ |

核心洞察：**大多数日常请求不需要顶级智能**。智能路由确保你只在真正需要时才为它付费。

## 解决方案：多模型编排

eVoiceClaw Desktop v3 采用不同的思路：**组合多个模型，以极低成本达到顶级质量**。

两层编排机制使之成为可能：

**第一层——智能路由（逐请求）：** 每条消息被分析为 15 维需求向量（数学推理、编程、法律知识、成本敏感度、速度优先级等）。系统将该向量与每个可用模型的能力画像匹配，选出最佳模型。

**第二层——多 Agent 协作：** 对于复杂任务，多个专业 Agent 协同工作——每个由最适合其角色的模型驱动。与现有方案的关键区别：**Agent 自主决定何时协作、与谁协作**，而非遵循预编排的工作流。

以下是实际测试运行的真实记录：

```
用户："帮我写一份关于AI在医疗领域应用的研究报告"

SmartRouter 自动选择：qwen-plus（主 Agent）
  │
  ├─→ consult_expert(domain="tech")      → qwen-turbo      （AI 技术分析）
  ├─→ consult_expert(domain="compliance") → deepseek-reasoner（合规审查）
  └─→ consult_expert(domain="business")  → MiniMax-M2.5    （商业前景）
       │
       │  3 个专家来自 3 个不同供应商，并发 API 调用
       │  专家总耗时：~62s（并行），而非 162s（串行）
       │
       ▼
  qwen-long 综合所有专家意见 → 5,293 字结构化报告
  write_file 输出最终文档
```

[![演示：多 Agent 自动模式](https://asciinema.org/a/yU1FhDxDysLeDASl.svg)](https://asciinema.org/a/yU1FhDxDysLeDASl)

三个不同模型，三个不同供应商，并发执行。每个模型被选中是因为它在我们 15 维能力矩阵中该领域得分最高。主 Agent 不需要被告知该咨询谁——它根据任务需求自主决定。

详见[设计讨论](docs/AGENT_COLLABORATION_DESIGN.md)。

---

## 智能路由工作原理

```
用户消息
     │
     ▼
┌─────────────────────────────────────────────────┐
│  ① kNN 语义预测器（~30ms）                       │
│     2,000+ 标注锚点                              │
│     → 15 维需求向量                              │
│     → 置信度检查                                 │
│        ├─ 高置信度 → 直接使用                     │
│        └─ 低置信度 ──┐                           │
│                      ▼                           │
│  ② LLM 分类器（~500ms，降级方案）                 │
│     → 15 维需求向量                              │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  ③ 模型矩阵评分                                  │
│     对每个可用模型：                               │
│       得分 = Σ (需求[i] × 能力[i])                │
│     按得分排序 → 选最优                           │
│     最优失败 → 自动降级到下一个                    │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  ④ 回复验证（按需触发）                           │
│     • 弱模型处理难题 → 强模型交叉验证              │
│     • 高风险声称（医疗/法律/金融）                 │
│       → 联网搜索验证                              │
│     • 发现问题 → 自动纠正循环                     │
└─────────────────────────────────────────────────┘
```

<details>
<summary>15 个能力维度</summary>

| 维度 | 衡量内容 |
|------|---------|
| `math_reasoning` | 数学与定量分析 |
| `coding` | 代码生成、调试、架构设计 |
| `long_context` | 长文档和长对话处理 |
| `chinese_writing` | 中文语言质量与表达 |
| `agent_tool_use` | 函数调用与工具编排 |
| `knowledge_tech` | 技术领域知识 |
| `knowledge_business` | 商业与市场知识 |
| `knowledge_legal` | 法律领域知识 |
| `knowledge_medical` | 医学领域知识 |
| `logic` | 逻辑推理与演绎 |
| `instruction_following` | 对复杂指令的精确遵循 |
| `reasoning` | 综合推理（由 logic + instruction + math 派生） |
| `cost_sensitivity` | 该请求对成本的敏感度 |
| `speed_priority` | 该请求对延迟的敏感度 |
| `context_need` | 需要多大的上下文窗口 |

</details>

模型能力画像不是静态的——后台评估系统持续对每个模型进行 74 个测试用例、12 个维度的基准测试，然后热加载路由矩阵，无需重启。

---

## 为什么是多模型，而非单模型多 Agent？

当前的 AI Agent——Claude Code、Cursor、Devin——都是强大的单 Agent 系统：一个模型 + 工具。一些框架通过在*同一个*模型上运行多个 Agent 来扩展。但这有一个根本性的局限：

**单模型多 Agent = 同一个大脑的多个副本。** 它们共享相同的训练数据、相同的偏见、相同的盲区。当一个副本产生幻觉时，其他副本很可能会同意——因为它们从相同的数据中学习。这就是一致性偏差，意味着错误会累积而非相互抵消。

多模型协作提供真正的认知多样性：

```
单模型多 Agent：                        多模型协作：

  Agent A (GPT-4o) ─┐                   Agent A (qwen-plus) ──────┐
  Agent B (GPT-4o) ─┤ 相同盲区           Agent B (deepseek-reasoner)┤ 不同训练数据，
  Agent C (GPT-4o) ─┘ 错误累积           Agent C (MiniMax-M2.5) ───┘ 错误相互抵消
```

当法律专家（deepseek-reasoner）和商业分析师（MiniMax-M2.5）从不同角度审视同一个问题时，它们的分歧会暴露真实问题。当同一模型的三个副本审视时，它们倾向于互相背书。

这不是理论——在我们的测试中，来自不同供应商的专家模型确实能捕捉到主 Agent 模型持续遗漏的问题。

<details>
<summary>已构建的基础设施</summary>

多 Agent 协作的基础组件已实现并通过测试（869 个测试全部通过）：

- **ExecutionContext** — 递归保护，带深度限制和 token 预算。防止 Agent 无限互调。跨调用链传播 trace_id 实现全链路可观测。
- **`consult_expert` 工具** — Agent 可以显式请求另一个 LLM 提供第二意见。SmartRouter 为问题领域选择最佳专家模型。自咨询回避机制确保专家始终是与调用者*不同*的模型。
- **PolicyEngine** — 在 SmartRouter 评分*之前*过滤模型的硬约束。排除特定供应商或模型、要求工具支持等。安全网：如果所有候选被过滤，回退到原始列表。
- **并行执行** — 多个 `consult_expert` 调用到不同供应商时通过 `asyncio.gather` 并发执行，将总耗时从所有之和降低到最大值。

</details>

### 社区路线图

**Phase 1（当前）：** SmartRouter（15 维评分）、ExecutionContext、可工作的 `consult_expert` 并行调用链、PolicyEngine。足以验证概念。

**Phase 2：** 预设专家人格（法律、安全、编程、医学、商业、创意、数学、研究），Web UI 实时可视化递归调用链，token 预算监控。

**Phase 3：** 策略标签市场、跨 Skill 协作协议、性能基准测试证明廉价专家团队优于单个昂贵通才。

**感兴趣？** 提交标记为 `multi-agent` 的 issue，或查看[设计讨论](docs/AGENT_COLLABORATION_DESIGN.md)。我们特别期待：
- 构建复杂 AI 工作流并触及单 Agent 系统极限的开发者
- 对涌现协作模式感兴趣的研究者
- 能压力测试多模型协调的真实场景

---

## 不止成本：隐私管线

成本优化在数据泄露面前毫无意义。每条消息在到达任何 LLM 之前都经过 5 阶段隐私管线——LLM 永远看不到你的真实姓名、身份证号或财务数据。

<details>
<summary>隐私管线工作原理</summary>

```
用户输入
  → ① 认知隔离器    用 UUID 占位符替换敏感数据
                     （身份证号、银行卡、手机号、姓名、地址）
  → ② 实体映射器    跨对话追踪实体（LanceDB）
  → ③ 上下文压缩器  在 token 预算内压缩，保留逻辑块
  → ④ 记忆注入器    注入相关记忆（三级：核心事实 → 向量检索 → 蒸馏规则）
  → ⑤ 记忆蒸馏器    提取并存储新知识供未来会话使用

LLM 回复
  → 隐私恢复器      将 UUID 占位符还原为原始数据
```

检测使用 4 级机制：文档类型语义 → 正则表达式 → AC 自动机词典 → CLUENER RoBERTa NER 模型（102M 参数，CPU 推理 80-120ms）。

</details>

---

## Skill 系统 + 安全

Skill 是 AI OS 的自然语言"程序"。通过粘贴 `SKILL.md` 文件即可安装：

```markdown
# WeatherSkill

查询任意城市的实时天气。

## Actions
- HTTP GET to https://api.open-meteo.com/v1/forecast
- 解析温度、风速和降水量
```

<details>
<summary>安全架构</summary>

守门员 LLM 审查 Skill，将其重写为仅声明安全动作（`ACTIONS.yaml`），并在运行时强制执行这些约束。配合 3 层 Shell 沙箱（白名单 → Skill 声明验证 → asyncio subprocess + ulimit）和 NetworkGuard（按工作区的域名白名单 + 内网 IP 屏蔽），系统在不牺牲能力的前提下保障安全。

</details>

---

## AI OS 类比

设计哲学将传统操作系统概念映射到 AI：

| 传统 OS | AI OS | 实现方式 |
|---------|-------|---------|
| CPU | LLM | 多模型路由 + 降级 |
| 能效核心 | 低价模型处理简单任务 | SmartRouter 15 维评分 |
| 指令集架构 | 函数调用（27+ 工具） | OpenAI tool_use 协议 |
| 应用程序 | Skill（SKILL.md） | 自然语言程序 |
| 应用商店审核 | 守门员 LLM | 安装时重写 Skill |
| Shell | 沙箱执行器 | 3 层：白名单 → 声明 → subprocess |
| 进程调度器 | SmartRouter | 意图 → 模型选择 |
| 进程间通信 | Agent 协作 | Agent 按需互相调用 |
| 内存管理 | 隐私管线 | 5 阶段数据流 + UUID 隔离 |
| 防火墙 | NetworkGuard | 域名白名单 + 内网 IP 屏蔽 |
| 审计日志 | 审计管线 | 全链路 trace_id 可追溯 |

---

## 快速开始

### 方式一：Docker（推荐）

```bash
git clone https://github.com/your-org/evoiceclaw-desktop-v3.git
cd evoiceclaw-desktop-v3

cp backend/config.example.us.yaml backend/config.yaml   # 或 .cn / .local
cp backend/secrets.yaml.example backend/secrets.yaml
# 编辑 secrets.yaml 填入你的 API Key

docker compose up -d
open http://localhost:28772
```

### 方式二：本地开发

**前置条件：** Python 3.12+, Node.js 20+

```bash
# 后端
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.us.yaml config.yaml
cp secrets.yaml.example secrets.yaml
# 编辑 secrets.yaml 填入你的 API Key
uvicorn app.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev          # http://localhost:5173（API 代理到 :8000）
```

---

## 配置

| 文件 | 用途 | 是否入 Git？ |
|------|------|-------------|
| `backend/config.yaml` | 非敏感配置（模型、管线、Shell、网络） | ❌ 否 |
| `backend/secrets.yaml` | API Key 和 Token | ❌ 否 |
| `backend/config.example.cn.yaml` | 模板——中国区（DeepSeek、Qwen、智谱、Kimi、MiniMax） | ✅ 是 |
| `backend/config.example.us.yaml` | 模板——国际区（OpenAI、Anthropic、Google） | ✅ 是 |
| `backend/config.example.local.yaml` | 模板——本地模型（Ollama） | ✅ 是 |

---

## 支持的供应商

通过 [LiteLLM](https://github.com/BerriAI/litellm) 开箱即用——任何 OpenAI 兼容 API 均可接入：

| 供应商 | 示例模型 | 路由中的典型角色 |
|--------|---------|----------------|
| DeepSeek | deepseek-chat, deepseek-reasoner | 日常主力 + 深度推理 |
| 通义千问（阿里） | qwen-max, qwen-plus, qwen-turbo | 中文写作、通用任务 |
| 智谱 | glm-4-flash, glm-4 | 免费层闪电模型，处理简单任务 |
| Kimi（月之暗面） | moonshot-v1-128k | 长上下文文档分析 |
| MiniMax | MiniMax-Text-01 | 高性价比通用任务 |
| OpenAI | gpt-4o, gpt-4o-mini, o3-mini | 编程、指令遵循 |
| Anthropic | claude-opus-4, claude-sonnet-4 | 复杂推理、安全性 |
| Google | gemini-2.0-flash, gemini-2.5-pro | 多模态、免费层闪电 |
| Ollama | 任意本地模型 | 完全离线，零成本 |

配置的供应商越多，SmartRouter 优化成本和质量的选择空间越大。即使只配置一个供应商也能工作——路由会在该供应商内选择最佳模型。

---

## 运行测试

```bash
cd backend
python3 -m pytest tests/ -v
```

869+ 后端测试 + 90 前端测试，全部通过。

---

## 项目结构

```
desktop-v3/
├── backend/
│   ├── app/
│   │   ├── api/v1/        # FastAPI 路由处理器
│   │   ├── core/          # 配置加载器（config.yaml + secrets.yaml）
│   │   ├── domain/        # 领域模型（Session, Message, Workspace）
│   │   ├── evaluation/    # 模型评估 + 规则生成
│   │   ├── infrastructure/# SQLite + LanceDB
│   │   ├── kernel/        # LLM 内核：SmartRouter、LLMRouter、kNN 预测器、27+ 工具
│   │   ├── pipeline/      # 隐私管线（5 阶段）
│   │   ├── security/      # Shell 沙箱、NetworkGuard、守门员、审计、限流
│   │   └── services/      # ChatService、SkillService、VerificationService
│   ├── data/
│   │   ├── preset/        # 评估数据、常识规则、意图锚点
│   │   └── skills/        # 已安装的 Skill（SKILL.md + ACTIONS.yaml）
│   ├── tests/             # 830+ 测试用例
│   ├── requirements.txt   # 锁定依赖
│   └── requirements.in    # 版本范围约束（用于升级）
├── frontend/              # React 19 + Vite + TypeScript + Tailwind
├── deploy/                # 部署脚本（远程 Mac、Docker、systemd）
├── docs/                  # 架构文档、设计文档、用户指南
└── discussions/           # 设计决策记录
```

---

## 路线图

- **多 Agent 协作（Phase 2）** — 预设专家人格，Web UI 实时可视化调用链，token 预算监控。基础设施（ExecutionContext、consult_expert、PolicyEngine、并行执行）已构建并通过测试。（[设计讨论](docs/AGENT_COLLABORATION_DESIGN.md)）
- **小脑模型** — 本地语义路由模型（<50M 参数，<100ms）替代 kNN + LLM 分类器，实现完全离线意图预测
- **跨平台** — iOS、鸿蒙、安卓原生客户端
- **社区评估** — 开放基准测试贡献管线，社区驱动的模型评分

---

## 许可证

[Apache License 2.0](LICENSE) — Copyright 2026 eVoiceClaw
