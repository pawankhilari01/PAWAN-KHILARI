# 20 — Production Readiness Checklist

> **EDT Platform** (`edt_platform`) — the go-live gate. Every item is concrete and checkable. A release to **prod** requires all **[MUST]** items checked and **[SHOULD]** items either checked or explicitly waived with sign-off.
>
> **Related docs:** [`15` Deployment](./15-deployment-architecture.md) · [`16` Evaluation](./16-evaluation-framework.md) · [`14` Observability] · [`08` Guardrails]
>
> **Legend:** `[MUST]` blocks go-live · `[SHOULD]` strong default · `[NICE]` incremental.

---

## 1. Reliability & SLOs

- [ ] **[MUST]** SLOs defined per user-facing service (API, console, Supervisor) and per phase-run: availability, latency (p95/p99), run success rate.
- [ ] **[MUST]** Error budgets defined with an error-budget policy (freeze features when burned).
- [ ] **[MUST]** Health probes (`/healthz/live`, `/healthz/ready`) on every service; readiness gates traffic.
- [ ] **[MUST]** Graceful shutdown + connection draining; PodDisruptionBudgets on critical services.
- [ ] **[MUST]** Runs are **idempotent & resumable** — Temporal + LangGraph checkpoints resume an interrupted run at the last completed phase/agent ([`17`](./17-example-execution.md)).
- [ ] **[MUST]** Retry with backoff + jitter and **dead-letter topics** for poison Kafka messages; DLQ has an alarm + runbook.
- [ ] **[SHOULD]** Circuit breakers / outlier detection on A2A + external LLM calls (Istio `DestinationRule`, [`15` §3.4](./15-deployment-architecture.md)).
- [ ] **[SHOULD]** Timeouts set at every hop (LLM, tool, A2A, DB); no unbounded waits.
- [ ] **[SHOULD]** Load/soak test at ≥ 2× projected peak concurrency; results recorded.
- [ ] **[SHOULD]** Chaos experiment (kill a phase agent mid-run) proves resumability.

## 2. Scalability

- [ ] **[MUST]** KEDA scale-to-zero + max-replica budgets configured per worker agent ([`15` §3.3](./15-deployment-architecture.md)).
- [ ] **[MUST]** HPA on request-driven services with sane min/max and target metrics.
- [ ] **[MUST]** **Aggregate LLM concurrency cap** + Redis token-bucket prevents autoscaler stampede against the Messages API.
- [ ] **[MUST]** Resource `requests`/`limits` set on every container; no unbounded pods.
- [ ] **[SHOULD]** Karpenter node autoscaling with Spot for stateless workers, consolidation enabled.
- [ ] **[SHOULD]** Kafka partitions sized for target parallelism; consumer-group lag dashboards.
- [ ] **[SHOULD]** DB connection pooling (PgBouncer) sized; no per-pod connection blowups.
- [ ] **[SHOULD]** Qdrant/Neo4j capacity + sharding plan validated against corpus growth.

## 3. Security — AuthN/AuthZ, Secrets, Encryption, Network, Supply Chain

**Identity & access**
- [ ] **[MUST]** OIDC (Keycloak) for all human access; MFA enforced; federated to enterprise IdP.
- [ ] **[MUST]** RBAC/ABAC enforced at API gateway (OPA) and human-approval gates; least privilege.
- [ ] **[MUST]** Service-to-service auth = Istio mTLS **and** OIDC client-credentials; A2A validates both.
- [ ] **[MUST]** IRSA / least-privilege IAM per service account; no shared node roles.

**Secrets & encryption**
- [ ] **[MUST]** All secrets in Vault; none in env files, images, or Git; gitleaks in CI ([`15` §7](./15-deployment-architecture.md)).
- [ ] **[MUST]** Dynamic DB/Redis creds with TTL + rotation; API-key rotation runbook.
- [ ] **[MUST]** Encryption at rest (KMS: RDS, S3 SSE-KMS, EBS, ElastiCache) and in transit (TLS/mTLS everywhere).
- [ ] **[SHOULD]** Envelope-encrypt especially sensitive artifact fields (Vault transit).

**Network**
- [ ] **[MUST]** Default-deny NetworkPolicies; explicit tier-to-tier allows only.
- [ ] **[MUST]** **Egress allow-list** (Anthropic/Voyage/Cohere/approved APIs only) — anti-exfiltration ([`15` §12](./15-deployment-architecture.md)).
- [ ] **[MUST]** WAF (OWASP + rate limit) + DDoS protection at the edge; private subnets for nodes/data; VPC endpoints.

**Supply chain**
- [ ] **[MUST]** Images signed (cosign) + admission verification; SBOM generated (Syft).
- [ ] **[MUST]** CVE scan (Trivy/Grype) blocks HIGH/CRITICAL; IaC scan (checkov/tfsec); SAST (CodeQL); dep pinning + Dependabot/Renovate.
- [ ] **[SHOULD]** Runtime threat detection (Falco/GuardDuty); read-only root FS; seccomp `RuntimeDefault`; drop all caps.
- [ ] **[SHOULD]** Pen test / red-team of the platform completed and findings remediated.

