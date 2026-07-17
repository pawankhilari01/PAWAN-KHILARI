"""Hybrid RAG retriever (see docs/06-rag-architecture.md).

Pipeline:  query -> [dense (Voyage) + sparse (BM25)] -> fuse -> rerank -> GraphRAG
expand -> grounded, cited context. Backends are injected; a fake is provided for
local runs. Every returned chunk carries a citation for explainability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from edt_platform.config import get_settings
from edt_platform.schemas.core import Citation, Phase


@dataclass
class RetrievedChunk:
    text: str
    citation: Citation
    dense_score: float = 0.0
    sparse_score: float = 0.0
    rerank_score: float = 0.0


class VectorIndex(Protocol):
    async def dense_search(self, query: str, k: int, flt: dict[str, Any]) -> list[RetrievedChunk]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, chunks: list[RetrievedChunk], k: int) -> list[RetrievedChunk]: ...


class GraphExpander(Protocol):
    async def expand(self, chunks: list[RetrievedChunk], phase: Phase) -> list[RetrievedChunk]: ...


@dataclass
class HybridRetriever:
    index: VectorIndex | None = None
    reranker: Reranker | None = None
    graph: GraphExpander | None = None
    corpus: list[str] = field(default_factory=list)  # fake BM25 corpus for local

    async def retrieve(
        self, query: str, phase: Phase, flt: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        cfg = get_settings().rag
        flt = flt or {}
        chunks: list[RetrievedChunk] = []

        if self.index:
            chunks = await self.index.dense_search(query, cfg.top_k_retrieve, flt)
        else:  # fake: return the corpus lines that share a token with the query
            terms = set(query.lower().split())
            for i, line in enumerate(self.corpus):
                if terms & set(line.lower().split()):
                    chunks.append(
                        RetrievedChunk(
                            text=line,
                            citation=Citation(source_id=f"local-{i}", source_type="local"),
                            dense_score=1.0,
                        )
                    )

        if cfg.enable_graph_rag and self.graph and chunks:
            chunks = await self.graph.expand(chunks, phase)
        if self.reranker and chunks:
            chunks = await self.reranker.rerank(query, chunks, cfg.top_k_rerank)
        else:
            chunks = chunks[: cfg.top_k_rerank]

        return [
            {
                "text": c.text,
                "citation": c.citation.model_dump(),
                "score": c.rerank_score or c.dense_score,
            }
            for c in chunks
        ]
