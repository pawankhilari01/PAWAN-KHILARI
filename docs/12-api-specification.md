# 12 — API Specification

> **EDT Platform** (`edt_platform`). Control-plane REST API (**FastAPI + Uvicorn + Pydantic
> v2**), **A2A** (Agent2Agent, JSON-RPC 2.0) inter-agent protocol, and the SSE/WebSocket live
> stream.
>
> **Related docs:** [`03-workflow.md`](./03-workflow.md) ·
> [`13-data-model.md`](./13-data-model.md) ·
> [`14-event-model.md`](./14-event-model.md) · [`openapi.yaml`](./openapi.yaml)

Base URL: `https://api.edt.example.com` · API version prefix: `/v1` ·
Media type: `application/json` · Auth: **OIDC bearer (Keycloak/OAuth2)**.

---

## 1. Conventions

### 1.1 AuthN / AuthZ
- **AuthN:** OAuth2 / OIDC (Keycloak). Clients send `Authorization: Bearer <JWT>`. Tokens are
  RS256, validated against the JWKS; `aud=edt-api`, `iss=https://id.edt.example.com/realms/edt`.
- **AuthZ:** RBAC + ABAC. Scopes carried in the `scope` claim; roles in `realm_access.roles`.

| Scope | Grants |
|-------|--------|
| `runs:read` | list/get runs, phases, events |
| `runs:write` | start/cancel runs |
| `artifacts:read` | read artifacts + versions |
| `approvals:read` | list approvals |
| `approvals:write` | approve/reject (requires `approver` role) |
| `agents:read` | read agent registry / cards |
| `evaluations:read` | read eval results |
| `memory:query` | semantic memory queries |
| `admin` | org/project admin |

- **ABAC:** every request is tenant-scoped by `org_id` from the token; cross-org access is
  denied at the dependency layer.

### 1.2 Error envelope
All non-2xx responses use a consistent envelope (RFC 9457 problem+json compatible):

```json
{
  "error": {
    "type": "https://errors.edt/validation",
    "code": "validation_error",
    "message": "confidence_threshold must be between 0 and 1",
    "status": 422,
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "details": [{"field": "confidence_threshold", "issue": "out_of_range"}]
  }
}
```

| Status | `code` | When |
|--------|--------|------|
| 400 | `bad_request` | malformed request |
| 401 | `unauthorized` | missing/invalid token |
| 403 | `forbidden` | scope/role/tenant denied |
| 404 | `not_found` | resource missing or not in tenant |
| 409 | `conflict` | illegal state transition (e.g. cancel a completed run) |
| 422 | `validation_error` | schema validation failed |
| 429 | `rate_limited` | quota exceeded (see 1.4) |
| 500 | `internal_error` | unexpected |

### 1.3 Pagination
Cursor-based. Requests: `?limit=50&cursor=<opaque>`. Responses:

```json
{ "items": [ ... ], "next_cursor": "eyJvZmZzZXQiOjUwfQ==", "has_more": true }
```
`limit` default 50, max 200. Sorting via `?sort=-created_at`.

