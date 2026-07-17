"""Durable run-history store (see docs/13-data-model.md).

Persists completed runs + their artifacts so the dashboard's history survives a
process restart. Uses SQLAlchemy async so the SAME code runs against:

  * **SQLite** (default: ``sqlite+aiosqlite:///./data/edt.db``) — zero infrastructure,
    ideal for local/demo; and
  * **PostgreSQL** (set ``EDT_STORE_HISTORY_URL`` to a ``postgresql+asyncpg://`` DSN) —
    the shared, HA store used in production.

Only run metadata + artifact projections are stored here; large blobs live in S3 and
the vector/graph indexes are populated separately (see the memory + RAG subsystems).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    delete,
    insert,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from edt_platform.config import get_settings

_metadata = MetaData()

runs_table = Table(
    "runs",
    _metadata,
    Column("run_id", String, primary_key=True),
    Column("problem", String),
    Column("depth", String),
    Column("status", String),
    Column("created_at", Float),
    Column("finished", Boolean),
    Column("artifacts", Integer),
    Column("tokens_in", Integer),
    Column("tokens_out", Integer),
    Column("est_cost_usd", Float),
    Column("loop_count", Integer),
)

artifacts_table = Table(
    "artifacts",
    _metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, index=True),
    Column("phase", String),
    Column("type", String),
    Column("title", String),
    Column("producer", String),
    Column("model", String),
    Column("confidence", Float),
    Column("content", JSON),
)


class RunStore:
    """Async persistence for runs + artifacts, backend-agnostic (SQLite/Postgres)."""

    def __init__(self, url: str | None = None) -> None:
        self._url = url or get_settings().store.history_url
        self._engine: AsyncEngine | None = None

    async def init(self) -> None:
        if self._engine is None:
            self._engine = create_async_engine(self._url, future=True)
            async with self._engine.begin() as conn:
                await conn.run_sync(_metadata.create_all)

    async def _conn(self):
        if self._engine is None:
            await self.init()
        assert self._engine is not None
        return self._engine.begin()

    async def save_run(self, summary: dict[str, Any]) -> None:
        row = {
            "run_id": summary["run_id"],
            "problem": summary.get("problem", ""),
            "depth": summary.get("depth", "standard"),
            "status": summary.get("status", "completed"),
            "created_at": summary.get("created_at", 0.0),
            "finished": bool(summary.get("finished", True)),
            "artifacts": summary.get("artifacts", 0),
            "tokens_in": summary.get("tokens_in", 0),
            "tokens_out": summary.get("tokens_out", 0),
            "est_cost_usd": summary.get("est_cost_usd", 0.0),
            "loop_count": summary.get("loop_count", 0),
        }
        async with await self._conn() as conn:
            await conn.execute(delete(runs_table).where(runs_table.c.run_id == row["run_id"]))
            await conn.execute(insert(runs_table).values(**row))

    async def save_artifacts(self, run_id: str, artifacts: list[dict[str, Any]]) -> None:
        async with await self._conn() as conn:
            await conn.execute(delete(artifacts_table).where(artifacts_table.c.run_id == run_id))
            if artifacts:
                await conn.execute(
                    insert(artifacts_table),
                    [
                        {
                            "id": a["id"],
                            "run_id": run_id,
                            "phase": a["phase"],
                            "type": a["type"],
                            "title": a["title"],
                            "producer": a["producer"],
                            "model": a.get("model", ""),
                            "confidence": a["confidence"],
                            "content": a.get("content", {}),
                        }
                        for a in artifacts
                    ],
                )

    async def list_runs(self) -> list[dict[str, Any]]:
        stmt = select(runs_table).order_by(runs_table.c.created_at.desc())
        async with await self._conn() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
            return [dict(r) for r in rows]

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        stmt = select(runs_table).where(runs_table.c.run_id == run_id)
        async with await self._conn() as conn:
            r = (await conn.execute(stmt)).mappings().first()
            return dict(r) if r else None

    async def get_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        async with await self._conn() as conn:
            rows = (
                await conn.execute(select(artifacts_table).where(artifacts_table.c.run_id == run_id))
            ).mappings().all()
            return [dict(r) for r in rows]


@lru_cache
def get_store() -> RunStore:
    """Process-wide singleton store."""
    return RunStore()
