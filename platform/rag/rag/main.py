"""RAG service: provenance-first retrieval over the platform's documents.

Backends (embedding / reranker / vector store) are chosen by RAG_* env vars, so
the same service runs CPU-OSS, GCP (Vertex), or GPU without code changes.
"""

from __future__ import annotations

from fastapi import FastAPI

from rag.config import settings
from rag.ingest import ingest_docs
from rag.models import IngestRequest, SearchRequest
from rag.search import search as run_search

app = FastAPI(
    title="Platform RAG", version="0.1.0",
    description="Provenance-first RAG with pluggable embedding/reranker/store backends.",
)


@app.get("/health", tags=["Meta"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/rag/info", tags=["RAG"], summary="Active backends")
async def info() -> dict:
    return {
        "embedding_backend": settings.embedding_backend,
        "embedding_model": settings.embedding_model,
        "reranker_backend": settings.reranker_backend,
        "vector_store": settings.vector_store,
    }


@app.post("/rag/ingest", tags=["RAG"], summary="Ingest documents (chunk + embed + store)")
async def ingest(body: IngestRequest) -> dict:
    n = await ingest_docs(body.documents)
    return {"chunks": n}


@app.post("/rag/search", tags=["RAG"], summary="Retrieve passages with provenance")
async def search(body: SearchRequest) -> dict:
    filters = {k: v for k, v in (("ticker", body.ticker), ("market", body.market)) if v}
    hits = await run_search(body.query, body.top_k, filters)
    return {"hits": [h.model_dump() for h in hits]}