### 1.4 Rate limiting
Token-bucket in Redis, keyed by `client_id + route class`. Response headers:
`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and `Retry-After` on 429.
Defaults: read 600 rpm, write 120 rpm, `runs:write` 20 rpm, SSE 50 concurrent streams/org.

### 1.5 Idempotency
Mutating POSTs accept an `Idempotency-Key` header; the key + body hash are cached in Redis 24h
and replay the original response.

---

## 2. Control-plane REST endpoints

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| `GET` | `/v1/projects` | `runs:read` | List projects (paginated) |
| `POST` | `/v1/projects` | `admin` | Create project |
| `GET` | `/v1/projects/{project_id}` | `runs:read` | Get project |
| `POST` | `/v1/projects/{project_id}/runs` | `runs:write` | Start a run |
| `GET` | `/v1/runs` | `runs:read` | List runs (filter by project/state) |
| `GET` | `/v1/runs/{run_id}` | `runs:read` | Get run (state, phases, cost) |
| `POST` | `/v1/runs/{run_id}/cancel` | `runs:write` | Cancel a run |
| `GET` | `/v1/runs/{run_id}/phases` | `runs:read` | List phases |
| `GET` | `/v1/runs/{run_id}/artifacts` | `artifacts:read` | List artifacts of a run |
| `GET` | `/v1/artifacts/{artifact_id}` | `artifacts:read` | Get artifact (latest version) |
| `GET` | `/v1/artifacts/{artifact_id}/versions` | `artifacts:read` | List versions |
| `GET` | `/v1/runs/{run_id}/approvals` | `approvals:read` | List approvals for a run |
| `GET` | `/v1/approvals` | `approvals:read` | List approvals (filter `?decision=pending`) |
| `POST` | `/v1/approvals/{approval_id}/approve` | `approvals:write` | Approve a gate |
| `POST` | `/v1/approvals/{approval_id}/reject` | `approvals:write` | Reject a gate |
| `GET` | `/v1/runs/{run_id}/events` | `runs:read` | List persisted events (paginated) |
| `GET` | `/v1/runs/{run_id}/stream` | `runs:read` | **SSE** live progress |
| `GET` | `/v1/agents` | `agents:read` | List registered agents |
| `GET` | `/v1/agents/{agent_id}` | `agents:read` | Get agent + Agent Card |
| `GET` | `/v1/evaluations` | `evaluations:read` | List eval results (filter by subject) |
| `POST` | `/v1/memory/query` | `memory:query` | Semantic memory query |

### 2.1 Start a run

`POST /v1/projects/{project_id}/runs`

```json
// request
{
  "business_problem": "Reduce last-mile delivery cost for mid-market logistics",
  "confidence_threshold": 0.70,
  "budget_usd_cap": 200.00,
  "options": { "auto_approve_gates": false, "reuse_memory": true }
}
```
```json
// 201 Created
{
  "run_id": "018f9b00-1111-7000-8000-000000000001",
  "project_id": "018f9a00-0000-7000-8000-000000000001",
  "state": "planning",
  "temporal_workflow_id": "run-018f9b00-1111",
  "created_at": "2026-07-17T09:10:00Z"
}
```

### 2.2 Get a run

`GET /v1/runs/{run_id}` → `200`

```json
{
  "run_id": "018f9b00-1111-7000-8000-000000000001",
  "project_id": "018f9a00-0000-7000-8000-000000000001",
  "state": "awaiting_approval",
  "pending_gate": "gate_1",
  "confidence_threshold": 0.70,
  "budget_usd_cap": 200.00,
  "cost_usd_spent": 41.20,
  "phases": [
    {"name": "discover", "seq": 1, "status": "completed", "avg_confidence": 0.83},
    {"name": "define",   "seq": 2, "status": "pending"}
  ],
  "created_at": "2026-07-17T09:10:00Z"
}
```

### 2.3 Cancel a run

`POST /v1/runs/{run_id}/cancel` → `202 Accepted` (state → `cancelled`; `409` if terminal).

### 2.4 Approvals

`GET /v1/approvals?decision=pending` → list. Approve/reject:

`POST /v1/approvals/{approval_id}/approve`
```json
{ "comments": "Research is solid, proceed." }
```
```json
// 200
{ "approval_id": "...", "gate_id": "gate_1", "decision": "approved",
  "decided_by": "user_9", "decided_at": "2026-07-17T10:05:00Z" }
```
Reject mirrors this at `/reject` and triggers the loop back to the producing phase
([`03-workflow.md`](./03-workflow.md#45-how-loops-are-triggered)). Both emit
`edt.approval.granted` / `edt.approval.rejected` ([`14-event-model.md`](./14-event-model.md))
which resume the Temporal workflow signal.

### 2.5 Memory query

`POST /v1/memory/query`
```json
{ "query": "personas for logistics dispatch", "layer": "semantic",
  "collection": "edt_personas", "top_k": 5, "filter": {"project_id": "..."} }
```
```json
{ "results": [
  {"subject_id": "...", "text": "Regional Operations Lead ...", "score": 0.89,
   "run_id": "...", "phase": "discover"}
]}
```

---

## 3. A2A protocol (inter-agent)

Every worker/phase agent is an independently deployable **A2A** service (JSON-RPC 2.0 over
HTTP). Agents advertise capabilities via an **Agent Card**; the Supervisor/Phase Agents call
`tasks/send` and poll `tasks/get`.

### 3.1 Agent Card — `GET /.well-known/agent.json`

```json
{
  "name": "PersonaBuilder",
  "description": "Builds evidence-backed personas from discovery research.",
  "url": "https://persona-builder.edt.svc/a2a",
  "version": "1.4.0",
  "provider": { "organization": "EDT Platform" },
  "capabilities": { "streaming": true, "pushNotifications": true },
  "authentication": { "schemes": ["Bearer"] },
  "defaultInputModes": ["application/json"],
  "defaultOutputModes": ["application/json"],
  "skills": [
    {
      "id": "build_personas",
      "name": "Build Personas",
      "description": "Generate 3-6 personas with goals, frustrations, JTBD.",
      "tags": ["discover", "personas"],
      "inputModes": ["application/json"],
      "outputModes": ["application/json"]
    }
  ]
}
```

### 3.2 `tasks/send` (JSON-RPC)

```json
// request → POST https://persona-builder.edt.svc/a2a
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "method": "tasks/send",
  "params": {
    "id": "task-018f9c40",
    "sessionId": "run-018f9b00-1111",
    "message": {
      "role": "user",
      "parts": [{
        "type": "data",
        "data": {
          "skill": "build_personas",
          "run_id": "018f9b00-1111-7000-8000-000000000001",
          "phase_id": "018f9b00-2222-7000-8000-000000000010",
          "inputs": { "insights": ["..."], "segment": "mid-market logistics" },
          "model_tier": "claude-sonnet-5",
          "confidence_threshold": 0.70
        }
      }]
    }
  }
}
```
```json
// response
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "result": {
    "id": "task-018f9c40",
    "status": { "state": "completed" },
    "artifacts": [{
      "name": "personas",
      "parts": [{ "type": "data", "data": {
        "artifact_id": "018f9c40-1234-7000-8000-000000000001",
        "type": "personas", "confidence": 0.86, "count": 4 }}]
    }]
  }
}
```

### 3.3 `tasks/get`

```json
{ "jsonrpc": "2.0", "id": "req-2", "method": "tasks/get",
  "params": { "id": "task-018f9c40" } }
