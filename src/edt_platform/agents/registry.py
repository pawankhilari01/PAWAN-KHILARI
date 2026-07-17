"""Agent registry — maps agent names to factory functions.

The Supervisor uses this to instantiate workers by name. Only a subset of the ~95
agents ship as full reference implementations (Problem Discovery, Persona Builder);
the rest are declared here with a generic, prompt-driven :class:`GenericWorkerAgent`
so the whole plan is executable today and specialized behavior can be filled in
incrementally without changing the orchestrator.
"""

from __future__ import annotations

from typing import Any

from edt_platform.agents.discover import persona_builder, problem_discovery
from edt_platform.core.base_agent import AgentContext, AgentSpec, BaseAgent
from edt_platform.orchestration.workflow_planner import PHASE_WORKERS
from edt_platform.schemas.core import (
    AgentInput,
    Artifact,
    ArtifactType,
    Confidence,
    Phase,
    Provenance,
)

_GENERIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["title", "findings", "confidence"],
    "properties": {
        "title": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}},
        "details": {"type": "object"},
        "confidence": {
            "type": "object",
            "properties": {"score": {"type": "number"}, "rationale": {"type": "string"}},
            "required": ["score", "rationale"],
        },
    },
}


class GenericWorkerAgent(BaseAgent):
    """Prompt-driven worker used until a specialized implementation is provided."""

    async def plan(self, task: AgentInput, grounding: dict[str, Any]) -> list[str]:
        return [f"Apply the {self.spec.role} technique", "Ground in upstream artifacts", "Emit findings"]

    async def act(
        self, task: AgentInput, plan: list[str], grounding: dict[str, Any]
    ) -> list[Artifact]:
        upstream = "\n".join(f"- {a.type.value}: {a.title}" for a in task.upstream_artifacts[:15])
        prompt = (
            f"You are the {self.spec.name} ({self.spec.role}).\n"
            f"Business problem: {task.task}\n\nUpstream artifacts:\n{upstream or '(none)'}\n\n"
            "Produce your specialized contribution. Emit via `emit`."
        )
        data, resp = await self.ctx.llm.structured(
            system=self.spec.system_prompt or f"You are {self.spec.name}, a {self.spec.role} agent.",
            prompt=prompt,
            schema=_GENERIC_SCHEMA,
            tier=self.spec.model_tier,
        )
        conf = data.get("confidence", {"score": 0.6, "rationale": ""})
        return [
            Artifact(
                run_id=task.run_id,
                project_id=task.project_id,
                phase=task.phase,
                type=ArtifactType.INSIGHT,  # generic bucket; specialized agents set precise types
                title=data.get("title", self.spec.name),
                content=data,
                provenance=Provenance(
                    producer_agent=self.spec.name,
                    model=resp.model,
                    inputs_ref=[a.id for a in task.upstream_artifacts],
                    token_usage={"in": resp.input_tokens, "out": resp.output_tokens},
                ),
                confidence=Confidence(
                    score=float(conf.get("score", 0.6)), rationale=conf.get("rationale", "")
                ),
            )
        ]


def _generic_factory(name: str, phase: Phase):
    def factory(ctx: AgentContext) -> BaseAgent:
        spec = AgentSpec(name=name, role=name.replace("_", " ").title())
        return GenericWorkerAgent(spec, ctx)

    return factory


def build_registry():
    """Return {agent_name: factory}. Specialized agents override generics."""
    registry: dict[str, Any] = {}
    for phase, names in PHASE_WORKERS.items():
        for name in names:
            registry[name] = _generic_factory(name, phase)
    # Specialized reference implementations:
    registry["problem_discovery"] = problem_discovery.build
    registry["persona_builder"] = persona_builder.build
    return registry
