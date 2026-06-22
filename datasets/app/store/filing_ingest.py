"""PH-PROV3e: filing PDF text → RAG corpus.

The cached evidence PDF is one artifact with two uses: the highlight source (PH-PROV3a–d) AND
the full-text corpus the agent searches. This extracts each cached filing's text page-by-page
(PyMuPDF) and indexes it into RAG — so `rag__search` returns real filing passages (MD&A, risk
factors, notes, any line), grounded with provenance `{accession, section=p.N, ticker, market,
source}`. The same `accession` lets `/evidence` (text mode) later highlight the cited passage in
the very same PDF. Filings are public → indexed as a global (unscoped) corpus, like news.
"""

from __future__ import annotations

import asyncio
import logging

import fitz  # pymupdf

from app.config import settings
from app.store.evidence_docs import build_evidence_docs_for_ticker, evidence_docs_for_ticker
from app.store.jobs import finish_job, start_job, update_progress
from app.store.news_ingest import _ingest_to_rag  # reuse the RAG /rag/ingest POST helper

log = logging.getLogger(__name__)

_MIN_PAGE_CHARS = 50  # skip near-empty pages (covers/dividers) — not worth a chunk


def _pdf_to_docs(pdf_path: str, market: str, ticker: str, accession: str, source: str,
                 url: str | None) -> list[dict]:
    """One RAG IngestDoc per non-empty page (RAG sub-chunks within); page → `section` so a
    hit points back to the exact page for evidence highlighting."""
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("filing-text: cannot open %s: %s", pdf_path, exc)
        return []
    out: list[dict] = []
    try:
        for i in range(doc.page_count):
            text = doc[i].get_text().strip()
            if len(text) < _MIN_PAGE_CHARS:
                continue
            out.append({"text": text, "source": source, "doc_type": "filing",
                        # stable per (filing, page) → re-ingest UPSERTs instead of duplicating
                        "doc_id": f"{accession}:p.{i + 1}",
                        "ticker": ticker, "market": market, "accession": accession,
                        "section": f"p.{i + 1}", "url": url})
    finally:
        doc.close()
    return out


async def ingest_filing_text_for_ticker(market: str, ticker: str, limit: int = 4,
                                        rag_url: str | None = None) -> int:
    """Cache one ticker's recent filing PDFs and index their text into RAG; return the chunk
    count. The unit of both the batch pipeline AND on-demand ingest (filing_search) — so a
    ticker the corpus has never seen becomes searchable live. Best-effort (0 on failure)."""
    market = (market or "").upper()
    source = "SEC EDGAR" if market == "US" else "OpenDART (FSS)"
    await build_evidence_docs_for_ticker(market, ticker, limit=limit)  # ensure PDFs are cached
    docs: list[dict] = []
    for ed in await asyncio.to_thread(evidence_docs_for_ticker, market, ticker):
        docs += await asyncio.to_thread(
            _pdf_to_docs, ed["pdf_path"], market, ticker.upper(), ed["accession"],
            source, ed["source_url"])
    if not docs:
        return 0
    chunks = await _ingest_to_rag(rag_url or settings.rag_url, docs)
    log.info("filing-text: %s %s → %d pages, %d chunks indexed", market, ticker.upper(), len(docs), chunks)
    return chunks


async def run_filing_text_ingest(market: str, tickers: list[str]) -> None:
    """Index each ticker's cached filing PDFs' text into RAG, tracked as an IngestionJob
    (kind `filing_text`). Ensures the PDFs exist first; best-effort per ticker."""
    market = (market or "").upper()
    tickers = tickers or []
    job = start_job("filing_text", market, ",".join(tickers), len(tickers))
    total = 0
    try:
        for i, tk in enumerate(tickers, 1):
            try:
                total += await ingest_filing_text_for_ticker(market, tk)
            except Exception as exc:  # noqa: BLE001 — one ticker never aborts the run
                log.warning("filing-text: %s %s failed: %s", market, tk, exc)
            update_progress(job, i)
        finish_job(job, "success", total)
    except Exception as exc:  # noqa: BLE001
        finish_job(job, "error", total, str(exc))
