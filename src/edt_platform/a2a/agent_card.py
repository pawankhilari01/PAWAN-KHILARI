"""A2A (Agent2Agent) protocol primitives (see docs/12-api-specification.md).

Each independently deployable agent publishes an Agent Card at
``/.well-known/agent.json`` and accepts JSON-RPC 2.0 ``tasks/send`` + ``tasks/get``.
This lets the Supervisor and Phase Agents delegate to workers over HTTP without
sharing a process, and lets third-party agents interoperate.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    """The public capability descriptor advertised by an agent service."""

    name: str
    description: str
    version: str = "1.0.0"
    url: str
    provider: str = "EDT Platform"
    protocol_version: str = "a2a/1.0"
    capabilities: dict[str, bool] = Field(
        default_factory=lambda: {"streaming": True, "pushNotifications": True}
    )
    default_input_modes: list[str] = Field(default_factory=lambda: ["application/json", "text/plain"])
    default_output_modes: list[str] = Field(default_factory=lambda: ["application/json"])
    skills: list[AgentSkill] = Field(default_factory=list)
    authentication: dict[str, Any] = Field(
        default_factory=lambda: {"schemes": ["oidc-bearer"]}
    )


class A2ATaskRequest(BaseModel):
    """JSON-RPC 2.0 params for ``tasks/send``."""

    id: str
    session_id: str | None = None
    message: dict[str, Any]           # {role, parts:[{type,text|data}]}
    accepted_output_modes: list[str] = Field(default_factory=lambda: ["application/json"])


class A2ATaskResult(BaseModel):
    id: str
    status: str                       # submitted|working|input-required|completed|failed
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
