"""RAG data models. Chunks carry the platform trust envelope (provenance)."""

from __future__ import annotations

from pydantic import BaseModel, Field

# Provenance fields a chunk/doc may carry (the trust envelope for unstructured data).
_PROVENANCE = ("source", "doc_type", "ticker", "market", "as_of", "url", "section", "accession")


class IngestDoc(BaseModel):
    text: str
    doc_id: str | None = None
    source: str | None = Field(None, description="e.g. 'SEC EDGAR', 'OpenDART', 'Google News'.")
    doc_type: str | None = None
    ticker: str | None = None
    market: str | None = None
    as_of: str | None = None
    url: str | None = None
    section: str | None = None
    accession: str | None = None


class Chunk(BaseModel):
    id: str
    text: str
    source: str | None = None
    doc_type: str | None = None
    ticker: str | None = None
    market: str | None = None
    as_of: str | None = None
    url: str | None = None
    section: str | None = None
    accession: str | None = None

    def provenance(self) -> dict:
        return {k: getattr(self, k) for k in _PROVENANCE if getattr(self, k) is not None}


class IngestRequest(BaseModel):
    documents: list[IngestDoc]


class SearchRequest(BaseModel):
    query: str
    top_k: int | None = None
    ticker: str | None = None
    market: str | None = None


class SearchHit(BaseModel):
    text: str
    score: float
    provenance: dict


def doc_to_chunks(doc: IngestDoc, texts: list[str]) -> list[Chunk]:
    base = doc.doc_id or str(abs(hash(doc.text)) % (10**10))
    return [
        Chunk(
            id=f"{base}::{i}", text=t, source=doc.source, doc_type=doc.doc_type, ticker=doc.ticker,
            market=doc.market, as_of=doc.as_of, url=doc.url, section=doc.section, accession=doc.accession,
        )
        for i, t in enumerate(texts)
    ]
