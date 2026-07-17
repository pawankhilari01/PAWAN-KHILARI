# 04 — Agent Interaction Sequences

> **Scope:** Concrete runtime interactions between the Supervisor, Workflow Planner, Phase
> Agents, Worker Agents, and cross-cutting services. Every diagram is a buildable contract
> using the canonical stack (A2A JSON-RPC, Temporal signals, Kafka CloudEvents, MCP).
>
> **Related docs:** [01 — Architecture](./01-architecture.md) ·
> [05 — Memory](./05-memory-architecture.md) · [06 — RAG](./06-rag-architecture.md) ·
> [07 — MCP](./07-mcp-architecture.md) · [08 — Tools](./08-tool-architecture.md)

**Conventions used below**
- `A2A` = JSON-RPC 2.0 over HTTP to an agent's `:90xx` endpoint (`message/send`, `tasks/get`).
- `CE` = CloudEvents 1.0 published to Kafka (e.g. `edt.discover.persona.created`).
- `signal` = Temporal workflow signal; `activity` = Temporal activity invocation.
- Every LLM call is traced via OTel + Langfuse; every artifact carries `confidence` +
  `provenance` + `approvals[]`.

---

## (a) End-to-End Run Kickoff: Supervisor + Workflow Planner

```mermaid
sequenceDiagram
    autonumber
    actor User as Enterprise User
    participant API as FastAPI Gateway :8080
    participant SUP as Supervisor Agent :9000
    participant TMP as Temporal :7233
    participant WP as Workflow Planner :9001
    participant MEM as MemoryAgent :9100
    participant COST as Cost/Token Optimizer :9104
    participant BUS as Kafka (CloudEvents)

    User->>API: POST /runs {brief, org_id, budget_cap, constraints}
    API->>API: OIDC authZ (Keycloak) + input guardrails (Presidio PII)
    API->>SUP: A2A message/send (RunRequest)
    SUP->>TMP: startWorkflow(DesignThinkingRun, run_id)
    TMP-->>SUP: workflow handle
    SUP->>BUS: CE edt.run.created
    SUP->>MEM: retrieve(scope=org, "prior similar runs / playbooks")
    MEM-->>SUP: procedural playbooks + semantic priors (cited)
    SUP->>WP: A2A plan_run(brief, priors, budget_cap)
    WP->>COST: propose model-tier routing per task
    COST-->>WP: routing table (Opus/Sonnet/Haiku per task) + budget split
    WP-->>SUP: RunPlan {phase DAG, worker assignments, budgets, gates}
    SUP->>TMP: persist RunPlan as workflow state
    SUP->>BUS: CE edt.run.planned
    SUP-->>API: 202 Accepted {run_id, status: PLANNED}
    API-->>User: run_id + live status URL
    Note over SUP,TMP: Supervisor now drives phases as Temporal child workflows (Discover→…→Validate)
```

**Explanation.** The Supervisor is the Temporal workflow's decision brain, not a request
handler — it survives restarts. Before planning it pulls **procedural + semantic memory**
([05](./05-memory-architecture.md)) so the planner reuses prior playbooks. The **Cost/Token
Optimizer** assigns model tiers up front (Haiku for extraction, Sonnet default, Opus for
critique) and splits the budget cap per phase. The `RunPlan` is durably stored as workflow
state; the run then proceeds phase by phase.

---

## (b) Discover-Phase Worker Fan-Out + Research Synthesizer Aggregation

```mermaid
sequenceDiagram
    autonumber
    participant SUP as Supervisor
    participant DPA as DiscoverPhaseAgent (LangGraph)
    participant PD as ProblemDiscoveryAgent
    participant MR as MarketResearchAgent
    participant PAT as PatentResearchAgent
    participant CI as CompetitiveIntelAgent
    participant TSA as Tool Selection Agent :9101
    participant MCP as MCP Gateway
    participant RS as ResearchSynthesizerAgent
    participant MEM as MemoryAgent
    participant BUS as Kafka

    SUP->>DPA: activity start_phase(discover, RunPlan.discover)
    par Fan-out over A2A (independent, parallel)
        DPA->>PD: A2A message/send(subtask: problem space)
        DPA->>MR: A2A message/send(subtask: market sizing)
        DPA->>PAT: A2A message/send(subtask: patent landscape)
        DPA->>CI: A2A message/send(subtask: competitor scan)
    end
    MR->>TSA: select_tool("market TAM/SAM/SOM")
    TSA-->>MR: bind market-research MCP tool
    MR->>MCP: tools/call market_research.size_market(args)
    MCP-->>MR: cited market data
    PAT->>MCP: tools/call patent.search(query)
    MCP-->>PAT: patent hits + citations
    PD-->>DPA: Problem Space artifact (confidence 0.82)
    MR-->>DPA: Market Insights artifact (0.78)
    PAT-->>DPA: Patent Landscape artifact (0.80)
    CI-->>DPA: Competitor Map artifact (0.75)
    DPA->>RS: A2A synthesize([artifacts], dedupe+cluster)
    RS->>MEM: retrieve(scope=project, related insights)
    MEM-->>RS: prior insights (semantic + graph)
    RS-->>DPA: Insights + Opportunity Areas + Personas (0.86)
    DPA->>MEM: write(episodic + semantic + KG: Persona/Insight nodes)
    DPA->>BUS: CE edt.discover.persona.created / edt.discover.insight.created
    DPA-->>SUP: DiscoverOutputBundle (aggregate confidence 0.84)
```

