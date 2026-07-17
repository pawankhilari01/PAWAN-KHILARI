"""Workflow Planner (cross-cutting).

Given a business problem and run configuration, produces an executable plan: which
phases to run, which worker agents to activate per phase, their dependencies
(fan-out/fan-in), model-tier budget, and the approval gates. The Supervisor executes
the plan; the planner can re-plan when loops fire (e.g. Validate -> Ideate).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from edt_platform.schemas.core import Phase

# Canonical worker roster per phase (subset activated per run by the planner).
PHASE_WORKERS: dict[Phase, list[str]] = {
    Phase.DISCOVER: [
        "problem_discovery", "customer_research", "voice_of_customer",
        "support_ticket_analyzer", "market_research", "competitive_intelligence",
        "technology_trend", "patent_research", "industry_benchmark",
        "persona_builder", "journey_mapping", "stakeholder_analysis",
        "business_context", "research_synthesizer",
    ],
    Phase.DEFINE: [
        "insight_synthesizer", "affinity_mapping", "root_cause", "five_why",
        "fishbone", "problem_statement", "jtbd", "pov_generator",
        "how_might_we", "opportunity_prioritization", "risk_discovery", "constraint",
    ],
    Phase.IDEATE: [
        "brainstorm", "scamper", "triz", "first_principles", "blue_ocean",
        "reverse_thinking", "innovation", "ai_opportunity", "business_model",
        "idea_merger", "idea_cluster", "idea_ranking", "idea_scoring",
        "idea_critic", "idea_refiner", "idea_selector",
    ],
    Phase.PROTOTYPE: [
        "solution_architect", "ux_architect", "information_architecture",
        "wireframe", "figma_generator", "ui_designer", "user_flow",
        "prd_generator", "user_story", "acceptance_criteria", "architecture",
        "api_designer", "data_model", "prototype_generator", "react_generator",
        "no_code_builder",
    ],
    Phase.VALIDATE: [
        "customer_simulator", "persona_simulation", "survey_generator",
        "interview_generator", "feedback_analyzer", "market_validation",
        "financial_analysis", "pricing", "roi", "risk", "compliance",
        "responsible_ai", "go_no_go", "recommendation", "roadmap",
    ],
}

# Agents that fan-in / synthesize the phase (run after their peers).
PHASE_SYNTHESIZERS: dict[Phase, str] = {
    Phase.DISCOVER: "research_synthesizer",
    Phase.DEFINE: "opportunity_prioritization",
    Phase.IDEATE: "idea_selector",
    Phase.PROTOTYPE: "prd_generator",
    Phase.VALIDATE: "recommendation",
}


@dataclass
class PhasePlan:
    phase: Phase
    parallel_workers: list[str]
    synthesizer: str
    requires_approval: bool = True


@dataclass
class RunPlan:
    phases: list[PhasePlan] = field(default_factory=list)
    notes: str = ""


class WorkflowPlanner:
    """Deterministic default planner; an LLM planner can override selection."""

    def plan(
        self,
        *,
        problem: str,
        phases: list[Phase] | None = None,
        depth: str = "standard",
        require_approval: bool = True,
    ) -> RunPlan:
        phases = phases or list(Phase)
        # `depth` can trim the parallel roster to control cost.
        trim = {"lite": 6, "standard": 10, "deep": 99}.get(depth, 10)
        plan = RunPlan(notes=f"depth={depth}")
        for ph in phases:
            workers = [w for w in PHASE_WORKERS[ph]][:trim]
            synth = PHASE_SYNTHESIZERS[ph]
            if synth not in workers:
                workers = [w for w in workers if w != synth]
            plan.phases.append(
                PhasePlan(
                    phase=ph,
                    parallel_workers=[w for w in workers if w != synth],
                    synthesizer=synth,
                    requires_approval=require_approval,
                )
            )
        return plan
