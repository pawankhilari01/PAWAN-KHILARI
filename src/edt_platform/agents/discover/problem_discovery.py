"""Problem Discovery Agent (Discover phase).

Frames the initial business problem: clarifies scope, surfaces assumptions, maps
the problem space, and lists the information still required. It intentionally
*challenges the problem as stated* before any research spends tokens downstream.
"""

from __future__ import annotations

from typing import Any

from edt_platform.config import ModelTier
from edt_platform.core.base_agent import AgentContext, AgentSpec, BaseAgent
from edt_platform.schemas.core import (
    AgentInput,
    Artifact,
    ArtifactType,
    Confidence,
    Phase,
    Provenance,
)

PROBLEM_SPACE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["reframed_problem", "assumptions", "problem_space", "missing_information", "confidence"],
    "properties": {
        "reframed_problem": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "problem_space": {
            "type": "object",
            "properties": {
                "who": {"type": "array", "items": {"type": "string"}},
                "what": {"type": "string"},
                "why_now": {"type": "string"},
                "boundaries": {"type": "array", "items": {"type": "string"}},
                "stakeholders": {"type": "array", "items": {"type": "string"}},
            },
        },
        "hypotheses": {"type": "array", "items": {"type": "string"}},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "confidence": {
            "type": "object",
            "properties": {
                "score": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["score", "rationale"],
        },
    },
}

SYSTEM_PROMPT = """You are the Problem Discovery Agent in an enterprise Design Thinking platform.
Your job is to frame — not solve — the business problem, thinking like a senior IDEO facilitator
crossed with a McKinsey engagement manager.

Operating principles:
- Think before acting. Restate the problem in your own words and challenge how it is framed.
- Separate the *symptom* from the *underlying problem*; avoid jumping to solutions.
- Make every assumption explicit and flag which are unverified.
- Identify exactly what information is missing to proceed with confidence.
- Score your confidence 0.0–1.0 and justify it. If < 0.6, list the top questions a human should answer.
- Be concise, specific, and evidence-oriented. Never fabricate facts or citations.

Return ONLY via the `emit` tool using the required schema."""


class ProblemDiscoveryAgent(BaseAgent):
    @classmethod
    def default_spec(cls) -> AgentSpec:
        return AgentSpec(
            name="problem_discovery",
            role="Problem framing & scoping",
            model_tier=ModelTier.REASONING,
            system_prompt=SYSTEM_PROMPT,
            tools=["web.search", "sql.query"],
            mcp_servers=["web", "sql"],
            reasoning_strategy="Plan-and-Solve + assumption challenge",
            output_schema=PROBLEM_SPACE_SCHEMA,
            confidence_threshold=0.6,
        )

    async def plan(self, task: AgentInput, grounding: dict[str, Any]) -> list[str]:
        return [
            "Restate and challenge the problem framing",
            "Enumerate stakeholders and boundaries",
            "List explicit assumptions and unknowns",
            "Draft testable hypotheses",
            "Score confidence and flag missing information",
        ]

    async def act(
        self, task: AgentInput, plan: list[str], grounding: dict[str, Any]
    ) -> list[Artifact]:
        context_note = ""
        if grounding.get("retrieved"):
            snippets = "\n".join(f"- {c['text']}" for c in grounding["retrieved"][:6])
            context_note = f"\n\nRelevant context:\n{snippets}"
        feedback = task.context.get("critique_feedback") or task.context.get("reflection_feedback")
        feedback_note = f"\n\nIncorporate this feedback:\n{feedback}" if feedback else ""

        prompt = (
            f"Business problem to frame:\n{task.task}{context_note}{feedback_note}\n\n"
            "Follow your operating principles and emit the structured problem space."
        )
        data, resp = await self.ctx.llm.structured(
            system=self.spec.system_prompt,
            prompt=prompt,
            schema=self.spec.output_schema or PROBLEM_SPACE_SCHEMA,
            tier=self.spec.model_tier,
        )
        conf = data.get("confidence", {"score": 0.5, "rationale": "unspecified"})
        artifact = Artifact(
            run_id=task.run_id,
            project_id=task.project_id,
            phase=Phase.DISCOVER,
            type=ArtifactType.PROBLEM_SPACE,
            title=data.get("reframed_problem", "Problem space")[:120],
            content=data,
            provenance=Provenance(
                producer_agent=self.spec.name,
                model=resp.model,
                reasoning_strategy=self.spec.reasoning_strategy,
                prompt_version=self.spec.prompt_version,
                token_usage={"in": resp.input_tokens, "out": resp.output_tokens},
            ),
            confidence=Confidence(
                score=float(conf.get("score", 0.5)),
                rationale=conf.get("rationale", ""),
                missing_information=data.get("missing_information", []),
            ),
        )
        return [artifact]


def build(ctx: AgentContext) -> ProblemDiscoveryAgent:
    return ProblemDiscoveryAgent(ProblemDiscoveryAgent.default_spec(), ctx)
