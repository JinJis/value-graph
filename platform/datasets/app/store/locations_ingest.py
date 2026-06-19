"""PH-PROV2 offline precompute: index WHERE each financial fact appears in its filing.

For a US ticker: pull as-reported facts (concept / accession / period / value), group by
filing, download each filing's primary inline-XBRL document once, deterministically match
every fact to its ``<ix:nonFraction>`` element, and upsert a ``FactLocation`` pointer. The
highlighted evidence image is rendered lazily from these pointers at query time. Best-effort
+ idempotent: a parse/download failure for one filing never blocks the rest (or ingestion).
"""

from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select

from app.http import fetch_text
from app.providers.registry import get_financials_provider
from app.providers.us.ixbrl import build_pointers_for_filing
from app.providers.us.sec_edgar import _UA, _resolve_cik, _submissions
from app.store.db import SessionLocal, init_db
from app.store.models import FactLocation
from app.symbols import Market, build_ref


async def _primary_doc_map(cik10: str) -> dict[str, str]:
    """accession_number → primary-document URL, from the submissions index (same URL
    shape `SecEdgarProvider.filings` builds)."""
    sub = await _submissions(cik10)
    recent = (sub.get("filings") or {}).get("recent") or {}
    accns = recent.get("accessionNumber") or []
    prim = recent.get("primaryDocument") or []
    out: dict[str, str] = {}
    for i, accn in enumerate(accns):
        doc = prim[i] if i < len(prim) and prim[i] else ""
        if accn and doc:
            nodash = accn.replace("-", "")
            out[accn] = f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{nodash}/{doc}"
    return out


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


async def precompute_locations_for_ticker(market: str, ticker: str, period: str = "annual", limit: int = 4) -> dict:
    """Index fact→location pointers for a US ticker's recent filings. Returns a summary."""
    if market.upper() != "US":  # PH-PROV2a is SEC iXBRL only; KR/DART = PR4 (PyMuPDF, PH-7b)
        return {"status": "skipped", "reason": "only US (SEC iXBRL) supported in PH-PROV2a"}
    ref = build_ref(Market.US, ticker)
    cik10 = await _resolve_cik(ref)
    prov = get_financials_provider(Market.US)
    periods = await prov.as_reported(ref, period, limit)
    docmap = await _primary_doc_map(cik10)

    # group targets by accession → one HTML download per filing (cache-friendly, rate-safe)
    by_accn: dict[str, list[dict]] = {}
    for p in periods:
        rp = p["report_period"]
        for item in p["line_items"]:
            accn = item.get("accession_number")
            if accn:
                by_accn.setdefault(accn, []).append({
                    "concept": item["concept"], "report_period": rp,
                    "value": item.get("value"), "unit": item.get("unit"),
                })

    rows: list[dict] = []
    for accn, targets in by_accn.items():
        url = docmap.get(accn)
        if not url:
            continue
        try:
            html = await fetch_text("sec_edgar", url, headers=_UA)
            pointers = build_pointers_for_filing(html, targets)
        except Exception:  # noqa: BLE001 — one bad filing never blocks the rest
            continue
        for ptr in pointers:
            rows.append({
                "market": "US", "cik": cik10, "accession_number": accn,
                "concept": ptr["concept"], "period": period,
                "report_period": _as_date(ptr["report_period"]), "value": ptr.get("value"),
                "unit": ptr.get("unit"), "primary_doc_url": url,
                "element_id": ptr.get("element_id"), "selector": ptr.get("selector"),
                "scale": ptr.get("scale"), "sign": ptr.get("sign"),
                "match_rule": ptr.get("match_rule"), "status": ptr["status"],
            })

    written = await asyncio.to_thread(_upsert, rows)
    return {"status": "ok", "ticker": ticker.upper(), "filings": len(by_accn),
            "pointers": len(rows), "matched": sum(1 for r in rows if r["status"] == "matched"),
            "written": written}


def _upsert(rows: list[dict]) -> int:
    init_db()
    n = 0
    with SessionLocal() as db:
        for r in rows:
            existing = db.execute(
                select(FactLocation).where(
                    FactLocation.market == r["market"], FactLocation.cik == r["cik"],
                    FactLocation.accession_number == r["accession_number"],
                    FactLocation.concept == r["concept"],
                    FactLocation.report_period == r["report_period"],
                )
            ).scalar_one_or_none()
            if existing:
                for k, v in r.items():
                    setattr(existing, k, v)
            else:
                db.add(FactLocation(**r))
            n += 1
        db.commit()
    return n


async def run_precompute_locations(market: str, tickers: list[str]) -> None:
    """Background runner: index fact→location pointers for a set of tickers, tracked as
    an IngestionJob (visible in /admin/jobs). Best-effort per ticker."""
    from app.store.jobs import finish_job, start_job, update_progress

    tickers = tickers or []
    job = await asyncio.to_thread(start_job, "locations", market, ",".join(tickers), len(tickers))
    matched = 0
    try:
        for i, tk in enumerate(tickers, 1):
            try:
                res = await precompute_locations_for_ticker(market, tk)
                matched += res.get("matched", 0)
            except Exception:  # noqa: BLE001 — one ticker never aborts the run
                pass
            await asyncio.to_thread(update_progress, job, i)
        await asyncio.to_thread(finish_job, job, "success", matched)
    except Exception as exc:  # noqa: BLE001
        await asyncio.to_thread(finish_job, job, "error", matched, str(exc))


def lookup_location(market: str, accession: str, concept: str, report_period, cik: str | None = None):
    """The single indexed, matched FactLocation row for the /evidence endpoint (or None).

    ``concept`` may be a comma-separated CANDIDATE list (e.g.
    ``RevenueFromContractWithCustomerExcludingAssessedTax,Revenues,SalesRevenueNet``) — the
    same field maps to different us-gaap tags across filers, so we try each in order and
    return the first match. Keyed by (market, accession, concept, report_period): the
    accession already uniquely identifies the filer+filing, so `cik` is intentionally NOT a
    filter (it's stored 10-digit zero-padded and callers pass it inconsistently)."""
    init_db()
    rp = _as_date(report_period)
    candidates = [c.split(":")[-1].strip() for c in concept.split(",") if c.strip()]
    with SessionLocal() as db:
        for bare in candidates:  # honor candidate order (first present tag wins)
            row = db.execute(
                select(FactLocation).where(
                    FactLocation.market == market.upper(),
                    FactLocation.accession_number == accession,
                    FactLocation.concept == bare,
                    FactLocation.report_period == rp,
                    FactLocation.status == "matched",
                )
            ).scalars().first()
            if row:
                return row
    return None
