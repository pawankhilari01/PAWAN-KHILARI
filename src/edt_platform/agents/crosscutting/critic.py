"""Critic Agent (cross-cutting).

A shared adversarial reviewer any agent can call. It scores an artifact against a
phase-appropriate rubric and returns either ``APPROVE`` or ``REJECT: <reasons>``.
Runs on Opus 4.8 so critiques are rigorous. Kept independent so it can be a
standalone A2A service and reused as an LLM-as-Judge in evaluation.
"""

from __future__ import annotations

from edt_platform.config import ModelTier
from edt_platform.core.llm import LLMClient
from edt_platform.schemas.core import AgentInput, Artifact

CRITIC_SYSTEM = """You are the Critic Agent — a rigorous, adversarial reviewer in an enterprise
Design Thinking platform. Your job is to find what is wrong, unsupported, vague, biased, or
non-actionable in an artifact, and to decide if it meets the bar.

Review against these dimensions: correctness, evidence/grounding, completeness, specificity,
actionability, internal consistency, bias/safety, and alignment to the stated task.

Respond in this exact format:
  VERDICT: APPROVE | REJECT
  SCORE: <0.0-1.0>
  ISSUES:
   - <issue 1>
   - <issue 2>
  MUST_FIX:
   - <the smallest set of changes required to reach APPROVE>

Be terse and concrete. Approve only genuinely strong work; when in doubt, REJECT with fixes."""


class CriticAgent:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def critique(self, agent_name: str, task: AgentInput, artifacts: list[Artifact]) -> str:
        if not artifacts:
            return "VERDICT: REJECT\nSCORE: 0.0\nISSUES:\n - No artifacts produced."
        payload = "\n\n".join(
            f"[{a.type.value}] {a.title}\n{a.content}" for a in artifacts[:8]
        )
        prompt = (
            f"Agent under review: {agent_name}\n"
            f"Original task: {task.task}\n"
            f"Phase: {task.phase.value}\n\n"
            f"Artifact(s):\n{payload}\n\nReview now."
        )
        resp = await self._llm.complete(
            system=CRITIC_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tier=ModelTier.REASONING,
        )
        return resp.text
