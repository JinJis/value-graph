"""Bulk / deep-history backfill into the ingestion store.

Two US paths:
  * per-ticker **deep** — pull a ticker's full companyfacts and load *every*
    annual + quarterly period (not just the latest N).
  * **zip** — stream SEC ``companyfacts.zip`` (all companies, all history) and
    load every company that maps to a ticker. This is the production full-universe
    path; it needs the ~1GB zip downloaded locally.

KR path iterates DART per ticker over a deep year range (reuses the live provider).
All paths feed the same point-in-time ``FinancialFact`` writer.
"""

from __future__ import annotations

import asyncio
import json
import zipfile
from datetime import date

from app.providers.registry import get_company_provider
from app.providers.us.sec_edgar import (
    _cik10,
    _company_facts_raw,
    _resolve_cik,
    _ticker_index,
    all_facts_from_companyfacts,
)
from app.store.db import SessionLocal, init_db
from app.store.ingest import _upsert_fact, ingest_ticker
from app.store.models import Company
from app.symbols import Market, build_ref


def _to_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _write(market: Market, ticker: str, cik: str | None, source: str, currency: str, rows: list[dict], company=None) -> int:
    with SessionLocal() as db:
        for r in rows:
            _upsert_fact(
                db,
                {
                    "market": market.value, "ticker": ticker, "cik": cik, "statement": r["statement"],
                    "line_item": r["line_item"], "value": r["value"], "currency": currency, "period": r["period"],
                    "report_period": _to_date(r["report_period"]), "fiscal_period": r.get("fiscal_period"),
                    "filing_date": None, "accession_number": r.get("accession_number") or "", "source": source,
                },
            )
        if company is not None:
            comp = db.get(Company, (market.value, ticker)) or Company(market=market.value, ticker=ticker)
            comp.name, comp.cik = company.name, company.cik
            comp.sector, comp.exchange, comp.currency = company.sector, company.exchange, currency
            db.merge(comp)
        db.commit()
    return len(rows)


# --- US ------------------------------------------------------------------
async def _load_us_ticker_deep(ticker: str) -> int:
    ref = build_ref(Market.US, ticker)
    cik = await _resolve_cik(ref)
    facts = await _company_facts_raw(cik)
    rows = all_facts_from_companyfacts(facts, cik)
    try:
        company = await get_company_provider(Market.US).company_facts(ref)
    except Exception:
        company = None
    return await asyncio.to_thread(_write, Market.US, ticker.upper(), cik, "sec_edgar", "USD", rows, company)


async def _load_us_zip(zip_path: str, limit: int | None) -> dict:
    idx = await _ticker_index()
    file_to_ticker = {f"CIK{int(r['cik_str']):010d}.json": r["ticker"].upper() for r in idx.values()}

    def _process() -> dict:
        results: dict[str, int] = {}
        with zipfile.ZipFile(zip_path) as zf:
            count = 0
            for name in zf.namelist():
                ticker = file_to_ticker.get(name)
                if not ticker:
                    continue  # only companies that map to a ticker
                try:
                    facts = json.loads(zf.read(name))
                    cik = _cik10(name.replace("CIK", "").replace(".json", ""))
                    results[ticker] = _write(Market.US, ticker, cik, "sec_edgar", "USD", all_facts_from_companyfacts(facts, cik))
                except Exception:
                    results[ticker] = -1
                count += 1
                if limit and count >= limit:
                    break
        return results

    return await asyncio.to_thread(_process)


async def bulk_load_us(tickers: list[str] | None = None, zip_path: str | None = None, limit: int | None = None) -> dict:
    init_db()
    if zip_path:
        return await _load_us_zip(zip_path, limit)
    out: dict[str, int] = {}
    for t in tickers or []:
        try:
            out[t] = await _load_us_ticker_deep(t)
        except Exception as exc:
            out[t] = -1
            print(f"  ! US:{t} failed: {exc}")
    return out


# --- KR ------------------------------------------------------------------
async def bulk_load_kr(tickers: list[str], limit: int = 15) -> dict:
    init_db()
    out: dict[str, int] = {}
    for t in tickers:
        try:
            annual = await ingest_ticker(Market.KR, t, "annual", limit)
            quarterly = await ingest_ticker(Market.KR, t, "quarterly", limit)
            out[t] = annual + quarterly
        except Exception as exc:
            out[t] = -1
            print(f"  ! KR:{t} failed: {exc}")
    return out
