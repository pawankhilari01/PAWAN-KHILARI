"""Durable Run orchestration with Temporal (see docs/15-deployment-architecture.md).

In production the Supervisor's logic runs as a Temporal Workflow so a Run survives
process restarts, phases become durable activities with automatic retries, and the
human-approval gate is a first-class Temporal *signal* (the workflow blocks for days
until an approver acts, without holding any thread).

This module is a reference skeleton — importing ``temporalio`` is optional at test
time. The real activities call worker agent services over A2A.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

try:  # pragma: no cover - optional dependency at test time
    from temporalio import activity, workflow
    from temporalio.common import RetryPolicy

    _TEMPORAL = True
except Exception:  # noqa: BLE001
    _TEMPORAL = False


@dataclass
class RunRequest:
    problem: str
    project_id: str
    depth: str = "standard"
    require_approval: bool = True


if _TEMPORAL:  # pragma: no cover

    @activity.defn
    async def run_phase_activity(run_id: str, phase: str, upstream_ids: list[str]) -> dict:
        """Durable activity: execute one phase by delegating to worker A2A services."""
        # Wire the Supervisor._run_phase equivalent against remote agents here.
        return {"run_id": run_id, "phase": phase, "artifacts": []}

    @workflow.defn
    class DesignThinkingRun:
        def __init__(self) -> None:
            self._approvals: dict[str, str] = {}

        @workflow.signal
        def approve(self, phase: str, decision: str) -> None:
            self._approvals[phase] = decision

        @workflow.query
        def approvals(self) -> dict[str, str]:
            return self._approvals

        @workflow.run
        async def run(self, req: RunRequest) -> dict:
            phases = ["discover", "define", "ideate", "prototype", "validate"]
            produced: list[str] = []
            retry = RetryPolicy(maximum_attempts=3, backoff_coefficient=2.0)
            for phase in phases:
                result = await workflow.execute_activity(
                    run_phase_activity,
                    args=[workflow.info().workflow_id, phase, produced],
                    start_to_close_timeout=timedelta(minutes=30),
                    retry_policy=retry,
                )
                produced.extend(result.get("artifacts", []))
                if req.require_approval:
                    await workflow.wait_condition(lambda p=phase: p in self._approvals)
                    if self._approvals[phase] != "approved":
                        return {"status": "cancelled", "phase": phase}
            return {"status": "completed", "artifacts": produced}
