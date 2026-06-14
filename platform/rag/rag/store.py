"""Pluggable vector store, selected by RAG_VECTOR_STORE.

* memory   — numpy cosine over an in-process list (dev/CI; vectors are normalized)
* pgvector — Postgres + pgvector (prod; managed via Cloud SQL / AlloyDB)
"""

from __future__ import annotations

import json
from functools import cache
from typing import Protocol

import numpy as np

from rag.config import settings
from rag.models import Chunk

_PROV = ("source", "doc_type", "ticker", "market", "as_of", "url", "section", "accession")


class VectorStore(Protocol):
    async def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    async def search(self, vector: list[float], top_k: int, filters: dict | None = None) -> list[tuple[Chunk, float]]: ...


class MemoryStore:
    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._matrix: list[list[float]] = []

    async def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        self._chunks.extend(chunks)
        self._matrix.extend(vectors)

    async def search(self, vector, top_k, filters=None):
        if not self._matrix:
            return []
        mat = np.asarray(self._matrix, dtype=np.float32)
        q = np.asarray(vector, dtype=np.float32)
        sims = mat @ q  # vectors are L2-normalized -> dot == cosine
        order = np.argsort(-sims)
        out: list[tuple[Chunk, float]] = []
        for i in order:
            chunk = self._chunks[int(i)]
            if filters and not _match(chunk, filters):
                continue
            out.append((chunk, float(sims[int(i)])))
            if len(out) >= top_k:
                break
        return out


class PgVectorStore:
    def __init__(self, dsn: str, dim: int) -> None:
        import psycopg
        from pgvector.psycopg import register_vector

        self._psycopg = psycopg
        self._register = register_vector
        self._dsn = dsn
        self._dim = dim
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS rag_chunks (id TEXT PRIMARY KEY, text TEXT, "
                f"meta JSONB, embedding vector({dim}))"
            )
            conn.commit()

    def _connect(self):
        conn = self._psycopg.connect(self._dsn)
        self._register(conn)
        return conn

    async def upsert(self, chunks, vectors):
        rows = [(c.id, c.text, json.dumps(c.provenance()), v) for c, v in zip(chunks, vectors)]
        with self._connect() as conn:
            conn.cursor().executemany(
                "INSERT INTO rag_chunks (id, text, meta, embedding) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (id) DO UPDATE SET text=EXCLUDED.text, meta=EXCLUDED.meta, embedding=EXCLUDED.embedding",
                rows,
            )
            conn.commit()

    async def search(self, vector, top_k, filters=None):
        where, filter_params = "", []
        if filters:
            conds = []
            for k, val in filters.items():
                conds.append("meta->>%s = %s")
                filter_params.extend([k, str(val)])
            where = "WHERE " + " AND ".join(conds)
        sql = (
            "SELECT id, text, meta, 1 - (embedding <=> %s) AS score FROM rag_chunks "
            f"{where} ORDER BY embedding <=> %s LIMIT %s"
        )
        args = [vector, *filter_params, vector, top_k]
        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        out = []
        for cid, text, meta, score in rows:
            meta = meta or {}
            out.append((Chunk(id=cid, text=text, **{k: meta.get(k) for k in _PROV}), float(score)))
        return out


def _match(chunk: Chunk, filters: dict) -> bool:
    return all(getattr(chunk, k, None) == v for k, v in filters.items())


@cache
def get_store() -> VectorStore:
    if settings.vector_store == "memory":
        return MemoryStore()
    if settings.vector_store == "pgvector":
        from rag.embeddings import get_embedder

        dim = get_embedder().dim or settings.hash_dim
        return PgVectorStore(settings.database_url, dim)
    raise ValueError(f"Unknown RAG_VECTOR_STORE '{settings.vector_store}'.")