**Explanation.** The Phase Agent is a **LangGraph** graph whose nodes fan out to independent
Worker A2A services in parallel (`par`). Workers reach external data only through the **Tool
Selection Agent → MCP Gateway** path ([07](./07-mcp-architecture.md),
[08](./08-tool-architecture.md)), so all access is permissioned and audited. The
**Research Synthesizer** de-duplicates and clusters across workers, enriches with project
memory, and the Phase Agent persists results into **episodic, semantic, and knowledge-graph**
memory before emitting CloudEvents. Aggregate confidence gates whether the phase proceeds or
loops.

---

## (c) Reflection → Critique → Self-Correction Loop (single agent)

```mermaid
sequenceDiagram
    autonumber
    participant W as Worker Agent (e.g. ProblemStatementAgent)
    participant LLM as Claude (Sonnet 5)
    participant REF as Reflection Agent :9102
    participant CRIT as Critic Agent :9102 (Opus 4.8)
    participant QA as Quality Agent
    participant MEM as MemoryAgent
    participant HITL as Human Approval Agent

    W->>LLM: plan() + act() → draft artifact (ReAct)
    W->>W: compute self-confidence = 0.62 (< threshold 0.75)
    W->>REF: reflect(draft, task, evidence)
    REF-->>W: reflection {gaps: "root cause unsupported by data", missing citations}
    W->>CRIT: critique(draft, reflection)
    CRIT->>LLM: Opus deep review (rubric: clarity, evidence, feasibility, bias)
    LLM-->>CRIT: scored critique {evidence: 0.5, clarity: 0.8, risk_flags:[...]}
    CRIT-->>W: critique report + required fixes
    W->>W: self_correct() → revise draft using critique + re-retrieve evidence
    W->>MEM: retrieve(additional evidence for weak claims)
    MEM-->>W: cited supporting facts
    W->>LLM: regenerate artifact
    W->>W: self-confidence = 0.83 (>= threshold)
    W->>QA: validate against Output Schema (Pydantic) + guardrails
    QA-->>W: pass
    alt confidence >= escalation-safe band
        W-->>W: emit(artifact)
    else still below threshold after N retries
        W->>HITL: escalate(draft, critique history)
    end
```

**Explanation.** This is the `plan → act → reflect → critique → self_correct → emit` contract
from `BaseAgent`. **Reflection** (Reflexion pattern) is cheap self-diagnosis; **Critique** is
an independent, higher-tier (**Opus 4.8**) adversarial review against a rubric;
**self-correction** re-retrieves evidence ([06](./06-rag-architecture.md)) and regenerates.
The loop is bounded by a retry budget (`retry_policy`); exhausting it escalates to a human
rather than emitting a low-confidence artifact. Quality Agent enforces the Pydantic output
schema and guardrails before emit.

---

## (d) Human-Approval Checkpoint (Temporal Signal)

```mermaid
sequenceDiagram
    autonumber
    participant SUP as Supervisor (Temporal workflow)
    participant TMP as Temporal
    participant HAA as Human Approval Agent :9103
    participant BUS as Kafka
    participant INBOX as Approval Inbox (Next.js)
    actor Approver as Human Approver
    participant MEM as MemoryAgent

    SUP->>TMP: awaitSignal("phase_approval:discover") + set 72h timer
    SUP->>HAA: create_approval_request(run_id, phase=discover, bundle_ref)
    HAA->>BUS: CE edt.approval.requested
    BUS->>INBOX: notify (WebSocket) + email
    INBOX-->>Approver: render bundle + evidence + confidence + citations
    Approver->>INBOX: Approve with comment / Reject / Request revision
    INBOX->>HAA: POST /approvals/{id} {decision, comment, approver_id}
    HAA->>TMP: signalWorkflow("phase_approval:discover", decision)
    HAA->>MEM: write(episodic: approval decision + rationale)
    HAA->>BUS: CE edt.approval.granted | edt.approval.rejected
    alt Approved
        TMP-->>SUP: signal received → proceed to Define phase
    else Rejected / Revision requested
        TMP-->>SUP: signal → re-run phase with approver feedback in context
    else Timer fires (72h, no response)
        TMP-->>SUP: timeout → escalate per escalation_rules (manager notify)
    end
```

**Explanation.** Approval is a **durable wait** — the workflow parks on
`awaitSignal` and consumes **no compute** while waiting, yet survives restarts and can wait
days. The gate carries full evidence (confidence + citations + provenance) so the human
decision is informed and auditable. Rejection feeds approver comments back into the phase's
context for a targeted re-run. A timer enforces SLAs and triggers escalation. Gates exist
after **every phase** and **before every executive deliverable** (per canonical conventions).

