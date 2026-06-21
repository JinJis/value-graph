"""PH-PROV3 evidence document store: cache each filing as a PDF once.

US iXBRL HTML / KR DART markup → PDF via the renderer (one-shot, at ingest). At query time
PyMuPDF (PH-PROV3b) highlights whatever the answer actually cited in the cached PDF — so
coverage is the whole document (any question), not a precomputed concept list, and the heavy
headless render is paid at most once per filing. Best-effort + idempotent: a failure for one
filing never blocks the rest.

NOTE (PH-PROV3c): filing-accession resolution here overlaps `locations_ingest`; the old
concept-pointer path is retired once this is wired into `/evidence`, and the shared
resolution will be consolidated then.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib

import httpx
from sqlalchemy import select

from app.config import settings
from app.http import fetch_text
from app.providers.kr.dart_document import fetch_dart_pdf, fetch_document_markup
from app.providers.registry import get_financials_provider
from app.providers.us.sec_edgar import _UA, _resolve_cik
from app.store.db import SessionLocal, init_db
from app.store.locations_ingest import _primary_doc_map
from app.store.models import EvidenceDoc
from app.store.provenance import dart_url, sec_index_url
from app.symbols import Market, build_ref

log = logging.getLogger(__name__)

_STMT_METHODS = ("income_statements", "balance_sheets", "cash_flow_statements")


def _pdf_path(market: str, accession: str) -> pathlib.Path:
    safe = accession.replace("/", "_")
    return pathlib.Path(settings.evidence_docs_dir) / market.upper() / f"{safe}.pdf"


async def _render_pdf(markup: str) -> bytes | None:
    """Ask the renderer to normalize a filing's markup to PDF (Chromium, one-shot)."""
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds + 60) as client:
            resp = await client.post(f"{settings.renderer_url}/pdf/from-html", json={"html": markup})
        if resp.status_code != 200:
            log.warning("renderer /pdf/from-html → %s (US render failed)", resp.status_code)
            return None
        return resp.content
    except Exception as exc:  # noqa: BLE001 — renderer down → no doc this run, never crash ingest
        log.warning("renderer /pdf/from-html unreachable: %s", exc)
        return None


async def _us_markup(accession: str, fetch_url: str | None) -> str | None:
    """US: the iXBRL primary-document HTML (SEC accepts our httpx User-Agent)."""
    if not fetch_url:
        return None
    try:
        return await fetch_text("sec_edgar", fetch_url, headers=_UA)
    except Exception:  # noqa: BLE001
        return None


async def _pdf_bytes(market: str, accession: str, fetch_url: str | None) -> bytes | None:
    """The filing as PDF bytes, by the cheapest Chromium-free route per market:
    KR = DART's official PDF (no render); US = iXBRL HTML → renderer (Chromium, one-shot).
    KR falls back to document.xml→renderer only if the official PDF endpoint fails."""
    if market == "KR":
        pdf = await fetch_dart_pdf(accession)
        if pdf:
            return pdf
        markup = await fetch_document_markup(accession)  # fallback
        return await _render_pdf(markup) if markup else None
    markup = await _us_markup(accession, fetch_url)
    return await _render_pdf(markup) if markup else None


