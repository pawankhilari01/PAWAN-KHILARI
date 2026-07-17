"""FastAPI control-plane + live dashboard (see docs/12-api-specification.md).

Beyond the REST control plane, this serves a single-page **dashboard** at ``/`` that
visualizes the entire Design Thinking lifecycle and executes it to create artifacts:

  * Start a run from a business problem (choose depth + optional approval gates).
  * Watch the five phases execute live via Server-Sent Events (real CloudEvents).
  * See artifacts appear per phase and open any one to read its full content.
  * Approve/reject human-approval gates interactively.

Runs execute as background asyncio tasks on the same event loop, so progress streams
while the run proceeds. Demo mode (no ``EDT_LLM_ANTHROPIC_API_KEY``) uses the offline
fake client, so the dashboard is fully usable with zero credentials/infrastructure.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from edt_platform.agents.crosscutting.critic import CriticAgent
from edt_platform.agents.registry import build_registry
from edt_platform.config import get_settings
from edt_platform.core.base_agent import AgentContext
from edt_platform.core.llm import LLMClient
from edt_platform.eventing.publisher import CloudEvent, EventPublisher
from edt_platform.memory.memory_agent import MemoryAgent
from edt_platform.orchestration.supervisor import RunState, Supervisor
from edt_platform.schemas.core import ApprovalRequest, ApprovalStatus, Phase
from edt_platform.security.guardrails import GuardrailEngine

# Respect the configured log level (drops per-span debug noise by default).
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, get_settings().obs.log_level.upper(), logging.INFO)
    )
)

app = FastAPI(title="EDT Platform Control Plane", version="0.1.0")

_DASHBOARD = Path(__file__).parent / "dashboard.html"

# Blended $/1M-token estimate for the live cost readout in demo mode.
_BLENDED_RATE = 6.0


def demo_mode() -> bool:
    return not os.environ.get("EDT_LLM_ANTHROPIC_API_KEY")


@dataclass
class RunSession:
    """Server-side state for one dashboard run."""

    run_id: str
    events: EventPublisher
    problem: str = ""
    depth: str = "standard"
    created_at: float = 0.0
    state: RunState | None = None
    task: asyncio.Task | None = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    pending_approvals: dict[str, asyncio.Future] = field(default_factory=dict)
    decisions: dict[str, str] = field(default_factory=dict)
    finished: bool = False


_SESSIONS: dict[str, RunSession] = {}


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class StartRunRequest(BaseModel):
    problem: str = Field(min_length=8)
    depth: str = "standard"
    require_approval: bool = False


class ApprovalDecision(BaseModel):
    phase: str
    decision: str = Field(description="approved | rejected")


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #
def _build_llm() -> LLMClient:
    if demo_mode():
        from edt_platform.testing import FakeAnthropicClient

        return LLMClient(client=FakeAnthropicClient())
    return LLMClient()


def _make_approval_handler(session: RunSession):
    async def handler(req: ApprovalRequest) -> ApprovalStatus:
        phase = req.phase.value
        # If the UI already decided (arrived before the gate opened), honor it.
        if phase in session.decisions:
            decided = session.decisions.pop(phase)
        else:
            loop = asyncio.get_event_loop()
            fut: asyncio.Future = loop.create_future()
            session.pending_approvals[phase] = fut
            decided = await fut
            session.pending_approvals.pop(phase, None)
        return ApprovalStatus.APPROVED if decided == "approved" else ApprovalStatus.REJECTED

    return handler


async def _run(session: RunSession, req: StartRunRequest) -> None:
    llm = _build_llm()
    ctx = AgentContext(
        llm=llm,
        memory=MemoryAgent(),
        events=session.events,
        critic=CriticAgent(llm),
        guardrails=GuardrailEngine(),
    )
    supervisor = Supervisor(
        ctx,
        build_registry(),
        approval_handler=_make_approval_handler(session) if req.require_approval else None,
    )
    try:
        await supervisor.run(
            problem=req.problem,
            depth=req.depth,
            require_approval=req.require_approval,
            on_state=lambda s: setattr(session, "state", s),
        )
    finally:
        session.finished = True
        # Nudge any open SSE streams to close.
        for q in session.subscribers:
            q.put_nowait(None)


# --------------------------------------------------------------------------- #
# Routes — dashboard
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    if _DASHBOARD.exists():
        return _DASHBOARD.read_text(encoding="utf-8")
    return "<h1>EDT Platform</h1><p>Dashboard asset missing.</p>"


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "mode": "demo" if demo_mode() else "live"}


# --------------------------------------------------------------------------- #
# Routes — runs
# --------------------------------------------------------------------------- #
@app.post("/v1/runs", status_code=202)
async def start_run(req: StartRunRequest) -> dict[str, Any]:
    run_id = str(uuid4())
    session = RunSession(
        run_id=run_id,
        events=EventPublisher(),
        problem=req.problem,
        depth=req.depth,
        created_at=time.time(),
    )
    _SESSIONS[run_id] = session
    session.task = asyncio.create_task(_run(session, req))
    return {"run_id": run_id, "status": "running", "mode": "demo" if demo_mode() else "live"}


@app.get("/v1/runs")
async def list_runs() -> list[dict[str, Any]]:
    """Run history, newest first — powers the dashboard's history sidebar."""
    rows = []
    for s in _SESSIONS.values():
        summ = _summary(s)
        rows.append(
            {
                "run_id": s.run_id,
                "problem": s.problem,
                "depth": s.depth,
                "created_at": s.created_at,
                "status": summ["status"],
                "artifacts": summ["artifacts"],
                "est_cost_usd": summ["est_cost_usd"],
                "finished": s.finished,
            }
        )
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


