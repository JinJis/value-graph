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
                        "ticker": ticker, "market": market, "accession": accession,
                        "section": f"p.{i + 1}", "url": url})
    finally:
        doc.close()
    return out


async def run_filing_text_ingest(market: str, tickers: list[str]) -> None:
    """Index each ticker's cached filing PDFs' text into RAG, tracked as an IngestionJob
    (kind `filing_text`). Ensures the PDFs exist first; best-effort per ticker."""
    market = (market or "").upper()
    tickers = tickers or []
    source = "SEC EDGAR" if market == "US" else "OpenDART (FSS)"
    job = start_job("filing_text", market, ",".join(tickers), len(tickers))
    total = 0
    try:
        for i, tk in enumerate(tickers, 1):
            try:
                await build_evidence_docs_for_ticker(market, tk)  # ensure PDFs are cached
                docs: list[dict] = []
                for ed in await asyncio.to_thread(evidence_docs_for_ticker, market, tk):
                    docs += await asyncio.to_thread(
                        _pdf_to_docs, ed["pdf_path"], market, tk.upper(), ed["accession"],
                        source, ed["source_url"])
                if docs:
                    chunks = await _ingest_to_rag(settings.rag_url, docs)
                    total += chunks
                    log.info("filing-text: %s %s → %d pages, %d chunks indexed",
                             market, tk.upper(), len(docs), chunks)
            except Exception as exc:  # noqa: BLE001 — one ticker never aborts the run
                log.warning("filing-text: %s %s failed: %s", market, tk, exc)
            update_progress(job, i)
        finish_job(job, "success", total)
    except Exception as exc:  # noqa: BLE001
        finish_job(job, "error", total, str(exc))
