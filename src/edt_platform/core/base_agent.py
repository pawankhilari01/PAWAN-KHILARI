"""BaseAgent — the universal agent contract for the EDT Platform.

Every one of the ~95 agents (phase agents, workers, cross-cutting services) is an
independently deployable subclass of :class:`BaseAgent`. The base class encodes the
platform's *agentic loop* so individual agents only implement the parts that differ:

    plan()  ->  act()  ->  reflect()  ->  critique()  ->  self_correct()  ->  emit()

Cross-cutting concerns (memory read/write, RAG, tool calling via MCP, guardrails,
confidence scoring, retries, escalation, tracing, cost accounting, event emission)
are handled here so they are consistent and governed everywhere.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from edt_platform.config import ModelTier, get_settings
from edt_platform.core.llm import LLMClient
from edt_platform.observability.tracing import traced
from edt_platform.schemas.core import (
    AgentInput,
    AgentOutcome,
    AgentResult,
    Artifact,
    Confidence,
)


@dataclass
class AgentContext:
    """Runtime collaborators injected into an agent (ports & adapters).

    Kept as a dataclass of protocols/objects so agents are testable with fakes and
    every dependency is explicit. In production these are wired by the DI container.
    """

    llm: LLMClient
    memory: Any | None = None          # MemoryAgent client (working/episodic/semantic/graph)
    retriever: Any | None = None       # RAG retriever
    tools: Any | None = None           # ToolRegistry / MCP tool router
    events: Any | None = None          # EventPublisher (CloudEvents -> Kafka)
    critic: Any | None = None          # shared Critic service (optional external)
    guardrails: Any | None = None      # input/output guardrail engine
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentSpec:
    """Declarative configuration for an agent instance (from YAML/registry)."""

    name: str
    role: str
    model_tier: ModelTier = ModelTier.DEFAULT
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    memory_scopes: list[str] = field(default_factory=lambda: ["run", "project"])
    confidence_threshold: float = 0.72
    max_retries: int = 3
    reasoning_strategy: str = "ReAct+Reflexion"
    output_schema: dict[str, Any] | None = None
    escalation_rules: list[str] = field(default_factory=list)
    prompt_version: str = "v1"


class BaseAgent(abc.ABC):
    """Abstract base implementing the shared agentic loop."""

    spec: AgentSpec

    def __init__(self, spec: AgentSpec, ctx: AgentContext) -> None:
        self.spec = spec
        self.ctx = ctx
        self._settings = get_settings()

    # ----- lifecycle the framework calls ---------------------------------- #
    @traced("agent.run")
    async def run(self, task: AgentInput) -> AgentResult:
        """The governed agentic loop. Subclasses rarely override this."""
        await self._emit_event("agent.started", task)

        # 1) Guardrail the input (PII, injection, policy).
        if self.ctx.guardrails:
            await self.ctx.guardrails.check_input(self.spec.name, task)

        # 2) Retrieve relevant memory + knowledge (RAG) to ground the work.
        grounding = await self._gather_context(task)

        # 3) Plan -> Act -> Reflect -> Critique -> Self-correct loop.
        result: AgentResult | None = None
        for attempt in range(self.spec.max_retries + 1):
            plan = await self.plan(task, grounding)
            artifacts = await self.act(task, plan, grounding)
            confidence = await self.score_confidence(task, artifacts)
            reflection = await self.reflect(task, artifacts, confidence)
            critique = await self.critique(task, artifacts)

            needs_fix = (
                confidence.score < self.spec.confidence_threshold
                or (critique and critique.strip().upper().startswith("REJECT"))
            )
            if needs_fix and attempt < self.spec.max_retries:
                artifacts = await self.self_correct(task, artifacts, reflection, critique)
                confidence = await self.score_confidence(task, artifacts)

            outcome = self._decide_outcome(confidence, attempt)
            result = AgentResult(
                agent=self.spec.name,
                outcome=outcome,
                artifacts=artifacts,
                confidence=confidence,
                reflection=reflection,
                critique=critique,
            )
            if outcome != AgentOutcome.RETRY:
                break

        assert result is not None
        # 4) Guardrail + persist outputs, write memory, emit events.
        if self.ctx.guardrails:
            for art in result.artifacts:
                await self.ctx.guardrails.check_output(self.spec.name, art)
        await self._persist(result)
        await self._emit_event("agent.completed", task, extra={"outcome": result.outcome})
        return result

    # ----- steps subclasses implement ------------------------------------- #
    @abc.abstractmethod
    async def plan(self, task: AgentInput, grounding: dict[str, Any]) -> list[str]:
        """Return an ordered plan (list of steps)."""

    @abc.abstractmethod
    async def act(
        self, task: AgentInput, plan: list[str], grounding: dict[str, Any]
    ) -> list[Artifact]:
        """Execute the plan (LLM + tool calls) and produce artifacts."""

    # ----- steps with sensible defaults (override as needed) -------------- #
    async def reflect(
        self, task: AgentInput, artifacts: list[Artifact], confidence: Confidence
    ) -> str:
        """Reflexion-style self-review of the outputs (what's weak/missing)."""
        if not artifacts:
            return "No artifacts produced."
        prompt = (
            "Reflect on the artifact(s) you just produced. Identify weaknesses, "
            "unsupported claims, and missing information. Be specific and terse.\n\n"
            f"Task: {task.task}\nConfidence: {confidence.score:.2f} — {confidence.rationale}"
        )
        resp = await self.ctx.llm.complete(
            system=self.spec.system_prompt or f"You are {self.spec.name}.",
            messages=[{"role": "user", "content": prompt}],
            tier=ModelTier.DEFAULT,
        )
        return resp.text

    async def critique(self, task: AgentInput, artifacts: list[Artifact]) -> str:
        """Delegate to the shared Critic service if present; else self-critique."""
        if self.ctx.critic:
            return await self.ctx.critic.critique(self.spec.name, task, artifacts)
        return "APPROVE (no external critic wired)."

    async def self_correct(
        self,
        task: AgentInput,
        artifacts: list[Artifact],
        reflection: str,
        critique: str,
    ) -> list[Artifact]:
        """Default self-correction re-runs :meth:`act` with feedback appended."""
        augmented = task.model_copy(
            update={
                "context": {
                    **task.context,
                    "reflection_feedback": reflection,
                    "critique_feedback": critique,
                }
            }
        )
        grounding = await self._gather_context(augmented)
        plan = await self.plan(augmented, grounding)
        return await self.act(augmented, plan, grounding)

    async def score_confidence(
        self, task: AgentInput, artifacts: list[Artifact]
    ) -> Confidence:
        """Default: reuse the confidence the agent attached to its primary artifact."""
        if artifacts and artifacts[0].confidence:
            return artifacts[0].confidence
        return Confidence(score=0.5, rationale="No explicit confidence produced.")

    # ----- shared helpers -------------------------------------------------- #
    async def _gather_context(self, task: AgentInput) -> dict[str, Any]:
        grounding: dict[str, Any] = {"memories": [], "retrieved": []}
        if self.ctx.memory:
            grounding["memories"] = await self.ctx.memory.retrieve(
                query=task.task, scopes=self.spec.memory_scopes, run_id=task.run_id
            )
        if self.ctx.retriever:
            grounding["retrieved"] = await self.ctx.retriever.retrieve(
                query=task.task, phase=task.phase
            )
        return grounding

    def _decide_outcome(self, confidence: Confidence, attempt: int) -> AgentOutcome:
        if confidence.score >= self.spec.confidence_threshold:
            return AgentOutcome.SUCCESS
        if attempt >= self.spec.max_retries:
            # Exhausted retries below threshold -> escalate to a human.
            return AgentOutcome.NEEDS_HUMAN
        return AgentOutcome.RETRY

    async def _persist(self, result: AgentResult) -> None:
        if self.ctx.memory:
            for art in result.artifacts:
                await self.ctx.memory.write_episodic(art)
                await self.ctx.memory.write_semantic(art)

    async def _emit_event(
        self, kind: str, task: AgentInput, extra: dict[str, Any] | None = None
    ) -> None:
        if not self.ctx.events:
            return
        await self.ctx.events.publish(
            event_type=f"edt.{task.phase.value}.{self.spec.name}.{kind}",
            subject=str(task.run_id),
            data={"agent": self.spec.name, "correlation_id": task.correlation_id, **(extra or {})},
        )