@app.get("/v1/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    session = _SESSIONS.get(run_id)
    if not session:
        raise HTTPException(status_code=404, detail="run not found")
    return _summary(session)


@app.get("/v1/runs/{run_id}/artifacts")
async def list_artifacts(run_id: str, phase: Phase | None = None) -> list[dict[str, Any]]:
    session = _SESSIONS.get(run_id)
    if not session or not session.state:
        return []
    arts = [a for a in session.state.artifacts if phase is None or a.phase == phase]
    return [
        {
            "id": str(a.id),
            "type": a.type.value,
            "phase": a.phase.value,
            "title": a.title,
            "confidence": round(a.confidence.score, 2),
            "producer": a.provenance.producer_agent,
            "model": a.provenance.model,
            "content": a.content,
        }
        for a in arts
    ]


@app.get("/v1/runs/{run_id}/events")
async def stream_events(run_id: str) -> EventSourceResponse:
    session = _SESSIONS.get(run_id)
    if not session:
        raise HTTPException(status_code=404, detail="run not found")

    queue: asyncio.Queue = asyncio.Queue()
    # Replay events already buffered, then live-subscribe.
    for evt in session.events.buffer:
        queue.put_nowait(evt)
    unsubscribe = session.events.subscribe(lambda e: queue.put_nowait(e))
    session.subscribers.append(queue)

    async def gen():
        try:
            while True:
                evt = await queue.get()
                if evt is None:  # run finished sentinel
                    yield {"event": "done", "data": _json_summary(session)}
                    break
                if isinstance(evt, CloudEvent):
                    yield {"event": "cloudevent", "data": _json_event(evt)}
        finally:
            unsubscribe()
            if queue in session.subscribers:
                session.subscribers.remove(queue)

    return EventSourceResponse(gen())


@app.post("/v1/runs/{run_id}/approvals")
async def decide_approval(run_id: str, decision: ApprovalDecision) -> dict[str, Any]:
    session = _SESSIONS.get(run_id)
    if not session:
        raise HTTPException(status_code=404, detail="run not found")
    fut = session.pending_approvals.get(decision.phase)
    if fut and not fut.done():
        fut.set_result(decision.decision)
    else:
        # Gate not open yet — stash it so the handler honors it when it opens.
        session.decisions[decision.phase] = decision.decision
    return {"ok": True, "phase": decision.phase, "decision": decision.decision}


@app.get("/v1/runs/{run_id}/export", response_class=PlainTextResponse)
async def export_run(run_id: str) -> PlainTextResponse:
    """Export the whole run as a single Markdown design-thinking report."""
    session = _SESSIONS.get(run_id)
    if not session:
        raise HTTPException(status_code=404, detail="run not found")
    md = _render_markdown(session)
    filename = f"edt-run-{run_id[:8]}.md"
    return PlainTextResponse(
        md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
_PHASE_ORDER = [Phase.DISCOVER, Phase.DEFINE, Phase.IDEATE, Phase.PROTOTYPE, Phase.VALIDATE]


def _render_markdown(session: RunSession) -> str:
    """Assemble every artifact into a readable Markdown report, grouped by phase."""
    summ = _summary(session)
    lines: list[str] = [
        "# Design Thinking Run — Report",
        "",
        f"**Problem:** {session.problem}",
        "",
        f"- Run id: `{session.run_id}`",
        f"- Status: **{summ['status']}**  ·  Depth: {session.depth}  ·  Loops: {summ['loop_count']}",
        f"- Artifacts: {summ['artifacts']}  ·  Tokens: {summ['tokens_in'] + summ['tokens_out']:,}"
        f"  ·  Est. cost: ${summ['est_cost_usd']}",
        f"- Mode: {summ['mode']}",
        "",
        "---",
        "",
    ]
    arts = session.state.artifacts if session.state else []
    for phase in _PHASE_ORDER:
        group = [a for a in arts if a.phase == phase]
        if not group:
            continue
        lines.append(f"## {phase.value.title()}  ({len(group)} artifacts)")
        lines.append("")
        for a in group:
            lines.append(f"### [{a.type.value}] {a.title}")
            lines.append(
                f"*Producer:* `{a.provenance.producer_agent}`  ·  "
                f"*Model:* {a.provenance.model}  ·  "
                f"*Confidence:* {a.confidence.score:.2f}"
            )
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(a.content, indent=2, default=str))
            lines.append("```")
            lines.append("")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_Generated by the Enterprise Design Thinking AI Platform (EDT Platform)._")
    return "\n".join(lines)

def _summary(session: RunSession) -> dict[str, Any]:
    st = session.state
    tokens_in = tokens_out = 0
    per_phase: dict[str, int] = {}
    if st:
        for a in st.artifacts:
            tokens_in += a.provenance.token_usage.get("in", 0)
            tokens_out += a.provenance.token_usage.get("out", 0)
            per_phase[a.phase.value] = per_phase.get(a.phase.value, 0) + 1
    est_cost = (tokens_in + tokens_out) * _BLENDED_RATE / 1_000_000
    return {
        "run_id": session.run_id,
        "problem": session.problem,
        "depth": session.depth,
        "created_at": session.created_at,
        "status": st.status.value if st else "starting",
        "finished": session.finished,
        "artifacts": len(st.artifacts) if st else 0,
        "artifacts_by_phase": per_phase,
        "loop_count": st.loop_count if st else 0,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "est_cost_usd": round(est_cost, 4),
        "pending_approvals": list(session.pending_approvals.keys()),
        "log": st.log if st else [],
        "mode": "demo" if demo_mode() else "live",
    }


def _json_summary(session: RunSession) -> str:
    return json.dumps(_summary(session))


def _json_event(evt: CloudEvent) -> str:
    return json.dumps({"type": evt.type, "subject": evt.subject, "data": evt.data})


# Convenience alias so `uvicorn edt_platform.api.app:app` and imports both work.
control_plane = app
