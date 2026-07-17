# 09 — Folder Structure

The repository is a **polyrepo-ready monorepo**: one Python package (`edt_platform`)
containing the orchestrator + all agent implementations, plus per-agent deployability
(each agent can be built into its own container and exposed as an A2A service). Docs,
prompts, MCP servers, infra, and tests are top-level siblings.

See also: [01-architecture](01-architecture.md) · [10-prompt-library](10-prompt-library.md) ·
[15-deployment-architecture](15-deployment-architecture.md).

```text
PAWAN-KHILARI/
├── README.md                     # Entry point: what/why/how, quickstart
├── pyproject.toml                # Package metadata, deps, ruff/mypy/pytest config
├── Makefile                      # dev, test, lint, run, docker targets
├── .env.example                  # All EDT_* env vars with safe defaults
├── .github/workflows/ci.yml      # Lint → type → test → build → scan → eval gate
│
├── docs/                         # The 20 numbered, implementation-ready deliverables
│   ├── 01-architecture.md
│   ├── 02-agent-catalog.md
│   ├── 03-workflow.md
│   ├── 04-agent-interaction-sequence.md
│   ├── 05-memory-architecture.md
│   ├── 06-rag-architecture.md
│   ├── 07-mcp-architecture.md
│   ├── 08-tool-architecture.md
│   ├── 09-folder-structure.md          (this file)
│   ├── 10-prompt-library.md
│   ├── 11-agent-specifications.md       # Full 25-field specs + long-form prompts
│   ├── 12-api-specification.md
│   ├── 13-data-model.md
│   ├── 14-event-model.md
│   ├── 15-deployment-architecture.md
│   ├── 16-evaluation-framework.md
│   ├── 17-example-execution.md
│   ├── 18-sample-outputs.md
│   ├── 19-future-enhancements.md
│   ├── 20-production-readiness-checklist.md
│   └── openapi.yaml                     # Control-plane OpenAPI 3.1
│
├── prompts/                      # Machine-loaded prompt library (versioned, eval'd)
│   ├── README.md
│   ├── discover/  define/  ideate/  prototype/  validate/  crosscutting/
│
├── mcp_servers/                  # MCP tool servers (one dir per server)
│   └── market_research/          # reference Python MCP server
│
├── src/edt_platform/             # The platform package
│   ├── __init__.py
│   ├── cli.py                    # `edt run "<problem>"`
│   │
│   ├── config/                   # 12-factor settings (LLM, stores, events, RAG, governance)
│   │   └── settings.py
│   │
│   ├── schemas/                  # Pydantic contracts shared by all agents
│   │   ├── core.py               # Artifact, AgentInput/Result, Phase, Provenance, Confidence
│   │   └── artifacts.py          # Persona, JTBD, HMW, Idea, PRD, RiskItem, FinancialModel...
│   │
│   ├── core/                     # Agent runtime primitives
│   │   ├── llm.py                # Governed Claude client (routing, caching, structured, cost)
│   │   └── base_agent.py         # BaseAgent: plan→act→reflect→critique→self_correct loop
│   │
│   ├── memory/                   # Layered long-term memory
│   │   └── memory_agent.py       # working/episodic/semantic/procedural/graph
│   ├── rag/                      # Hybrid + GraphRAG retriever
│   │   └── retriever.py
│   ├── knowledge/                # Knowledge-graph adapters (Neo4j)
│   ├── tools/                    # Tool Registry + selection + circuit-breaker
│   │   └── registry.py
│   ├── mcp/                      # MCP client router (adapts MCP tools into the registry)
│   │   └── client.py
│   ├── a2a/                      # Agent2Agent: Agent Card + task request/result models
│   │   └── agent_card.py
│   ├── eventing/                 # CloudEvents publisher over Kafka
│   │   └── publisher.py
│   │
│   ├── orchestration/            # Supervisor + planner + durable workflow
│   │   ├── workflow_planner.py   # Phase/worker roster + plan
│   │   ├── supervisor.py         # Phase fan-out/fan-in, gates, feedback loops
│   │   └── temporal_workflow.py  # Durable Temporal skeleton + approval signals
│   │
│   ├── agents/                   # All agent implementations
│   │   ├── registry.py           # name → factory (generic + specialized)
│   │   ├── supervisor/           # (phase-agent variants)
│   │   ├── discover/             # problem_discovery, persona_builder, ...
│   │   ├── define/  ideate/  prototype/  validate/
│   │   └── crosscutting/         # critic, (reflection, quality, ...)
│   │       └── critic.py
│   │
│   ├── api/                      # FastAPI control plane (runs, artifacts, approvals, SSE)
│   │   └── app.py
│   ├── security/                 # Guardrails (PII, injection, policy, Responsible AI)
│   │   └── guardrails.py
│   ├── evaluation/               # LLM-as-Judge panel + rubrics
│   │   └── judge.py
│   └── observability/            # OTel tracing decorator, metrics, structured logs
│       └── tracing.py
│
├── deploy/                       # Infrastructure as code
│   ├── docker/Dockerfile         # Multi-stage image (control plane + agents)
│   ├── docker-compose.yml        # Local stack: postgres, redis, qdrant, neo4j, kafka, minio
│   ├── k8s/helm/edt-platform/    # Helm chart (control plane + per-agent deployments)
│   └── terraform/                # AWS reference (EKS, RDS, MSK, S3, ElastiCache)
│
├── scripts/                      # Operational helpers (migrate, seed, eval-run)
└── tests/                        # pytest suite (offline, fakes injected)
    ├── conftest.py               # Fake Anthropic client
    └── test_pipeline.py          # Full-lifecycle smoke + unit tests
```

## Why this shape

| Decision | Rationale |
|---|---|
| Single package, many agents | One shared contract (`schemas/`) + one runtime (`core/`) prevents drift across ~95 agents while `agents/<phase>/` keeps ownership clear. |
| Ports & adapters in `AgentContext` | Every external dependency (LLM, memory, RAG, tools, events) is injected, so agents are unit-testable with fakes and swappable in prod. |
| `prompts/` separate from code | Prompts are versioned data, hot-reloadable and eval-gated independently of releases ([10-prompt-library](10-prompt-library.md)). |
| `orchestration/` isolated | The Supervisor/planner/Temporal logic is the one place control-flow lives; agents stay stateless workers. |
| Per-agent deployability | `deploy/k8s/helm` templates a Deployment per agent service so teams scale/ship agents independently ([15-deployment-architecture](15-deployment-architecture.md)). |

## Adding a new specialized agent (checklist)
1. Create `src/edt_platform/agents/<phase>/<name>.py` subclassing `BaseAgent` (implement `plan`/`act`).
2. Add its prompt at `prompts/<phase>/<name>.yaml` with eval cases.
3. Register it in `agents/registry.py` (overrides the generic worker).
4. Add its output type to `schemas/` if it produces a new artifact.
5. Add rubric dimensions in `evaluation/judge.py` and a promptfoo suite.
6. Ship: the Helm chart picks it up as a new A2A Deployment.
