"""Supervisor Agent — the top-level orchestrator.

Owns a Run end-to-end: asks the Workflow Planner for a plan, drives each phase
(parallel worker fan-out -> synthesizer fan-in), enforces human-approval gates,
detects when feedback loops must fire (e.g. Validate's Go/No-Go returns
`conditional_go` -> loop back to Ideate), tracks budget with the Cost agent, and
emits lifecycle events.

The reference implementation uses a registry of agent factories so it can run with
in-process fakes. In production the Supervisor delegates to worker services over
A2A and is itself hosted as a durable Temporal workflow (see temporal_workflow.py).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from edt_platform.core.base_agent import AgentContext, BaseAgent
from edt_platform.orchestration.workflow_planner import PhasePlan, RunPlan, WorkflowPlanner
from edt_platform.schemas.core import (
    AgentInput,
    AgentOutcome,
    AgentResult,
    ApprovalRequest,
    ApprovalStatus,
    Artifact,
    Phase,
    RunStatus,
)

AgentFactory = Callable[[AgentContext], BaseAgent]
ApprovalHandler = Callable[[ApprovalRequest], Awaitable[ApprovalStatus]]


@dataclass
class RunState:
    run_id: UUID
    project_id: UUID
    problem: str
    status: RunStatus = RunStatus.CREATED
    artifacts: list[Artifact] = field(default_factory=list)
    cost_usd: float = 0.0
    loop_count: int = 0
    log: list[str] = field(default_factory=list)


class Supervisor:
    def __init__(
        self,
        ctx: AgentContext,
        registry: dict[str, AgentFactory],
        planner: WorkflowPlanner | None = None,
        approval_handler: ApprovalHandler | None = None,
        max_loops: int = 2,
    ) -> None:
        self.ctx = ctx
        self.registry = registry
        self.planner = planner or WorkflowPlanner()
        self.approval_handler = approval_handler
        self.max_loops = max_loops

    async def run(
        self,
        *,
        problem: str,
        project_id: UUID | None = None,
        phases: list[Phase] | None = None,
        depth: str = "standard",
        require_approval: bool = True,
    ) -> RunState:
        state = RunState(run_id=uuid4(), project_id=project_id or uuid4(), problem=problem)
        state.status = RunStatus.PLANNING
        await self._event(state, "run.created", {"problem": problem})

        plan: RunPlan = self.planner.plan(
            problem=problem, phases=phases, depth=depth, require_approval=require_approval
        )
        state.status = RunStatus.RUNNING

        for phase_plan in plan.phases:
            await self._run_phase(state, phase_plan)
            if phase_plan.requires_approval:
                approved = await self._approval_gate(state, phase_plan.phase)
                if not approved:
                    state.status = RunStatus.CANCELLED
                    state.log.append(f"Run halted: {phase_plan.phase.value} not approved.")
                    return state
            # Feedback loop: Validate may send us back to Ideate.
            if (
                phase_plan.phase is Phase.VALIDATE
                and self._needs_ideation_loop(state)
                and state.loop_count < self.max_loops
            ):
                state.loop_count += 1
                state.log.append("Validation triggered an Ideate loop; re-ideating.")
                await self._run_phase(state, self._phase_plan(plan, Phase.IDEATE))
                await self._run_phase(state, self._phase_plan(plan, Phase.PROTOTYPE))
                await self._run_phase(state, phase_plan)

        state.status = RunStatus.GENERATING_DELIVERABLES
        await self._event(state, "run.deliverables.started", {})
        state.status = RunStatus.COMPLETED
        await self._event(state, "run.completed", {"artifacts": len(state.artifacts)})
        return state

    # ----- phase execution ------------------------------------------------- #
    async def _run_phase(self, state: RunState, pp: PhasePlan) -> None:
        await self._event(state, f"{pp.phase.value}.phase.started", {})
        upstream = list(state.artifacts)

        # 1) Parallel worker fan-out.
        tasks = [
            self._run_worker(state, pp.phase, name, upstream)
            for name in pp.parallel_workers
            if name in self.registry
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, AgentResult):
                self._absorb(state, r)

        # 2) Synthesizer fan-in over everything produced this phase.
        if pp.synthesizer in self.registry:
            synth = await self._run_worker(
                state, pp.phase, pp.synthesizer, list(state.artifacts)
            )
            self._absorb(state, synth)

        await self._event(state, f"{pp.phase.value}.phase.completed", {})

    async def _run_worker(
        self, state: RunState, phase: Phase, name: str, upstream: list[Artifact]
    ) -> AgentResult:
        agent = self.registry[name](self.ctx)
        task = AgentInput(
            run_id=state.run_id,
            project_id=state.project_id,
            phase=phase,
            task=state.problem,
            upstream_artifacts=upstream,
        )
        try:
            return await agent.run(task)
        except Exception as exc:  # noqa: BLE001
            state.log.append(f"{name} failed: {exc}")
            return AgentResult(agent=name, outcome=AgentOutcome.FAILED)

    def _absorb(self, state: RunState, result: AgentResult) -> None:
        state.artifacts.extend(result.artifacts)
        state.cost_usd += result.cost_usd
        if result.outcome == AgentOutcome.NEEDS_HUMAN:
            state.log.append(f"{result.agent} escalated: {result.escalation_reason}")

    # ----- gates & loops --------------------------------------------------- #
    async def _approval_gate(self, state: RunState, phase: Phase) -> bool:
        req = ApprovalRequest(
            run_id=state.run_id,
            phase=phase,
            summary=f"Approve {phase.value} outputs ({len(state.artifacts)} artifacts).",
            artifacts=[a.id for a in state.artifacts if a.phase == phase],
        )
        prev = state.status
        state.status = RunStatus.AWAITING_APPROVAL
        await self._event(state, "approval.requested", {"phase": phase.value})
        decision = (
            await self.approval_handler(req)
            if self.approval_handler
            else ApprovalStatus.APPROVED  # auto-approve when no human handler wired
        )
        state.status = prev
        await self._event(state, "approval.decided", {"phase": phase.value, "decision": decision.value})
        return decision == ApprovalStatus.APPROVED

    def _needs_ideation_loop(self, state: RunState) -> bool:
        for a in reversed(state.artifacts):
            if a.type.value == "go_no_go":
                return str(a.content.get("decision")) == "conditional_go"
        return False

    @staticmethod
    def _phase_plan(plan: RunPlan, phase: Phase) -> PhasePlan:
        return next(p for p in plan.phases if p.phase == phase)

    async def _event(self, state: RunState, kind: str, data: dict) -> None:
        if self.ctx.events:
            await self.ctx.events.publish(
                event_type=f"edt.{kind}", subject=str(state.run_id), data=data
            )
