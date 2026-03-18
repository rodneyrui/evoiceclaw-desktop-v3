# eVoiceClaw Desktop v3 — AI Operating System

[中文版](README.zh-CN.md)

> **Every token you spend on a task that doesn't need it is a token wasted. We route each request to the right model — automatically.**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61dafb)](https://react.dev/)

## The Problem: Token Black Hole

AI OS treats LLMs as CPUs — every user interaction, tool call, and reasoning step consumes tokens. But unlike traditional CPUs, **the more capable the model, the more expensive each "clock cycle" becomes**. Running an AI OS entirely on a top-tier model creates a token black hole: costs scale linearly with usage and quickly become unsustainable.

The naive approach — pick one powerful model and send everything to it — is like building a computer with only a high-end CPU and no efficiency cores. It works, but you're paying premium prices for tasks that don't need premium intelligence.

## When Does Collaboration Actually Matter?

Not every task needs multi-model orchestration. Here's when it makes a real difference:

| Scenario | Single Model | Multi-Model Orchestration |
|----------|-------------|--------------------------|
| "What's the weather?" | Works fine (but overpaying if using a premium model) | Routes to free/cheap model — same result, ~0 cost |
| "Summarize this PDF" | Works fine | Routes to mid-tier model — same quality, lower cost |
| "Analyze this legal contract and check compliance" | One model does everything — legal reasoning quality depends on luck | Legal expert model analyzes → compliance model cross-checks → synthesis model writes report |
| "Review my investment plan" | Hallucination risk on financial claims | Strong model drafts → web search verifies claims → correction loop |
| 100 requests/day, mixed complexity | All hit premium model: $$$$ | ~90% hit cheap models, ~10% hit premium: $ |

The key insight: **most daily requests don't need premium intelligence**. Smart routing ensures you only pay for it when you actually need it.

## The Solution: Multi-Model Orchestration

eVoiceClaw Desktop v3 takes a different approach: **combine multiple models to achieve top-tier quality at a fraction of the cost**.

Two layers of orchestration make this possible:

**Layer 1 — Smart Routing (per-request):** Every message is analyzed by a 15-dimensional requirement vector (math reasoning, coding, legal knowledge, cost sensitivity, speed priority, etc.). The system matches this vector against a capability profile for each available model and picks the best fit.

**Layer 2 — Multi-Agent Collaboration:** For complex tasks, multiple specialized Agents collaborate — each powered by the model best suited to its role. The key difference from existing approaches: **Agents decide for themselves when to collaborate and with whom**, rather than following a pre-scripted workflow.

Here's what this looks like in practice — a real test run from our system:

```
User: "Write a research report on AI applications in healthcare"

SmartRouter auto-selects: qwen-plus (main agent)
  │
  ├─→ consult_expert(domain="tech")       → qwen-turbo       (AI tech analysis)
  ├─→ consult_expert(domain="compliance") → deepseek-reasoner (regulatory review)
  └─→ consult_expert(domain="business")   → MiniMax-M2.5     (market outlook)
       │
       │  3 experts on 3 different providers, concurrent API calls
       │  Total expert time: ~62s (parallel), not 162s (sequential)
       │
       ▼
  qwen-long synthesizes all expert opinions → 5,293-char structured report
  write_file outputs final document
```

