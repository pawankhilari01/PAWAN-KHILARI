"""Structured payload models for the platform's key domain artifacts.

These are the ``content`` payloads carried inside :class:`Artifact`. They give
downstream agents strong typing (a Persona Builder emits :class:`PersonaContent`,
the Journey Mapping Agent consumes it, etc.) and back the JSON-Schema output
contracts enforced by guardrails.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Discover
# --------------------------------------------------------------------------- #
class PainPoint(BaseModel):
    description: str
    severity: int = Field(ge=1, le=5)
    frequency: int = Field(ge=1, le=5)
    evidence: list[str] = Field(default_factory=list)
    affected_persona: str | None = None


class PersonaContent(BaseModel):
    name: str
    archetype: str
    demographics: dict[str, str] = Field(default_factory=dict)
    goals: list[str] = Field(default_factory=list)
    frustrations: list[str] = Field(default_factory=list)
    behaviors: list[str] = Field(default_factory=list)
    jobs_to_be_done: list[str] = Field(default_factory=list)
    quote: str | None = None
    tech_savviness: int = Field(default=3, ge=1, le=5)


class JourneyStage(BaseModel):
    stage: str
    actions: list[str]
    thoughts: list[str]
    emotions: list[str]
    pain_points: list[str]
    opportunities: list[str]


class JourneyMapContent(BaseModel):
    persona: str
    scenario: str
    stages: list[JourneyStage]


class InsightContent(BaseModel):
    statement: str
    supporting_evidence: list[str]
    surprise_factor: int = Field(ge=1, le=5)
    opportunity_areas: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Define
# --------------------------------------------------------------------------- #
class RootCauseContent(BaseModel):
    problem: str
    five_whys: list[str]
    fishbone: dict[str, list[str]] = Field(
        default_factory=dict, description="category -> causes (Ishikawa)"
    )
    root_causes: list[str]


class ProblemStatementContent(BaseModel):
    statement: str
    user: str
    need: str
    insight: str
    success_looks_like: str


class JTBDContent(BaseModel):
    when: str
    i_want_to: str
    so_i_can: str
    functional: list[str] = Field(default_factory=list)
    emotional: list[str] = Field(default_factory=list)
    social: list[str] = Field(default_factory=list)


class HMWContent(BaseModel):
    statements: list[str]
    linked_problem_statement: str | None = None


class OpportunityContent(BaseModel):
    title: str
    description: str
    impact: int = Field(ge=1, le=5)
    feasibility: int = Field(ge=1, le=5)
    strategic_fit: int = Field(ge=1, le=5)
    rice_score: float | None = None


# --------------------------------------------------------------------------- #
# Ideate
# --------------------------------------------------------------------------- #
class IdeaContent(BaseModel):
    title: str
    description: str
    technique: str = Field(description="e.g. SCAMPER, TRIZ, First-Principles, Blue-Ocean")
    linked_hmw: str | None = None
    novelty: int = Field(default=3, ge=1, le=5)
    desirability: int = Field(default=3, ge=1, le=5)
    feasibility: int = Field(default=3, ge=1, le=5)
    viability: int = Field(default=3, ge=1, le=5)
    ai_leverage: int = Field(default=3, ge=1, le=5)
    composite_score: float | None = None


# --------------------------------------------------------------------------- #
# Prototype
# --------------------------------------------------------------------------- #
class AcceptanceCriterion(BaseModel):
    given: str
    when: str
    then: str


class UserStoryContent(BaseModel):
    as_a: str
    i_want: str
    so_that: str
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    priority: str = "should"     # must/should/could/wont (MoSCoW)
    story_points: int | None = None


class PRDContent(BaseModel):
    title: str
    problem: str
    goals: list[str]
    non_goals: list[str] = Field(default_factory=list)
    personas: list[str] = Field(default_factory=list)
    user_stories: list[UserStoryContent] = Field(default_factory=list)
    success_metrics: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Validate
# --------------------------------------------------------------------------- #
class RiskItem(BaseModel):
    risk: str
    category: str
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    mitigation: str
    owner: str | None = None


class FinancialModelContent(BaseModel):
    horizon_years: int = 3
    assumptions: dict[str, float] = Field(default_factory=dict)
    revenue_by_year: list[float] = Field(default_factory=list)
    cost_by_year: list[float] = Field(default_factory=list)
    npv: float | None = None
    irr: float | None = None
    payback_months: int | None = None
    roi_pct: float | None = None


class GoNoGoContent(BaseModel):
    decision: str = Field(description="'go' | 'no_go' | 'conditional_go'")
    rationale: str
    conditions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    dissenting_view: str | None = None