## 4. Responsible AI

- [ ] **[MUST]** **Model cards** for each agent (purpose, model tier, data, limitations, eval scores) published internally.
- [ ] **[MUST]** Bias/fairness evals pass — persona/recommendation counterfactual tests within tolerance ([`16` §12](./16-evaluation-framework.md)).
- [ ] **[MUST]** Safety classifier (Anthropic safety + Llama-Guard-style) on inputs/outputs; jailbreak/red-team suite passes.
- [ ] **[MUST]** **Human oversight** — approval gates after each phase + before executive deliverables; no fully-autonomous ship.
- [ ] **[MUST]** Transparency — every artifact carries provenance, producing agent, model version, confidence, and rubric rationale; reflection/loops visible in the trace.
- [ ] **[MUST]** Hallucination controls — RAG faithfulness gate ≥ 0.85; citation checks; no fabricated stats (the persona-loop failure mode, [`17` §2.1](./17-example-execution.md)).
- [ ] **[SHOULD]** Business-case anti-manipulation checks (assumption transparency + sensitivity) enforced.
- [ ] **[SHOULD]** Responsible-AI agent mandatory on regulated-domain runs; documented escalation path for harmful/uncertain outputs.

## 5. Privacy & Compliance

- [ ] **[MUST]** PII inventory + data-flow map; PII minimization; Presidio redaction before external LLM egress where policy requires.
- [ ] **[MUST]** **GDPR/CCPA** posture: lawful basis, consent capture, DSAR (access/delete/export) workflow, retention schedule.
- [ ] **[MUST]** **Data residency** enforced (tenant region tag → routing; Bedrock-in-VPC option for strict residency, [`15` §4](./15-deployment-architecture.md)).
- [ ] **[MUST]** DPA / sub-processor list current; LLM provider data-use terms reviewed (no training on customer data).
- [ ] **[SHOULD]** **SOC 2 Type II** and **ISO 27001** controls mapped; evidence collection automated.
- [ ] **[SHOULD]** Domain-specific compliance profiles wired (e.g., banking: Reg E/BSA-AML/fair-lending gates as in [`18` §13](./18-sample-outputs.md)).
- [ ] **[SHOULD]** Audit log immutability (S3 Object Lock) for approvals and money/decision events.

## 6. Observability

- [ ] **[MUST]** OpenTelemetry traces end-to-end (run → phase → agent turn → tool/LLM call); trace IDs propagate across A2A + Kafka.
- [ ] **[MUST]** **Langfuse** LLM tracing (prompt, model, tokens, cost, latency) on every generation.
- [ ] **[MUST]** Prometheus metrics (RED + USE) + Grafana dashboards; Loki structured logs (structlog) with correlation IDs.
- [ ] **[MUST]** Alerting on SLO burn, DLQ, error rate, latency, cost anomaly, guardrail/eval regression; routed to on-call.
- [ ] **[MUST]** **SLO dashboards** per service + per-run success/quality dashboards.
- [ ] **[SHOULD]** Online eval + drift dashboards (quality/input/behavior/model drift, [`16` §11](./16-evaluation-framework.md)).
- [ ] **[SHOULD]** No PII/secrets in logs (redaction verified); log retention policy set.

## 7. Cost Governance

- [ ] **[MUST]** Per-run, per-tenant, per-phase **token budgets** enforced by the Cost/Token-Optimization agent (hard stop + escalate).
- [ ] **[MUST]** Model routing live (Haiku/Sonnet/Opus by task) + prompt caching enabled ([`15` §11](./15-deployment-architecture.md)).
- [ ] **[MUST]** Cost attribution per run/tenant/agent/model (Langfuse + Kubecost); budgets + anomaly alerts.
- [ ] **[SHOULD]** Semantic/retrieval caching + tool-call dedup within a run; batching of extraction to Haiku.
- [ ] **[SHOULD]** Monthly FinOps review; unit economics ($/run, $/phase) tracked and trending.

## 8. Evaluation & Quality Gates

- [ ] **[MUST]** CI eval gates green: promptfoo regression, DeepEval suites, RAGAS thresholds, phase rubrics, red-team ([`16` §13](./16-evaluation-framework.md)).
- [ ] **[MUST]** Canary/rollout analysis wired to online judge scores + SLOs; auto-rollback on breach.
- [ ] **[MUST]** Golden datasets versioned (Git+DVC), PII-scrubbed, reviewed.
- [ ] **[MUST]** Confidence thresholds + escalation rules configured per agent; below-threshold → reflect/retry/escalate.
- [ ] **[SHOULD]** Judge-vs-human calibration (κ ≥ 0.6) checked; ECE monitored.
- [ ] **[SHOULD]** Human-in-the-loop labels flow back into golden sets.

