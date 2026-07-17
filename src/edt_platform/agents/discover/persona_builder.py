"""Persona Builder (Discover phase).

Synthesizes evidence-grounded personas from research artifacts (VoC, support
tickets, interviews, market data). Personas are refined iteratively as later
phases surface new evidence (Discover -> refine Personas feedback loop).
"""

from __future__ import annotations

from typing import Any

from edt_platform.config import ModelTier
from edt_platform.core.base_agent import AgentContext, AgentSpec, BaseAgent
from edt_platform.schemas.artifacts import PersonaContent
from edt_platform.schemas.core import (
    AgentInput,
    Artifact,
    ArtifactType,
    Confidence,
    Phase,
    Provenance,
)

SYSTEM_PROMPT = """You are the Persona Builder in an enterprise Design Thinking platform.
Create realistic, evidence-grounded personas — never stereotypes. Every trait must trace to
supplied research evidence; where evidence is thin, say so and lower confidence. Personas must be
decision-useful for product teams: goals, frustrations, behaviors, and jobs-to-be-done that later
phases can act on. Emit ONLY via the `emit` tool."""

PERSONA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["personas", "confidence"],
    "properties": {
        "personas": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "archetype", "goals", "frustrations"],
                "properties": {
                    "name": {"type": "string"},
                    "archetype": {"type": "string"},
                    "demographics": {"type": "object", "additionalProperties": {"type": "string"}},
                    "goals": {"type": "array", "items": {"type": "string"}},
                    "frustrations": {"type": "array", "items": {"type": "string"}},
                    "behaviors": {"type": "array", "items": {"type": "string"}},
                    "jobs_to_be_done": {"type": "array", "items": {"type": "string"}},
                    "quote": {"type": "string"},
                    "tech_savviness": {"type": "integer", "minimum": 1, "maximum": 5},
                },
            },
        },
        "confidence": {
            "type": "object",
            "properties": {"score": {"type": "number"}, "rationale": {"type": "string"}},
            "required": ["score", "rationale"],
        },
    },
}


class PersonaBuilderAgent(BaseAgent):
    @classmethod
    def default_spec(cls) -> AgentSpec:
        return AgentSpec(
            name="persona_builder",
            role="Evidence-grounded persona synthesis",
            model_tier=ModelTier.DEFAULT,
            system_prompt=SYSTEM_PROMPT,
            tools=["vector.search"],
            mcp_servers=["vector-search"],
            reasoning_strategy="ReAct + evidence grounding",
            output_schema=PERSONA_SCHEMA,
        )

    async def plan(self, task: AgentInput, grounding: dict[str, Any]) -> list[str]:
        return [
            "Cluster research evidence by user archetype",
            "Draft 2–4 personas grounded in evidence",
            "Attach goals, frustrations, behaviors, JTBD",
            "Rate evidence sufficiency and set confidence",
        ]

    async def act(
        self, task: AgentInput, plan: list[str], grounding: dict[str, Any]
    ) -> list[Artifact]:
        evidence = "\n".join(
            f"- {a.title}: {a.content}" for a in task.upstream_artifacts[:20]
        ) or "(no upstream research; infer cautiously and lower confidence)"
        prompt = (
            f"Problem context:\n{task.task}\n\nResearch evidence:\n{evidence}\n\n"
            "Produce personas per your operating principles."
        )
        data, resp = await self.ctx.llm.structured(
            system=self.spec.system_prompt,
            prompt=prompt,
            schema=self.spec.output_schema or PERSONA_SCHEMA,
            tier=self.spec.model_tier,
        )
        conf = data.get("confidence", {"score": 0.6, "rationale": ""})
        artifacts: list[Artifact] = []
        for p in data.get("personas", []):
            persona = PersonaContent(**{k: v for k, v in p.items() if k in PersonaContent.model_fields})
            artifacts.append(
                Artifact(
                    run_id=task.run_id,
                    project_id=task.project_id,
                    phase=Phase.DISCOVER,
                    type=ArtifactType.PERSONA,
                    title=f"Persona — {persona.name} ({persona.archetype})",
                    content=persona.model_dump(),
                    provenance=Provenance(
                        producer_agent=self.spec.name,
                        model=resp.model,
                        reasoning_strategy=self.spec.reasoning_strategy,
                        inputs_ref=[a.id for a in task.upstream_artifacts],
                        token_usage={"in": resp.input_tokens, "out": resp.output_tokens},
                    ),
                    confidence=Confidence(
                        score=float(conf.get("score", 0.6)),
                        rationale=conf.get("rationale", ""),
                    ),
                )
            )
        return artifacts


def build(ctx: AgentContext) -> PersonaBuilderAgent:
    return PersonaBuilderAgent(PersonaBuilderAgent.default_spec(), ctx)
