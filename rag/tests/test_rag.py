"""RAG tests on the dependency-free default (hash embedder + memory store + no rerank).

The hash embedder is lexical, so semantically these are keyword-overlap checks —
enough to verify the full pipeline + provenance end-to-end without heavy models.
"""

from __future__ import annotations

import math

from fastapi.testclient import TestClient

from rag import store
from rag.chunk import chunk_text
from rag.embeddings import HashEmbedder, get_embedder
from rag.ingest import ingest_docs
from rag.main import app
from rag.models import IngestDoc
from rag.search import search

client = TestClient(app)


def _reset():
    store.get_store.cache_clear()  # fresh in-memory store


def test_chunking():
    text = "Para one is here.\n\nPara two follows.\n\nThird paragraph ends it."
    chunks = chunk_text(text, size=25, overlap=5)
    assert len(chunks) >= 2 and all(chunks)


async def test_hash_embedder_normalized_and_deterministic():
    e = HashEmbedder(64)
    a = (await e.embed(["apple chip supplier"]))[0]
    b = (await e.embed(["apple chip supplier"]))[0]
    assert a == b  # deterministic
    assert abs(math.sqrt(sum(x * x for x in a)) - 1.0) < 1e-6  # L2-normalized


def test_default_backend_is_hash():
    get_embedder.cache_clear()
    assert isinstance(get_embedder(), HashEmbedder)


async def test_ingest_search_with_provenance():
    _reset()
    docs = [
        IngestDoc(text="Apple discloses a limited number of suppliers including TSMC that manufacture its chips.",
                  source="SEC EDGAR", doc_type="10-K", ticker="AAPL", market="US",
                  url="https://sec.gov/aapl-10k", as_of="2025-11-01", section="Item 1A"),
        IngestDoc(text="The Bank of Korea raised its base interest rate to 3.5 percent.", source="ECOS", market="KR"),
        IngestDoc(text="Tesla expanded electric vehicle battery production at its gigafactory.", source="SEC EDGAR", ticker="TSLA", market="US"),
    ]
    n = await ingest_docs(docs)
    assert n >= 3
    hits = await search("Apple chip suppliers TSMC", top_k=3)
    assert hits and "TSMC" in hits[0].text
    prov = hits[0].provenance
    assert prov["ticker"] == "AAPL" and prov["source"] == "SEC EDGAR"
    assert prov["url"] == "https://sec.gov/aapl-10k" and prov["as_of"] == "2025-11-01"


async def test_search_filter_by_market():
    _reset()
    await ingest_docs([
        IngestDoc(text="Samsung Electronics semiconductor memory chips business.", ticker="005930", market="KR", source="OpenDART"),
        IngestDoc(text="Apple semiconductor chips and suppliers overview.", ticker="AAPL", market="US", source="SEC EDGAR"),
    ])
    hits = await search("semiconductor chips", top_k=5, filters={"market": "KR"})
    assert hits and all(h.provenance.get("market") == "KR" for h in hits)


def test_endpoints():
    _reset()
    assert client.get("/rag/info").json()["embedding_backend"] == "hash"
    ing = client.post("/rag/ingest", json={"documents": [
        {"text": "Apple sources chips from TSMC, a key supplier.", "source": "SEC EDGAR", "ticker": "AAPL", "url": "https://sec.gov/x"}
    ]})
    assert ing.json()["chunks"] >= 1
    res = client.post("/rag/search", json={"query": "Apple TSMC supplier chips", "top_k": 3}).json()
    assert res["hits"] and res["hits"][0]["provenance"]["ticker"] == "AAPL"


async def test_reranker_none_passthrough():
    from rag.rerank import NoneReranker

    out = await NoneReranker().rerank("q", ["a", "b", "c"], 2)
    assert out == [(0, 0.0), (1, 0.0)]


