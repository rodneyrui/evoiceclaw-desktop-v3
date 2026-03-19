# Multi-Agent Collaboration Design

> Architecture vision for eVoiceClaw Desktop v3's multi-agent collaboration system.

---

## From Pre-Orchestrated Workflows to Autonomous Collaboration

Traditional multi-agent frameworks follow a "planner assigns tasks to workers" pattern: a planning model analyzes the task upfront, produces a fixed execution plan, and workers execute steps sequentially. This works for structured, predictable workflows but breaks down for open-ended tasks where the best path isn't known in advance.

eVoiceClaw Desktop v3 takes a different approach: **agents decide for themselves when to collaborate and with whom**. There is no pre-scripted workflow. An agent working on a coding task that encounters a legal question can autonomously consult a legal expert — and that expert can, in turn, consult a technical specialist if needed.

### Why This Matters

| Dimension | Pre-Orchestrated Workflow | Autonomous Collaboration |
|-----------|--------------------------|--------------------------|
| Planning | Before execution (fixed plan) | During execution (dynamic decisions) |
| Flexibility | Low — steps are fixed | High — agents adjust in real-time |
| Tool usage | Pre-declared per step | Dynamically chosen |
| Collaboration | None — each step runs in isolation | On-demand — agents call each other as needed |
| Cost control | Good — cheapest model per step | Optimal — each agent uses its best-fit model |
| Best for | Structured, repeatable processes | Complex, open-ended tasks |

---

## Core Concept: Model = Agent

Every configured model is naturally an agent. The evaluation system benchmarks each model across 15 capability dimensions — this profile *is* the agent's resume. No manual role definitions needed.

When an agent needs help, it calls `consult_expert` — a built-in tool that triggers another round of SmartRouter scoring. The router picks the best model for the requested domain, ensuring the expert is always a *different* model than the caller (self-consultation avoidance).

```
User: "Review this code for GPL compliance"

Main agent (selected by SmartRouter for coding + legal mix)
  │
  ├─ Writes initial analysis
  ├─ Realizes it needs deeper legal expertise
  │
  └─→ consult_expert(domain="legal", question="Does this violate GPL?")
       │
       SmartRouter scores all models on legal dimension
       → Selects the strongest legal reasoning model
       │
       Expert reviews and responds
       │
  Main agent integrates expert opinion into final answer
```

The key insight: **agents don't need to be pre-defined roles**. Any model becomes a specialist when SmartRouter routes a domain-specific question to it based on its capability profile.

---

## The OS Scheduling Analogy

In a traditional OS, applications don't bind to specific CPU cores. They run their logic, and the scheduler assigns resources dynamically based on load, priority, and affinity.

```
Traditional OS:
Application ←→ Scheduler ←→ CPU Core
    ↓              ↓            ↓
  Logic      Load balancing   Compute

AI OS:
Skill ←→ SmartRouter ←→ LLM
  ↓           ↓           ↓
ACTIONS    15-dim scoring  Reasoning
```

A Skill never declares "I need GPT-4" — it exposes capability interfaces. The router decides which model satisfies those requirements *at call time*, based on the latest evaluation data. The same Skill routes to different models depending on the complexity of each specific request.

---

## Three Mechanisms for Collaboration

### 1. Recursion Protection (ExecutionContext)

Every tool execution carries an `ExecutionContext` that tracks:
- **Call depth** — hard limit prevents infinite agent-calls-agent loops
- **Token budget** — remaining budget decreases with each recursive call
- **Call stack** — full trace for observability and debugging
- **Policy tags** — accumulated constraints that propagate through the chain

When an agent calls `consult_expert`, a child context is forked with reduced budget and incremented depth. If depth exceeds the limit or budget runs out, the call is rejected gracefully.

### 2. Expert Consultation (consult_expert tool)

A built-in tool that any agent can call to get a second opinion from a specialist model:

- The caller specifies a domain (e.g., "legal", "security", "medical") and a question
- SmartRouter selects the best model for that domain from the current capability matrix
- Self-consultation avoidance ensures cognitive diversity — the expert is always a different model
- Multiple expert calls to different providers run concurrently via `asyncio.gather`

### 3. Policy Engine (Hard Constraints)

Policy tags are declarative constraints that filter models *before* SmartRouter scoring:

