"""Pluggable reranker backends, selected by RAG_RERANKER_BACKEND.

``rerank(query, docs, top_n) -> [(original_index, score)]`` sorted best-first.
"""

from __future__ import annotations

import asyncio
from functools import cache
from typing import Protocol

import httpx

from rag.config import settings


class Reranker(Protocol):
    async def rerank(self, query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]: ...


class NoneReranker:
    async def rerank(self, query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]:
        return [(i, 0.0) for i in range(min(len(docs), top_n))]


class CrossEncoderReranker:
    """oss-cpu / oss-gpu via sentence-transformers CrossEncoder."""

    def __init__(self, model: str, device: str) -> None:
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model, device=device)

    async def rerank(self, query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]:
        def _run():
            scores = self._model.predict([(query, d) for d in docs])
            return sorted(((i, float(s)) for i, s in enumerate(scores)), key=lambda x: x[1], reverse=True)[:top_n]

        return await asyncio.to_thread(_run)


class TEIReranker:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint.rstrip("/")

    async def rerank(self, query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.post(f"{self.endpoint}/rerank", json={"query": query, "texts": docs})
            resp.raise_for_status()
            rows = resp.json()  # [{index, score}, ...]
        ranked = sorted(((r["index"], float(r["score"])) for r in rows), key=lambda x: x[1], reverse=True)
        return ranked[:top_n]


class VertexReranker:
    """gcp — Vertex AI Ranking API (Discovery Engine RankService)."""

    def __init__(self, project: str, location: str, ranking_config: str) -> None:
        from google.cloud import discoveryengine_v1 as de

        self._client = de.RankServiceClient()
        self._de = de
        self._config = self._client.ranking_config_path(project, location, ranking_config)

    async def rerank(self, query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]:
        def _run():
            records = [self._de.RankingRecord(id=str(i), content=d) for i, d in enumerate(docs)]
            req = self._de.RankRequest(ranking_config=self._config, query=query, records=records, top_n=top_n)
            resp = self._client.rank(request=req)
            return [(int(r.id), float(r.score)) for r in resp.records][:top_n]

        return await asyncio.to_thread(_run)


@cache
def get_reranker() -> Reranker:
    backend = settings.reranker_backend
    if backend == "none":
        return NoneReranker()
    if backend in ("oss-cpu", "oss-gpu"):
        return CrossEncoderReranker(settings.reranker_model, "cuda" if backend == "oss-gpu" else "cpu")
    if backend == "tei":
        return TEIReranker(settings.reranker_endpoint)
    if backend == "gcp":
        return VertexReranker(settings.gcp_project, settings.gcp_location, settings.gcp_ranking_config)
    raise ValueError(f"Unknown RAG_RERANKER_BACKEND '{backend}'.")
