"""LLM-as-Judge evaluation harness (see docs/16-evaluation-framework.md).

Scores an artifact against a phase-specific rubric using a panel of independent
judges (majority/mean aggregation) to reduce single-judge variance. Powers both
offline eval (golden datasets, CI gates) and online sampling. Rubrics encode the
Design-Thinking quality bar (persona realism, HMW quality, idea novelty/feasibility,
PRD completeness, business-case rigor, etc.).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field

from edt_platform.config import ModelTier
from edt_platform.core.llm import LLMClient
from edt_platform.schemas.core import Artifact, Phase

# Phase -> rubric dimensions (0-1 each). Extend per artifact type as needed.
RUBRICS: dict[Phase, list[str]] = {
    Phase.DISCOVER: ["evidence_grounding", "persona_realism", "insight_novelty", "coverage"],
    Phase.DEFINE: ["root_cause_depth", "problem_clarity", "jtbd_quality", "prioritization_logic"],
    Phase.IDEATE: ["novelty", "desirability", "feasibility", "viability", "diversity"],
    Phase.PROTOTYPE: ["prd_completeness", "story_testability", "architecture_soundness", "traceability"],
    Phase.VALIDATE: ["financial_rigor", "risk_coverage", "evidence_of_validation", "decision_justification"],
}

_JUDGE_SYSTEM = """You are an expert Design Thinking evaluator. Score the artifact on each rubric
dimension from 0.0 to 1.0 and give a one-line justification per dimension. Be calibrated and strict.
Return ONLY JSON: {"scores": {"<dim>": <0-1>, ...}, "justifications": {"<dim>": "..."},
"overall": <0-1>, "pass": <bool>}."""


@dataclass
class JudgeResult:
    overall: float
    scores: dict[str, float] = field(default_factory=dict)
    justifications: dict[str, str] = field(default_factory=dict)
    passed: bool = False


class LLMJudge:
    def __init__(self, llm: LLMClient, panel_size: int = 3, pass_threshold: float = 0.7) -> None:
        self._llm = llm
        self._panel = panel_size
        self._threshold = pass_threshold

    async def evaluate(self, artifact: Artifact) -> JudgeResult:
        dims = RUBRICS.get(artifact.phase, ["quality"])
        prompt = (
            f"Rubric dimensions: {', '.join(dims)}\n"
            f"Artifact type: {artifact.type.value}\nTitle: {artifact.title}\n"
            f"Content:\n{json.dumps(artifact.content, default=str)[:6000]}"
        )
        panel: list[JudgeResult] = []
        for _ in range(self._panel):
            resp = await self._llm.complete(
                system=_JUDGE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                tier=ModelTier.REASONING,
                temperature=0.3,
            )
            try:
                data = json.loads(resp.text)
                panel.append(
                    JudgeResult(
                        overall=float(data.get("overall", 0.0)),
                        scores={k: float(v) for k, v in data.get("scores", {}).items()},
                        justifications=data.get("justifications", {}),
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        if not panel:
            return JudgeResult(overall=0.0, passed=False)
        overall = statistics.mean(j.overall for j in panel)
        agg_scores = {
            d: statistics.mean(j.scores.get(d, 0.0) for j in panel) for d in dims
        }
        return JudgeResult(
            overall=overall,
            scores=agg_scores,
            justifications=panel[0].justifications,
            passed=overall >= self._threshold,
        )