- `legal_review` → only models scoring above threshold on legal dimensions
- `medical_diagnosis` → requires human-in-the-loop confirmation
- `code_critical` → minimum capability threshold on coding dimension

Tags are declarative ("I need legal-grade safety"), not imperative ("use model X"). The router interprets them against the latest evaluation data — which model satisfies "legal-grade" may change as models improve or pricing shifts.

---

## Why Multi-Model, Not Single-Model Multi-Agent?

Running multiple agents on the *same* model creates copies of the same brain — same training data, same biases, same blind spots. When one copy hallucinates, the others tend to agree (coherence bias).

Multi-model collaboration provides genuine cognitive diversity. Models from different providers, trained on different data with different architectures, catch each other's mistakes. Their disagreements surface real issues rather than rubber-stamping errors.

In practice, we observe that expert models from different providers consistently catch issues that the main agent's model misses — precisely because they have different knowledge distributions and reasoning patterns.

---

## Evolution Roadmap

### Phase 1 (Current)
- Single agent + SmartRouter 15-dimensional routing
- 27+ built-in tools with autonomous tool selection
- Verified: order-of-magnitude cost reduction vs. single premium model

### Phase 2 (In Progress)
- `consult_expert` tool enabling explicit cross-model consultation
- ExecutionContext for recursion protection and budget tracking
- PolicyEngine for hard constraints on model selection
- Parallel expert execution for concurrent multi-provider calls
- 8 preset expert personas (Legal, Security, Code, Medical, Business, Creative, Math, Research)

### Phase 3 (Planned)
- Deep reasoning model as "team lead" — provides strategic advice rather than fixed plans
- Collaboration pattern caching — common paths reused automatically
- Confidence calibration — external calibration of weak models' self-assessment
- Real-time collaboration cost monitoring and budget controls

### Phase 4 (Vision)
- Self-organizing agent networks — agents dynamically create specialized sub-agents
- Cross-workspace agent collaboration via event bridging
- Self-optimizing collaboration patterns — the system learns which collaboration paths work best

---

## Key Principles

1. **No pre-orchestration** — agents decide collaboration dynamically, not from a fixed plan
2. **Model = Agent** — every configured model is naturally an agent; evaluation data is its resume
3. **Collaboration as a tool** — `consult_expert` is a standard tool; the LLM decides when to use it
4. **Declarative constraints** — Policy tags say "what safety level" not "which model"
5. **Pure scheduling** — SmartRouter makes a fresh decision at every LLM call, using the latest evaluation data
6. **Cost compounds** — each agent uses the cheapest model that fits its specialty; savings multiply in collaboration
7. **Controlled emergence** — emergent collaboration happens inside a bounded sandbox with hard limits, full audit trails, and circuit breakers; uncontrolled emergence is a bug, controlled emergence is a feature

---

## Controllability: From Observable to Transactional

The system's multi-agent collaboration is "constrained emergence" — agents autonomously decide collaboration strategies, but within hard boundaries enforced by code.

### Layer 1: Decision Audit Trail (Implemented)

Every routing decision is recorded as a structured audit event:

- `PREDICTION_DECISION` — which predictor (kNN vs LLM), confidence score, 15-dim requirement vector
- `ROUTING_DECISION` — all candidate model scores, final selection, requirement vector
- `EXPERT_ROUTING_DECISION` — domain, parent model, routed expert, self-avoidance trigger, recursion depth, remaining budget

This enables post-hoc analysis: "why was this model chosen for this request?"

### Layer 2: Declarative Collaboration Policy (Planned)

Extract natural-language constraints from system prompts into enforceable configuration:

```yaml
collaboration_policy:
  max_rounds: 2
  max_experts_per_round: 4
  dedup: true
  synthesis_threshold: 3000
  fallback_on_timeout: self
  circuit_breaker:
    provider_failure_threshold: 2
    degrade_to: single_agent
```

Code enforces these constraints at the ToolExecutor layer. System prompts remain as soft guidance.

### Layer 3: Collaboration Transactions (Research)

Compensating transactions for multi-expert collaboration:
- Context snapshots before each expert input
- Arbitration rounds when contradictions are detected (stronger model adjudicates)
- Confidence and disagreement annotations on final output

This extends the existing VerificationService from "verify final output" to "verify intermediate collaboration process."