[![Demo: Multi-Agent Auto Mode](https://asciinema.org/a/yU1FhDxDysLeDASl.svg)](https://asciinema.org/a/yU1FhDxDysLeDASl)

Three different models, three different providers, running concurrently. Each chosen because it scores highest in its domain on our 15-dimensional capability matrix. The main agent didn't need to be told who to consult — it decided based on the task requirements.

See [design discussion](docs/AGENT_COLLABORATION_DESIGN.md) for the full architecture vision.

---

## How Smart Routing Works

```
User message
     │
     ▼
┌─────────────────────────────────────────────────┐
│  ① kNN Semantic Predictor (~30ms)               │
│     2,000+ labeled anchor points                │
│     → 15-dim requirement vector                 │
│     → confidence check                          │
│        ├─ high confidence → use directly         │
│        └─ low confidence ──┐                     │
│                            ▼                     │
│  ② LLM Classifier (~500ms, fallback)            │
│     → 15-dim requirement vector                 │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  ③ Model Matrix Scoring                         │
│     For each available model:                   │
│       score = Σ (requirement[i] × capability[i])│
│     Sort by score → pick best                   │
│     If best fails → auto fallback to next       │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│  ④ Response Verification (when triggered)       │
│     • Weak model on hard task → cross-check     │
│       with a stronger model                     │
│     • High-risk claims (medical/legal/finance)  │
│       → web search verification                 │
│     • Auto-correction loop if issues found      │
└─────────────────────────────────────────────────┘
```

<details>
<summary>The 15 capability dimensions</summary>

| Dimension | What it measures |
|-----------|-----------------|
| `math_reasoning` | Mathematical and quantitative analysis |
| `coding` | Code generation, debugging, architecture |
| `long_context` | Handling large documents and conversations |
| `chinese_writing` | Chinese language quality and nuance |
| `agent_tool_use` | Function calling and tool orchestration |
| `knowledge_tech` | Technical domain knowledge |
| `knowledge_business` | Business and market knowledge |
| `knowledge_legal` | Legal domain knowledge |
| `knowledge_medical` | Medical domain knowledge |
| `logic` | Logical reasoning and deduction |
| `instruction_following` | Precise adherence to complex instructions |
| `reasoning` | General reasoning (derived from logic + instruction + math) |
| `cost_sensitivity` | How much cost matters for this request |
| `speed_priority` | How much latency matters |
| `context_need` | How large a context window is needed |

</details>

The model capability profiles are not static — they are continuously updated by a background evaluation system that benchmarks each model on 165 test cases across 11 dimensions, then hot-reloads the routing matrix without restart.

---

## Why Multi-Model, Not Single-Model Multi-Agent?

Today's AI agents — Claude Code, Cursor, Devin — are powerful single-agent systems: one model + tools. Some frameworks extend this by running multiple agents on the *same* model. But there's a fundamental limitation:

**Single-model multi-agent = multiple copies of the same brain.** They share the same training data, the same biases, the same blind spots. When one copy hallucinates a "fact," the others are likely to agree — because they learned from the same data. This is coherence bias, and it means errors compound rather than cancel out.

Multi-model collaboration provides genuine cognitive diversity:

```
Single-model multi-agent:              Multi-model collaboration:

  Agent A (GPT-4o) ─┐                   Agent A (qwen-plus) ──────┐
  Agent B (GPT-4o) ─┤ same blind spots   Agent B (deepseek-reasoner)┤ different training,
  Agent C (GPT-4o) ─┘ errors compound    Agent C (MiniMax-M2.5) ───┘ errors cancel out
```

When a legal expert (deepseek-reasoner) and a business analyst (MiniMax-M2.5) review the same question from different angles, their disagreements surface real issues. When three copies of the same model review it, they tend to rubber-stamp each other.

This isn't theoretical — in our test runs, we observe that expert models from different providers catch issues that the main agent's model consistently misses.

<details>
<summary>Infrastructure already built</summary>

The foundational pieces for Multi-Agent collaboration are implemented and tested (869 tests passing):

- **ExecutionContext** — Recursion protection with depth limits and token budgets. Prevents infinite Agent-calls-Agent loops. Propagates trace IDs across the call chain for full observability.
- **`consult_expert` tool** — An Agent can explicitly ask another LLM for a second opinion. SmartRouter picks the best expert model for the question domain. Self-consultation avoidance ensures the expert is always a *different* model than the caller.
- **PolicyEngine** — Hard constraints that filter models *before* SmartRouter scoring. Exclude specific providers or models, require tool support, etc. Safety net: if all candidates are filtered out, falls back to the original list.
- **Parallel execution** — Multiple `consult_expert` calls to different providers run concurrently via `asyncio.gather`, reducing wall-clock time from sum-of-all to max-of-all.

</details>

### Community Roadmap

**Phase 1 (current):** SmartRouter (15-dim scoring), ExecutionContext, working `consult_expert` chains with parallel execution, PolicyEngine. Enough to see the concept in action.

**Phase 2:** Preset Expert personas (Legal, Security, Code, Medical, Business, Creative, Math, Research), Web UI visualizing recursive call chains in real-time, token budget monitoring.

**Phase 3:** Policy Tag marketplace, cross-Skill collaboration protocol, performance benchmarks proving that a team of cheap specialists outperforms a single expensive generalist.

**Interested?** Open an issue tagged `multi-agent`, or check the [design discussion](docs/AGENT_COLLABORATION_DESIGN.md). We're especially looking for:
- People building complex AI workflows who hit the limits of single-agent systems
- Researchers interested in emergent collaboration patterns
- Real-world use cases that stress-test multi-model coordination

---

## Beyond Cost: Privacy Pipeline

Cost optimization means nothing if your data leaks. Every message passes through a 5-stage privacy pipeline before reaching any LLM — the LLM never sees your real names, ID numbers, or financial data.

<details>
<summary>How the privacy pipeline works</summary>

```
User input
  → ① Cognitive Isolator    Replace sensitive data with UUID placeholders
                             (ID numbers, bank cards, phone numbers, names, addresses)
  → ② Entity Mapper         Track entities across conversations (LanceDB)
  → ③ Context Compressor    Fit within token budget, preserve logical blocks
  → ④ Memory Injector       Inject relevant memories (3-tier: core facts → vector search → distilled rules)
  → ⑤ Memory Distiller      Extract and store new knowledge for future sessions

LLM response
  → Privacy Restorer        Replace UUID placeholders back to original data
```

Detection uses 4 levels: document-type semantics → regex patterns → AC automaton dictionary → CLUENER RoBERTa NER model (102M params, CPU inference 80-120ms).

</details>

---

## Skill System + Security

A Skill is a natural-language "program" for the AI OS. Install one by pasting a `SKILL.md` file:

```markdown
# WeatherSkill

Query real-time weather for any city.

## Actions
- HTTP GET to https://api.open-meteo.com/v1/forecast
- Parse temperature, wind speed, and precipitation
```

<details>
<summary>Security architecture</summary>

The Gatekeeper LLM reviews the Skill, rewrites it to declare only safe actions (`ACTIONS.yaml`), and enforces those constraints at runtime. Combined with a 3-layer Shell sandbox (whitelist → Skill declaration verification → asyncio subprocess + ulimit) and NetworkGuard (per-workspace domain allowlist + private IP blocking), the system maintains security without sacrificing capability.

</details>

---

## The AI OS Analogy

The design philosophy maps traditional OS concepts to AI:

| Traditional OS | AI OS | Implementation |
|----------------|-------|----------------|
| CPU | LLM | Multi-model routing + fallback |
| Efficiency cores | Cheap models for simple tasks | SmartRouter 15-dim scoring |
| ISA | Function Calling (27+ tools) | OpenAI tool_use protocol |
| Application | Skill (SKILL.md) | Natural-language program |
| App Store review | Gatekeeper LLM | Rewrites Skill on install |
| Shell | Sandboxed executor | 3-layer: whitelist → declaration → subprocess |
| Process scheduler | SmartRouter | Intent → model selection |
| Inter-process communication | Agent Collaboration (planned) | Agents call each other as needed |
| Memory management | Privacy Pipeline | 5-stage data flow with UUID isolation |
| Firewall | NetworkGuard | Domain allowlist + private IP block |
| Audit log | Audit Pipeline | Full-chain trace_id traceability |

---

## Quick Start

### Option 1: Docker (recommended)

```bash
git clone https://github.com/your-org/evoiceclaw-desktop-v3.git
cd evoiceclaw-desktop-v3

cp backend/config.example.us.yaml backend/config.yaml   # or .cn / .local
cp backend/secrets.yaml.example backend/secrets.yaml
# Edit secrets.yaml and add your API keys

docker compose up -d
open http://localhost:28772
```

### Option 2: Local Development

**Prerequisites:** Python 3.12+, Node.js 20+

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.us.yaml config.yaml
cp secrets.yaml.example secrets.yaml
# Edit secrets.yaml with your API keys
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies API to :8000)
```

---

## Configuration

| File | Purpose | Git-tracked? |
|------|---------|-------------|
| `backend/config.yaml` | Non-sensitive settings (models, pipeline, shell, network) | ❌ No |
| `backend/secrets.yaml` | API keys and tokens | ❌ No |
| `backend/config.example.cn.yaml` | Template — China region (DeepSeek, Qwen, Zhipu, Kimi, MiniMax) | ✅ Yes |
| `backend/config.example.us.yaml` | Template — Global region (OpenAI, Anthropic, Google) | ✅ Yes |
| `backend/config.example.local.yaml` | Template — Local models (Ollama) | ✅ Yes |

---

## Supported Providers

Out of the box via [LiteLLM](https://github.com/BerriAI/litellm) — any OpenAI-compatible API works:

| Provider | Example Models | Typical Role in Routing |
|----------|---------------|------------------------|
| DeepSeek | deepseek-chat, deepseek-reasoner | Daily workhorse + deep reasoning |
| Qwen (Alibaba) | qwen-max, qwen-plus, qwen-turbo | Chinese writing, general tasks |
| Zhipu | glm-4-flash, glm-4 | Free-tier flash model for simple tasks |
| Kimi (Moonshot) | moonshot-v1-128k | Long-context document analysis |
| MiniMax | MiniMax-Text-01 | Cost-effective general tasks |
| OpenAI | gpt-4o, gpt-4o-mini, o3-mini | Coding, instruction following |
| Anthropic | claude-opus-4, claude-sonnet-4 | Complex reasoning, safety |
| Google | gemini-2.0-flash, gemini-2.5-pro | Multimodal, free-tier flash |
| Ollama | any local model | Fully offline, zero cost |

The more providers you configure, the more options SmartRouter has to optimize cost and quality. Even a single provider works — routing simply picks the best model within that provider.

---

## Running Tests

```bash
cd backend
python3 -m pytest tests/ -v
```

869+ backend tests + 90 frontend tests, all passing.

---

## Project Structure

```
desktop-v3/
├── backend/
│   ├── app/
│   │   ├── api/v1/        # FastAPI route handlers
│   │   ├── core/          # Config loader (config.yaml + secrets.yaml)
│   │   ├── domain/        # Domain models (Session, Message, Workspace)
│   │   ├── evaluation/    # Model evaluation + rule generation (Phase 7)
│   │   ├── infrastructure/# SQLite + LanceDB
│   │   ├── kernel/        # LLM kernel: SmartRouter, LLMRouter, kNN predictor, 27+ tools
│   │   ├── pipeline/      # Privacy pipeline (5 stages)
│   │   ├── security/      # Shell sandbox, NetworkGuard, Gatekeeper, audit, rate limiter
│   │   └── services/      # ChatService, SkillService, VerificationService
│   ├── data/
│   │   ├── preset/        # Evaluation data, common-sense rules, intent anchors
│   │   └── skills/        # Installed Skills (SKILL.md + ACTIONS.yaml)
│   ├── tests/             # 830+ test cases
│   ├── requirements.txt   # Pinned dependencies
│   └── requirements.in    # Version range constraints (for upgrades)
├── frontend/              # React 19 + Vite + TypeScript + Tailwind
├── deploy/                # Deployment scripts (remote Mac, Docker, systemd)
├── docs/                  # Architecture, design docs, user guide
└── discussions/           # Design decision records
```

---

## Roadmap

- **Multi-Agent Collaboration (Phase 2)** — Preset Expert personas, Web UI for real-time call chain visualization, token budget monitoring. Foundation (ExecutionContext, consult_expert, PolicyEngine, parallel execution) is already built and tested. ([Design discussion](docs/AGENT_COLLABORATION_DESIGN.md))
- **Cerebellum model** — Local semantic routing model (<50M params, <100ms) to replace kNN + LLM classifier, enabling fully offline intent prediction
- **Cross-platform** — Native clients for iOS, HarmonyOS, Android
- **Community evaluation** — Open benchmark contribution pipeline for community-driven model scoring

---

## License

[Apache License 2.0](LICENSE) — Copyright 2026 eVoiceClaw
