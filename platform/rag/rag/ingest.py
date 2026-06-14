"""Ingest documents -> chunks (with provenance) -> embeddings -> vector store."""

from __future__ import annotations

from rag.chunk import chunk_text
from rag.embeddings import get_embedder
from rag.models import Chunk, IngestDoc, doc_to_chunks
from rag.store import get_store


async def ingest_docs(docs: list[IngestDoc], tenant_id: str | None = None) -> int:
    chunks: list[Chunk] = []
    for doc in docs:
        if tenant_id and not doc.tenant_id:
            doc.tenant_id = tenant_id
        chunks.extend(doc_to_chunks(doc, chunk_text(doc.text)))
    if not chunks:
        return 0
    vectors = await get_embedder().embed([c.text for c in chunks])
    await get_store().upsert(chunks, vectors)
    return len(chunks)