async def ensure_doc(market: str, ticker: str | None, accession: str, *,
                     fetch_url: str | None = None, canonical_url: str | None = None) -> str:
    """Cache one filing as a PDF (idempotent). → 'cached' | 'stored' | 'skipped'."""
    market = market.upper()
    path = _pdf_path(market, accession)
    if path.exists() and await asyncio.to_thread(_doc_status, market, accession) == "stored":
        return "cached"
    pdf = await _pdf_bytes(market, accession, fetch_url)
    if not pdf:
        log.info("evidence doc skipped (no PDF) %s %s", market, accession)
        return "skipped"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf)
    await asyncio.to_thread(_upsert_doc, {
        "market": market, "ticker": (ticker or "").upper() or None,
        "accession_number": accession, "source_url": canonical_url,
        "pdf_path": str(path), "page_count": None, "status": "stored",
    })
    log.info("evidence doc stored %s %s (%d KB) → %s", market, accession, len(pdf) // 1024, path)
    return "stored"


async def _filing_refs(market: str, ticker: str, limit: int) -> dict[str, dict]:
    """Recent filing accessions (with their fetch + canonical URLs) for a ticker, taken
    from the financial statements — exactly the filings users cite figures from."""
    market = market.upper()
    ref = build_ref(Market[market], ticker)
    prov = get_financials_provider(Market[market])
    out: dict[str, dict] = {}
    cik, docmap = None, {}
    if market == "US":
        cik = await _resolve_cik(ref)
        docmap = await _primary_doc_map(cik)
    for method_name in _STMT_METHODS:
        method = getattr(prov, method_name, None)
        if method is None:
            continue
        for period in ("annual", "quarterly"):
            try:
                stmts = await method(ref, period, limit)
            except Exception:  # noqa: BLE001 — a missing statement/period never blocks the rest
                continue
            for st in stmts:
                accn = getattr(st, "accession_number", None)
                if not accn or accn in out:
                    continue
                if market == "US":
                    out[accn] = {"fetch_url": docmap.get(accn), "canonical": sec_index_url(cik, accn)}
                else:
                    fu = getattr(st, "filing_url", None)
                    out[accn] = {"fetch_url": None, "canonical": str(fu) if fu else dart_url(accn)}
    return out


async def build_evidence_docs_for_ticker(market: str, ticker: str, limit: int = 4) -> dict:
    """Cache a ticker's recent filings as PDFs. Returns a per-status summary."""
    if market.upper() not in ("US", "KR"):
        return {"status": "skipped", "reason": "only US + KR supported"}
    refs = await _filing_refs(market, ticker, limit)
    log.info("evidence docs: %s %s → %d filing(s) to cache", market, ticker.upper(), len(refs))
    tally = {"stored": 0, "cached": 0, "skipped": 0}
    for accn, info in refs.items():
        r = await ensure_doc(market, ticker, accn, fetch_url=info["fetch_url"], canonical_url=info["canonical"])
        tally[r] += 1
    log.info("evidence docs: %s %s done — stored=%d cached=%d skipped=%d",
             market, ticker.upper(), tally["stored"], tally["cached"], tally["skipped"])
    return {"status": "ok", "ticker": ticker.upper(), "filings": len(refs), **tally}


async def run_build_evidence_docs(market: str, tickers: list[str]) -> None:
    """Background runner: cache filings as PDFs for a set of tickers, tracked as an
    IngestionJob (visible in /admin/jobs). Best-effort per ticker."""
    from app.store.jobs import finish_job, start_job, update_progress

    tickers = tickers or []
    job = await asyncio.to_thread(start_job, "evidence_docs", market, ",".join(tickers), len(tickers))
    total = 0
    try:
        for i, tk in enumerate(tickers, 1):
            try:
                res = await build_evidence_docs_for_ticker(market, tk)
                total += res.get("stored", 0) + res.get("cached", 0)
            except Exception:  # noqa: BLE001 — one ticker never aborts the run
                pass
            await asyncio.to_thread(update_progress, job, i)
        await asyncio.to_thread(finish_job, job, "success", total)
    except Exception as exc:  # noqa: BLE001
        await asyncio.to_thread(finish_job, job, "error", total, str(exc))


# --- store access --------------------------------------------------------
def _doc_status(market: str, accession: str) -> str | None:
    init_db()
    with SessionLocal() as db:
        return db.execute(
            select(EvidenceDoc.status).where(
                EvidenceDoc.market == market.upper(), EvidenceDoc.accession_number == accession)
        ).scalar_one_or_none()


def _upsert_doc(row: dict) -> None:
    init_db()
    with SessionLocal() as db:
        existing = db.execute(
            select(EvidenceDoc).where(
                EvidenceDoc.market == row["market"], EvidenceDoc.accession_number == row["accession_number"])
        ).scalar_one_or_none()
        if existing:
            for k, v in row.items():
                setattr(existing, k, v)
        else:
            db.add(EvidenceDoc(**row))
        db.commit()


def get_evidence_doc(market: str, accession: str) -> dict | None:
    """The cached PDF record for the /evidence reader + '원문 열기' (PH-PROV3b)."""
    init_db()
    with SessionLocal() as db:
        row = db.execute(
            select(EvidenceDoc).where(
                EvidenceDoc.market == market.upper(), EvidenceDoc.accession_number == accession)
        ).scalar_one_or_none()
        if not row:
            return None
        return {"pdf_path": row.pdf_path, "source_url": row.source_url,
                "status": row.status, "page_count": row.page_count}