## 9. DR / Backup

- [ ] **[MUST]** RPO/RTO targets defined (≤ 15 min / ≤ 1 h core) and documented.
- [ ] **[MUST]** Automated backups: RDS PITR, Vault raft snapshots, Qdrant/Neo4j snapshots to S3; S3 versioning + CRR.
- [ ] **[MUST]** **Restore tested** (not just backed up) — documented, dated, within RTO.
- [ ] **[MUST]** Multi-AZ for RDS/MSK/Redis; anti-affinity for stateful clusters.
- [ ] **[SHOULD]** Cross-region DR (RDS read replica, MSK replicator, warm EKS) with a rehearsed failover runbook.
- [ ] **[SHOULD]** Quarterly DR game-day executed; results recorded.

## 10. Runbooks & On-Call

- [ ] **[MUST]** On-call rotation + escalation policy defined; paging tested.
- [ ] **[MUST]** Runbooks for top failure modes: DLQ drain, stuck run, LLM provider outage, cost spike, guardrail incident, eval regression, DB failover.
- [ ] **[MUST]** Incident response process (severity levels, comms, postmortem template) documented.
- [ ] **[SHOULD]** **Break-glass** access procedure for prod, audited.
- [ ] **[SHOULD]** Blameless postmortems required for SEV1/2; action items tracked to closure.

## 11. Data Governance

- [ ] **[MUST]** Data classification (public/internal/confidential/regulated) applied to all stores.
- [ ] **[MUST]** Artifact lineage/provenance recorded (Postgres metadata + S3 blob + Qdrant index + Neo4j links) per the canonical contract.
- [ ] **[MUST]** Retention & deletion policies per data class; enforced (S3 lifecycle, DB jobs).
- [ ] **[SHOULD]** Schema Registry governs event contracts (CloudEvents + JSON Schema/Avro); compatibility checks in CI.
- [ ] **[SHOULD]** Access to memory stores (semantic/graph) scoped per tenant; cross-tenant leakage tested.

## 12. Model & Prompt Versioning & Rollback

- [ ] **[MUST]** Prompts versioned in Git (`prompts/`) with semver; every artifact records the prompt + model version used.
- [ ] **[MUST]** Model routing config versioned; pinned model IDs (`claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5`).
- [ ] **[MUST]** Rollback path for prompts/agents/config (Git revert → ArgoCD sync) tested and fast.
- [ ] **[MUST]** Provider model updates detected by canary golden-set runs before broad adoption ([`16` §11](./16-evaluation-framework.md)).
- [ ] **[SHOULD]** Playbook/procedural-memory versions tracked; promotion requires eval + human sign-off.

## 13. Change Management & CI/CD

- [ ] **[MUST]** GitOps only to prod (ArgoCD); no manual `kubectl apply` in staging/prod ([`15` §6](./15-deployment-architecture.md)).
- [ ] **[MUST]** **Two-person approval** + manual sync for prod deploys; change record generated.
- [ ] **[MUST]** Build-once/promote-same-image across dev→staging→prod; immutable `:<git-sha>` tags.
- [ ] **[MUST]** Progressive delivery (Argo Rollouts canary) with automated analysis + auto-rollback.
- [ ] **[SHOULD]** Feature flags for risky agent/prompt changes; kill-switch per agent.
- [ ] **[SHOULD]** Deploy freeze windows + release calendar respected.

## 14. Documentation

- [ ] **[MUST]** Architecture, deployment, eval, and runbook docs current (this `docs/` set) and linked.
- [ ] **[MUST]** Agent specs complete (25-field template) for every deployed agent; Agent Cards published.
- [ ] **[MUST]** API/SDK reference published; onboarding guide for new operators.
- [ ] **[SHOULD]** Model cards + responsible-AI statement accessible to stakeholders.
- [ ] **[SHOULD]** Customer-facing "how a run works" explainer (maps to [`17`](./17-example-execution.md)/[`18`](./18-sample-outputs.md)).

---

## 15. Go-Live Sign-Off

| Area | Owner | Status | Waivers |
|---|---|---|---|
| Reliability/SLOs | SRE lead | ☐ | |
| Security | Security lead | ☐ | |
| Responsible AI | RAI lead | ☐ | |
| Privacy/Compliance | DPO / Compliance | ☐ | |
| Observability | Platform lead | ☐ | |
| Cost governance | FinOps | ☐ | |
| Eval/Quality | ML/Eval lead | ☐ | |
| DR/Backup | SRE lead | ☐ | |
| Data governance | Data lead | ☐ | |

> **Go-live rule:** all `[MUST]` checked across §1–14; each area signed above; open `[SHOULD]` items either checked or waived with a dated rationale and owner. Re-review on any change to model tiers, data classes, or regulated-domain scope.
