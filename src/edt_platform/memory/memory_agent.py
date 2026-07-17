"""MemoryAgent — the layered long-term memory service.

Five cooperating layers (see docs/05-memory-architecture.md):

    working    -> Redis            (per-task scratchpad, short TTL)
    episodic   -> PostgreSQL+Kafka (immutable run/turn/decision log)
    semantic   -> Qdrant           (embeddings of insights/personas/learnings)
    procedural -> prompt/skill registry (versioned playbooks)
    graph      -> Neo4j            (entities + relationships, GraphRAG)

The concrete backends are injected; the reference implementation below is an
in-memory fake used for local runs and tests. Production wires real clients.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from edt_platform.schemas.core import Artifact


class MemoryBackend(Protocol):
    async def upsert(self, collection: str, key: str, value: dict[str, Any]) -> None: ...
    async def search(self, collection: str, query: str, k: int) -> list[dict[str, Any]]: ...


@dataclass
class MemoryRecord:
    id: str
    scope: str                 # run | project | org | global
    kind: str                  # insight | persona | decision | learning | turn
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    ttl_s: int | None = None


class MemoryAgent:
    """Read/write/consolidate/forget/retrieve across the five layers."""

    def __init__(
        self,
        working: MemoryBackend | None = None,
        semantic: MemoryBackend | None = None,
        graph: Any | None = None,
    ) -> None:
        self._working = working
        self._semantic = semantic
        self._graph = graph
        self._fallback: list[MemoryRecord] = []  # in-memory fake

    # ----- write paths ----------------------------------------------------- #
    async def write_working(self, run_id: UUID, key: str, value: dict[str, Any]) -> None:
        if self._working:
            await self._working.upsert(f"work:{run_id}", key, value)
        else:
            self._fallback.append(
                MemoryRecord(id=key, scope="run", kind="turn", text=str(value), ttl_s=3600)
            )

    async def write_episodic(self, artifact: Artifact) -> None:
        """Append an immutable record of an artifact to the episodic log."""
        self._fallback.append(
            MemoryRecord(
                id=str(artifact.id),
                scope="run",
                kind="decision",
                text=artifact.title,
                metadata={"type": artifact.type.value, "phase": artifact.phase.value},
            )
        )

    async def write_semantic(self, artifact: Artifact) -> None:
        """Embed + store the artifact for cross-project semantic recall."""
        record = {
            "id": str(artifact.id),
            "text": f"{artifact.title}\n{artifact.content}",
            "type": artifact.type.value,
            "phase": artifact.phase.value,
            "project_id": str(artifact.project_id),
        }
        if self._semantic:
            await self._semantic.upsert("edt_semantic", str(artifact.id), record)
        if self._graph:
            await self._graph.upsert_artifact(artifact)

    # ----- read paths ------------------------------------------------------ #
    async def retrieve(
        self, query: str, scopes: list[str], run_id: UUID, k: int = 6
    ) -> list[dict[str, Any]]:
        if self._semantic:
            return await self._semantic.search("edt_semantic", query, k)
        # naive fallback substring match
        q = query.lower()
        hits = [r for r in self._fallback if q in r.text.lower() and r.scope in scopes]
        return [{"id": r.id, "text": r.text, "metadata": r.metadata} for r in hits[:k]]

    # ----- lifecycle ------------------------------------------------------- #
    async def consolidate(self, run_id: UUID) -> None:
        """Summarize an episode into durable semantic/procedural learnings.

        Production: an LLM summarizer distills the run's turns into (a) reusable
        insights written to semantic memory and (b) a playbook delta to procedural
        memory, then compacts the working memory.
        """
        # reference no-op; see docs for the full consolidation strategy.
        return None

    async def forget(self, older_than_s: int) -> int:
        """TTL-based forgetting for working memory / stale, low-value records."""
        now = time.time()
        before = len(self._fallback)
        self._fallback = [
            r
            for r in self._fallback
            if not (r.ttl_s and now - r.created_at > r.ttl_s)
            and now - r.created_at < older_than_s
        ]
        return before - len(self._fallback)