def test_embedder_factory_unknown_raises(monkeypatch):
    import pytest

    from rag import embeddings
    from rag.config import settings as s

    embeddings.get_embedder.cache_clear()
    monkeypatch.setattr(s, "embedding_backend", "nope")
    with pytest.raises(ValueError):
        embeddings.get_embedder()
    embeddings.get_embedder.cache_clear()


def test_info_endpoint_reflects_backends():
    j = client.get("/rag/info").json()
    assert j["embedding_backend"] == "hash" and j["vector_store"] == "memory" and j["reranker_backend"] == "none"


async def test_search_on_empty_store_returns_nothing():
    _reset()
    assert await search("anything at all", top_k=5) == []


# --- PH-2a: per-tenant document isolation -------------------------------------
_HDR_A = {"X-Tenant-Id": "ten_a"}
_HDR_B = {"X-Tenant-Id": "ten_b"}


def _ingest(text: str, headers: dict | None = None):
    return client.post("/rag/ingest", json={"documents": [{"text": text, "source": "SEC EDGAR"}]},
                       headers=headers or {})


def test_tenant_cannot_see_another_tenants_docs():
    _reset()
    _ingest("Acme builds widgets exclusively for tenant A.", _HDR_A)
    # tenant B searches the same query → must not see tenant A's private doc
    resb = client.post("/rag/search", json={"query": "Acme widgets", "top_k": 5}, headers=_HDR_B).json()
    assert resb["hits"] == []
    # tenant A sees its own doc
    resa = client.post("/rag/search", json={"query": "Acme widgets", "top_k": 5}, headers=_HDR_A).json()
    assert resa["hits"] and "Acme" in resa["hits"][0]["text"]


def test_global_docs_visible_to_every_tenant():
    _reset()
    _ingest("Apple sources chips from TSMC, a key supplier.")  # no header → global
    # a scoped tenant still sees the shared/global corpus
    res = client.post("/rag/search", json={"query": "Apple TSMC supplier chips", "top_k": 5}, headers=_HDR_A).json()
    assert res["hits"] and "TSMC" in res["hits"][0]["text"]


def test_tenant_not_leaked_into_provenance():
    _reset()
    _ingest("Tenant-scoped note about chips.", _HDR_A)
    res = client.post("/rag/search", json={"query": "chips note", "top_k": 5}, headers=_HDR_A).json()
    assert res["hits"] and "tenant" not in res["hits"][0]["provenance"]


async def test_search_respects_top_k():
    _reset()
    await ingest_docs([
        IngestDoc(text=f"Document number {i} about semiconductor chips and suppliers.", source="SEC EDGAR", ticker=f"T{i}")
        for i in range(6)
    ])
    hits = await search("semiconductor chips suppliers", top_k=2)
    assert len(hits) == 2


async def test_search_ranks_relevant_above_unrelated():
    _reset()
    await ingest_docs([
        IngestDoc(text="Apple relies on TSMC to fabricate its custom silicon chips.", source="SEC EDGAR", ticker="AAPL"),
        IngestDoc(text="The cafeteria menu featured pasta and salad on Tuesday.", source="Misc", ticker="ZZZ"),
    ])
    hits = await search("TSMC silicon chips supplier", top_k=2)
    assert hits[0].provenance["ticker"] == "AAPL"  # relevant doc ranks first


async def test_search_filter_by_ticker():
    _reset()
    await ingest_docs([
        IngestDoc(text="Apple chips and suppliers.", ticker="AAPL", market="US", source="SEC EDGAR"),
        IngestDoc(text="Apple-like fruit and orchard suppliers.", ticker="FARM", market="US", source="Misc"),
    ])
    hits = await search("apple suppliers", top_k=5, filters={"ticker": "AAPL"})
    assert hits and all(h.provenance.get("ticker") == "AAPL" for h in hits)


def test_long_text_chunks_into_multiple_pieces():
    text = ". ".join(f"Sentence {i} about supply chains and disclosures" for i in range(40))
    chunks = chunk_text(text, size=80, overlap=10)
    assert len(chunks) > 1 and all(chunks)