```
Returns the task with `status.state` in `submitted|working|input-required|completed|failed`.
Streaming variant `tasks/sendSubscribe` returns SSE `TaskStatusUpdate` / `TaskArtifactUpdate`
events. A2A tasks also emit platform CloudEvents (`edt.agent.execution.*`).

---

## 4. Streaming (SSE / WebSocket)

### 4.1 SSE — live run progress

`GET /v1/runs/{run_id}/stream` · `Accept: text/event-stream` · Bearer auth ·
`?since=<event_seq>` to resume; server replays from the `event` table then tails Kafka.

```
event: edt.phase.started
id: 4211
data: {"phase":"discover","seq":1,"planned_workers":14}

event: edt.discover.persona.created
id: 4212
data: {"persona_id":"...","name":"Regional Operations Lead","confidence":0.86}

event: edt.approval.requested
id: 4231
data: {"approval_id":"...","gate_id":"gate_1","artifact_type":"insights"}

: keep-alive
```

- Event `id` = monotonic run sequence; clients resume with `Last-Event-ID` header.
- Heartbeat comment every 15s; server closes on `run.completed|failed|cancelled`.
- Payloads are the CloudEvent `data` blocks defined in [`14-event-model.md`](./14-event-model.md).

### 4.2 WebSocket

`wss://api.edt.example.com/v1/runs/{run_id}/ws` — bidirectional. Server→client frames mirror SSE
events; client→server frames allow lightweight control:

```json
// client → server
{ "action": "subscribe", "topics": ["approvals", "artifacts"] }
{ "action": "ping" }
```
```json
// server → client
{ "type": "edt.critic.rejected", "seq": 4240, "data": { "reasons": ["..."] } }
```
Auth via `Sec-WebSocket-Protocol: bearer,<jwt>`. Same tenant scoping and rate limits as REST.

---

## 5. OpenAPI 3.1 (abbreviated, control plane)

Full spec: [`openapi.yaml`](./openapi.yaml). Abbreviated inline:

```yaml
openapi: 3.1.0
info:
  title: EDT Platform Control Plane API
  version: 1.0.0
servers:
  - url: https://api.edt.example.com
security:
  - oidc: [runs:read]
paths:
  /v1/projects/{project_id}/runs:
    post:
      summary: Start a run
      operationId: startRun
      security: [{ oidc: [runs:write] }]
      parameters:
        - { name: project_id, in: path, required: true, schema: { type: string, format: uuid } }
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/StartRunRequest' }
      responses:
        '201':
          description: Run started
          content:
            application/json:
              schema: { $ref: '#/components/schemas/Run' }
        '422': { $ref: '#/components/responses/Error' }
  /v1/runs/{run_id}:
    get:
      summary: Get run
      operationId: getRun
      security: [{ oidc: [runs:read] }]
      parameters:
        - { name: run_id, in: path, required: true, schema: { type: string, format: uuid } }
      responses:
        '200':
          description: OK
          content: { application/json: { schema: { $ref: '#/components/schemas/Run' } } }
        '404': { $ref: '#/components/responses/Error' }
components:
  securitySchemes:
    oidc:
      type: openIdConnect
      openIdConnectUrl: https://id.edt.example.com/realms/edt/.well-known/openid-configuration
  schemas:
    StartRunRequest:
      type: object
      required: [business_problem]
      properties:
        business_problem: { type: string }
        confidence_threshold: { type: number, minimum: 0, maximum: 1, default: 0.7 }
        budget_usd_cap: { type: number }
    Run:
      type: object
      properties:
        run_id: { type: string, format: uuid }
        state:
          type: string
          enum: [created, planning, discover, awaiting_approval, define, ideate,
                 prototype, validate, generating_deliverables, completed, failed, cancelled]
  responses:
    Error:
      description: Error envelope
      content: { application/json: { schema: { $ref: '#/components/schemas/ErrorEnvelope' } } }
```

---

## 6. Cross-references

- Event payloads streamed here → [`14-event-model.md`](./14-event-model.md).
- Entities returned by these endpoints → [`13-data-model.md`](./13-data-model.md).
- Approval gates and loop semantics → [`03-workflow.md`](./03-workflow.md).
- Complete machine-readable contract → [`openapi.yaml`](./openapi.yaml).
