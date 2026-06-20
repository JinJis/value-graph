"""Query -> embed -> vector search -> (optional) rerank -> hits with provenance."""

from __future__ import annotations

from rag.config import settings
from rag.embeddings import get_embedder
from rag.models import SearchHit
from rag.rerank import get_reranker
from rag.store import get_store


async def search(query: str, top_k: int | None = None, filters: dict | None = None) -> list[SearchHit]:
    top_k = top_k or settings.top_k
    qvec = (await get_embedder().embed([query]))[0]
    hits = await get_store().search(qvec, top_k, filters or None)
    if not hits:
        return []
    if settings.reranker_backend != "none":
        docs = [c.text for c, _ in hits]
        ranked = await get_reranker().rerank(query, docs, min(settings.rerank_top_n, len(docs)))
        hits = [(hits[i][0], score) for i, score in ranked]
    return [SearchHit(text=c.text, score=round(s, 4), provenance=c.provenance()) for c, s in hits]
