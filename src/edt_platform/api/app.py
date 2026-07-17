"""FastAPI control-plane (see docs/12-api-specification.md).

Exposes the platform to the Web console, SDKs, and CI: create/inspect runs, list
artifacts, act on approval gates, and stream live progress via SSE. Worker agents
are separate A2A services; this is the orchestration entry point.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from edt_platform.agents.crosscutting.critic import CriticAgent
from edt_platform.agents.registry import build_registry
from edt_platform.core.base_agent import AgentContext
from edt_platform.core.llm import LLMClient
from edt_platform.eventing.publisher import EventPublisher
from edt_platform.memory.memory_agent import MemoryAgent
from edt_platform.orchestration.supervisor import RunState, Supervisor
from edt_platform.schemas.core import Phase

app = FastAPI(title="EDT Platform Control Plane", version="0.1.0")

# In-memory run store for the reference server (Postgres in production).
_RUNS: dict[str, RunState] = {}


class StartRunRequest(BaseModel):
    problem: str = Field(min_length=8)
    project_id: UUID | None = None
    phases: list[Phase] | None = None
    depth: str = "standard"
    require_approval: bool = False


class RunSummary(BaseModel):
    run_id: str
    status: str
    artifacts: int
    cost_usd: float
    loop_count: int


def _build_context(events: EventPublisher) -> AgentContext:
    llm = LLMClient()
    return AgentContext(
        llm=llm,
        memory=MemoryAgent(),
        events=events,
        critic=CriticAgent(llm),
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/runs", response_model=RunSummary, status_code=202)
async def start_run(req: StartRunRequest) -> RunSummary:
    events = EventPublisher()
    ctx = _build_context(events)
    supervisor = Supervisor(ctx, build_registry())
    state = await supervisor.run(
        problem=req.problem,
        project_id=req.project_id,
        phases=req.phases,
        depth=req.depth,
        require_approval=req.require_approval,
    )
    _RUNS[str(state.run_id)] = state
    return _summary(state)


@app.get("/v1/runs/{run_id}", response_model=RunSummary)
async def get_run(run_id: str) -> RunSummary:
    state = _RUNS.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="run not found")
    return _summary(state)


@app.get("/v1/runs/{run_id}/artifacts")
async def list_artifacts(run_id: str, phase: Phase | None = None) -> list[dict[str, Any]]:
    state = _RUNS.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="run not found")
    arts = [a for a in state.artifacts if phase is None or a.phase == phase]
    return [
        {
            "id": str(a.id),
            "type": a.type.value,
            "phase": a.phase.value,
            "title": a.title,
            "confidence": a.confidence.score,
            "producer": a.provenance.producer_agent,
        }
        for a in arts
    ]


@app.get("/v1/runs/{run_id}/events")
async def stream_events(run_id: str) -> EventSourceResponse:
    """Live progress via SSE (reference server replays buffered events)."""

    async def gen():
        state = _RUNS.get(run_id)
        yield {"event": "status", "data": state.status.value if state else "unknown"}
        await asyncio.sleep(0)

    return EventSourceResponse(gen())


def _summary(state: RunState) -> RunSummary:
    return RunSummary(
        run_id=str(state.run_id),
        status=state.status.value,
        artifacts=len(state.artifacts),
        cost_usd=round(state.cost_usd, 4),
        loop_count=state.loop_count,
    )
