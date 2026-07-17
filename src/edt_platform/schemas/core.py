"""Core typed contracts shared across all agents, phases, and stores.

These Pydantic v2 models are the *lingua franca* of the platform: every agent
consumes and emits them, they are persisted in PostgreSQL (metadata) + S3 (blobs),
indexed in Qdrant, and projected into Neo4j. Keeping them in one place guarantees
that independently deployable agent services agree on the wire format.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class Phase(str, Enum):
    DISCOVER = "discover"
    DEFINE = "define"
    IDEATE = "ideate"
    PROTOTYPE = "prototype"
    VALIDATE = "validate"


class RunStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    GENERATING_DELIVERABLES = "generating_deliverables"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactType(str, Enum):
    # Discover
    PROBLEM_SPACE = "problem_space"
    PAIN_POINT = "pain_point"
    PERSONA = "persona"
    JOURNEY_MAP = "journey_map"
    INSIGHT = "insight"
    OPPORTUNITY_AREA = "opportunity_area"
    RESEARCH_REPORT = "research_report"
    COMPETITOR_ANALYSIS = "competitor_analysis"
    MARKET_ANALYSIS = "market_analysis"
    TREND_REPORT = "trend_report"
    # Define
    ROOT_CAUSE = "root_cause"
    PROBLEM_STATEMENT = "problem_statement"
    JTBD = "jtbd"
    POV = "point_of_view"
    HMW = "how_might_we"
    OPPORTUNITY_MATRIX = "opportunity_matrix"
    # Ideate
    IDEA = "idea"
    IDEA_CATALOGUE = "idea_catalogue"
    IDEA_SCORE = "idea_score"
    PRIORITIZED_BACKLOG = "prioritized_backlog"
    # Prototype
    PRD = "prd"
    USER_STORY = "user_story"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    WIREFRAME = "wireframe"
    ARCHITECTURE = "architecture"
    API_SPEC = "api_spec"
    DATA_MODEL = "data_model"
    PROTOTYPE = "prototype"
    # Validate
    VALIDATION_REPORT = "validation_report"
    BUSINESS_CASE = "business_case"
    FINANCIAL_MODEL = "financial_model"
    ROI = "roi"
    RISK_REGISTER = "risk_register"
    COMPLIANCE_REPORT = "compliance_report"
    GTM_STRATEGY = "gtm_strategy"
    ROADMAP = "roadmap"
    PITCH_DECK = "pitch_deck"
    EXECUTIVE_SUMMARY = "executive_summary"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


# --------------------------------------------------------------------------- #
# Provenance, confidence, explainability
# --------------------------------------------------------------------------- #
class Citation(BaseModel):
    """A single provenance record backing a claim in an artifact (explainability)."""

    source_id: str
    source_type: str = Field(description="e.g. 'support_ticket', 'market_report', 'web', 'kg'")
    uri: str | None = None
    snippet: str | None = None
    score: float | None = Field(default=None, description="retrieval/rerank score")


class Provenance(BaseModel):
    """How an artifact came to be — the audit trail for Responsible AI / explainability."""

    producer_agent: str
    model: str
    reasoning_strategy: str | None = None
    inputs_ref: list[UUID] = Field(default_factory=list, description="upstream artifact ids")
    citations: list[Citation] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    prompt_version: str | None = None
    token_usage: dict[str, int] = Field(default_factory=dict)


class Confidence(BaseModel):
    """Calibrated confidence attached to every artifact; drives loops and escalation."""

    score: float = Field(ge=0.0, le=1.0)
    rationale: str
    uncertainties: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Artifact — the unit of value produced by agents
# --------------------------------------------------------------------------- #
class Artifact(BaseModel):
    """A typed, versioned, governed output of an agent.

    Blobs (images, decks, code) live in S3 referenced by ``blob_uri``; structured
    content lives in ``content``. Every artifact carries provenance + confidence.
    """

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    project_id: UUID
    phase: Phase
    type: ArtifactType
    version: int = 1
    title: str
    content: dict[str, Any] = Field(default_factory=dict)
    blob_uri: str | None = None
    provenance: Provenance
    confidence: Confidence
    approvals: list[UUID] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    supersedes: UUID | None = Field(default=None, description="prior version this replaces")
    created_at: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------- #
# Agent execution I/O
# --------------------------------------------------------------------------- #
class AgentInput(BaseModel):
    """Everything an agent needs to do one unit of work."""

    run_id: UUID
    project_id: UUID
    phase: Phase
    task: str = Field(description="Concrete instruction from the Supervisor/Phase agent.")
    upstream_artifacts: list[Artifact] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))


class AgentOutcome(str, Enum):
    SUCCESS = "success"
    NEEDS_HUMAN = "needs_human"        # escalation
    RETRY = "retry"                    # transient failure
    FAILED = "failed"


class AgentResult(BaseModel):
    """The standardized envelope every agent returns."""

    agent: str
    outcome: AgentOutcome
    artifacts: list[Artifact] = Field(default_factory=list)
    confidence: Confidence | None = None
    reflection: str | None = None
    critique: str | None = None
    escalation_reason: str | None = None
    next_suggested_agents: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    tokens: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Approval
# --------------------------------------------------------------------------- #
class ApprovalRequest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    phase: Phase
    summary: str
    artifacts: list[UUID]
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime = Field(default_factory=_utcnow)
    decided_at: datetime | None = None
    decided_by: str | None = None
    reviewer_notes: str | None = None