---

## (e) A2A Message Exchange Between Two Agents (with Agent Cards)

```mermaid
sequenceDiagram
    autonumber
    participant IDA as IdeationAgent
    participant REG as A2A Registry / Discovery
    participant CARD as CustomerSimulatorAgent /.well-known/agent-card.json
    participant CSA as CustomerSimulatorAgent :90xx
    participant IDP as Keycloak (OIDC)

    IDA->>REG: discover(capability="persona-based concept reaction")
    REG-->>IDA: CustomerSimulatorAgent {url, skills[]}
    IDA->>CARD: GET /.well-known/agent-card.json
    CARD-->>IDA: Agent Card {skills, inputModes, securitySchemes}
    IDA->>IDP: client_credentials → access_token (scope: agent.invoke)
    IDP-->>IDA: JWT
    IDA->>CSA: JSON-RPC message/send {method, params:{skill:"react-to-concept", concept, persona}} + Bearer JWT
    CSA->>CSA: validate token + ABAC policy + input guardrails
    CSA-->>IDA: JSON-RPC result {task_id, status:"working"}
    loop until complete (streaming / poll)
        IDA->>CSA: tasks/get {task_id}
        CSA-->>IDA: {status:"working", partial reactions}
    end
    CSA-->>IDA: {status:"completed", artifact: SimulatedReaction (confidence 0.79, provenance)}
```

**Explanation.** Inter-agent calls are **capability-discovered, not hard-coded**. An agent
finds a peer via the registry, fetches its **Agent Card** to learn skills/IO modes/security,
obtains an OIDC token (Keycloak) scoped to `agent.invoke`, then issues a JSON-RPC
`message/send`. The callee enforces token + ABAC + guardrails before working. Long tasks use
A2A `tasks/get` polling or streaming. This is how agents in *different deployments* collaborate
without shared code — see [01 §5](./01-architecture.md).

---

## (f) Validation → Ideation Feedback Loop

```mermaid
sequenceDiagram
    autonumber
    participant SUP as Supervisor
    participant VPA as ValidatePhaseAgent
    participant FA as FeedbackAnalyzerAgent
    participant GNG as Go/No-Go Agent (Opus 4.8)
    participant IPA as IdeatePhaseAgent
    participant IRef as IdeaRefinerAgent
    participant MEM as MemoryAgent
    participant BUS as Kafka

    VPA->>FA: analyze(validation results: sim reactions, market, ROI, risk)
    FA-->>VPA: findings {concept C3 fails pricing, C7 weak differentiation}
    VPA->>GNG: decide(concepts, thresholds)
    GNG-->>VPA: NO-GO for C3/C7; CONDITIONAL for C5 (needs refinement)
    VPA->>MEM: write(KG: Risk + Insight edges; episodic: validation verdict)
    VPA->>BUS: CE edt.validate.nogo / edt.validate.conditional
    alt Concepts salvageable → loop back to Ideate
        VPA->>SUP: request_reentry(phase=ideate, feedback)
        SUP->>IPA: re-open Ideate with validation feedback in context
        IPA->>IRef: refine(C5, constraints from validation)
        IRef->>MEM: retrieve(root causes + JTBD from Define)
        MEM-->>IRef: cited context
        IRef-->>IPA: refined concept C5' (confidence 0.85)
        IPA-->>SUP: updated concept set → re-enter Prototype/Validate
    else All concepts validated
        VPA-->>SUP: ValidationReport + BusinessCase + ROI + Roadmap
        SUP->>BUS: CE edt.run.completed
    end
```

**Explanation.** Design Thinking is iterative, not linear. When validation surfaces failing or
conditional concepts, the **Go/No-Go Agent** (Opus 4.8) applies decision criteria, and the
Supervisor **re-opens an earlier phase** (Temporal supports re-entry as child-workflow
re-invocation). Validation feedback is injected into the Ideate context, and the
**Idea Refiner** pulls Define-phase root causes/JTBD from memory to fix the concept rather
than start over. The loop terminates when concepts pass thresholds, producing the executive
deliverables. Every loop iteration is bounded by the run budget and its own approval gate.

---

## Cross-Cutting Interaction Notes

- **Observability:** every A2A hop and MCP `tools/call` propagates the OTel trace context
  (`traceparent`); Langfuse captures the LLM spans (prompt, tokens, cost, latency) keyed by
  `run_id`/`agent`/`turn`.
- **Idempotency:** CloudEvents carry a dedupe key (`run_id + agent + logical_step`); consumers
  are idempotent so Kafka at-least-once delivery is safe.
- **Back-pressure:** worker deployments scale on Kafka lag + Temporal task-queue depth (KEDA);
  the Supervisor throttles fan-out to respect the run's cost budget.
- **Memory on every step:** reads/writes go through the MemoryAgent APIs
  (`retrieve/write/consolidate/forget`) detailed in [05](./05-memory-architecture.md).
