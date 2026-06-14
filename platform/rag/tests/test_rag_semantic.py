"""Real-embedding integration test: proves the RAG pipeline does SEMANTIC
retrieval (not keyword matching) with the oss-cpu backend (fastembed / ONNX).

Skipped unless fastembed is installed — run it with the model present:

    cd rag && uv run --extra oss pytest tests/test_rag_semantic.py -q

The query shares ZERO content words with the document it must retrieve, so a
lexical matcher (the default hash embedder) cannot win here — only real
embeddings can. That's the whole point.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastembed", reason="needs the `oss` extra (fastembed)")

from rag import embeddings, store  # noqa: E402
from rag.config import settings  # noqa: E402
from rag.ingest import ingest_docs  # noqa: E402
from rag.models import IngestDoc  # noqa: E402
from rag.search import search  # noqa: E402

# a small, fast ONNX model so the download stays light
_MODEL = "BAAI/bge-small-en-v1.5"


@pytest.fixture()
def oss_cpu(monkeypatch):
    monkeypatch.setattr(settings, "embedding_backend", "oss-cpu")
    monkeypatch.setattr(settings, "embedding_model", _MODEL)
    embeddings.get_embedder.cache_clear()
    store.get_store.cache_clear()
    yield
    embeddings.get_embedder.cache_clear()
    store.get_store.cache_clear()


def _no_word_overlap(query: str, text: str) -> bool:
    trivial = {"the", "a", "an", "to", "its", "on", "of", "in", "and", "for", "with", "by"}
    qw = {w.strip(".,'?").lower() for w in query.split()} - trivial
    tw = {w.strip(".,'?").lower() for w in text.split()} - trivial
    return not (qw & tw)  # no shared content word


async def test_oss_cpu_semantic_retrieval_beats_lexical(oss_cpu):
    store.get_store.cache_clear()
    docs = [
        # monetary policy — worded WITHOUT "interest", "rate", "fed", "hike"
        IngestDoc(text="The central bank lifted its benchmark borrowing cost to cool rising consumer prices.",
                  source="ECOS", doc_type="macro", ticker=None, market="US", url="https://example/policy"),
        # a consumer-gadget topic
        IngestDoc(text="The firm unveiled a thinner laptop featuring a brighter display and longer battery life.",
                  source="News", doc_type="news", ticker="X", market="US", url="https://example/gadget"),
        # an earnings topic
        IngestDoc(text="Quarterly profit climbed as demand for cloud data-center services accelerated.",
                  source="SEC EDGAR", doc_type="10-Q", ticker="Y", market="US", url="https://example/earnings"),
    ]
    n = await ingest_docs(docs)
    assert n == 3

    query = "Federal Reserve interest rate hike"
    hits = await search(query, top_k=3)
    assert hits, "no hits returned"
    top = hits[0]
    # the monetary-policy doc must win, even though it shares no content word with the query
    assert top.provenance["url"] == "https://example/policy", f"semantic miss: top={top.text!r}"
    assert _no_word_overlap(query, top.text), "test invalid: query lexically overlaps the target doc"
    # provenance survives the real-embedding pipeline
    assert top.provenance["source"] == "ECOS"


async def test_oss_cpu_distinguishes_close_topics(oss_cpu):
    store.get_store.cache_clear()
    await ingest_docs([
        IngestDoc(text="Apple relies on TSMC to fabricate its custom silicon processors.",
                  source="SEC EDGAR", ticker="AAPL", market="US", url="https://example/aapl"),
        IngestDoc(text="The Bank of Korea held its policy stance amid easing inflation.",
                  source="ECOS", ticker=None, market="KR", url="https://example/bok"),
    ])
    hits = await search("Who manufactures Apple's chips?", top_k=2)
    assert hits[0].provenance["ticker"] == "AAPL"  # semantic match to the supplier doc
