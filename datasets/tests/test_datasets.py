"""Unit + integration tests for the US+KR datasets API.

Mapping logic is tested against synthetic upstream payloads (no network); a few
end-to-end checks use FastAPI's TestClient; one provider path is exercised with
respx-mocked SEC responses.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app
from datetime import date

from app.filters import ReportPeriodFilters
from app.providers.kr.opendart import (
    INCOME_MAP as KR_INCOME,
    _amount,
    _extract,
    _fiscal_period,
    _kr_date,
)
from app.providers.us.sec_edgar import (
    INCOME_MAP as US_INCOME,
    _assemble,
    _parse_13f,
    _parse_form4,
    _ttm_value,
)
from app.symbols import Market, build_ref, normalize_ticker

client = TestClient(app)


# --- symbol normalization -------------------------------------------------
def test_normalize_us_ticker():
    assert normalize_ticker(Market.US, "aapl") == "AAPL"


def test_normalize_kr_ticker_strips_suffix_and_pads():
    assert normalize_ticker(Market.KR, "5930") == "005930"
    assert normalize_ticker(Market.KR, "005930.KS") == "005930"
    assert normalize_ticker(Market.KR, "035720.KQ") == "035720"


def test_normalize_kr_rejects_alpha():
    with pytest.raises(ValueError):
        normalize_ticker(Market.KR, "AAPL")


def test_build_ref_requires_identifier():
    with pytest.raises(ValueError):
        build_ref(Market.US)


# --- US XBRL assembler ----------------------------------------------------
def test_us_assemble_income_picks_latest_annual():
    gaap = {
        "Revenues": {
            "units": {
                "USD": [
                    {"start": "2023-01-01", "end": "2023-12-31", "val": 1000, "form": "10-K", "fy": 2023, "fp": "FY", "accn": "A"},
                    {"start": "2022-01-01", "end": "2022-12-31", "val": 800, "form": "10-K", "fy": 2022, "fp": "FY", "accn": "B"},
                    {"start": "2023-07-01", "end": "2023-09-30", "val": 250, "form": "10-Q", "fy": 2023, "fp": "Q3", "accn": "C"},
                ]
            }
        },
        "NetIncomeLoss": {
            "units": {"USD": [{"start": "2023-01-01", "end": "2023-12-31", "val": 100, "form": "10-K", "fy": 2023, "fp": "FY", "accn": "A"}]}
        },
    }
    rows = _assemble(gaap, US_INCOME, US_INCOME["revenue"] + US_INCOME["net_income"], "annual", 4, instant=False, cik10="0000000001")
    assert len(rows) == 2  # two annual periods, the 10-Q excluded
    assert rows[0]["report_period"] == "2023-12-31"
    assert rows[0]["revenue"] == 1000
    assert rows[0]["net_income"] == 100
    assert rows[0]["accession_number"] == "A"


def test_us_assemble_quarterly_filters_by_duration():
    gaap = {
        "Revenues": {
            "units": {"USD": [
                {"start": "2023-07-01", "end": "2023-09-30", "val": 250, "form": "10-Q", "fy": 2023, "fp": "Q3", "accn": "C"},
                {"start": "2023-01-01", "end": "2023-12-31", "val": 1000, "form": "10-K", "fy": 2023, "fp": "FY", "accn": "A"},
            ]}
        },
    }
    rows = _assemble(gaap, US_INCOME, US_INCOME["revenue"], "quarterly", 4, instant=False, cik10="1")
    assert len(rows) == 1
    assert rows[0]["revenue"] == 250


# --- KR DART extraction ---------------------------------------------------
def test_kr_amount_parsing():
    assert _amount("1,234,567") == 1234567.0
    assert _amount("-") is None
    assert _amount("") is None


def test_kr_extract_income_by_account_id():
    rows = [
        {"sj_div": "IS", "account_id": "ifrs-full_Revenue", "thstrm_amount": "300,000"},
        {"sj_div": "BS", "account_id": "ifrs-full_Assets", "thstrm_amount": "9,000"},
        {"sj_div": "CIS", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "50,000"},
    ]
    out = _extract(rows, KR_INCOME, {"IS", "CIS"})
    assert out["revenue"] == 300000.0
    assert out["net_income"] == 50000.0
    assert "total_assets" not in out  # BS row ignored for income map


def test_kr_fiscal_period_labels():
    assert _fiscal_period(2025, "11011") == "2025-FY"
    assert _fiscal_period(2025, "11013") == "2025-Q1"
    assert _fiscal_period(2025, "11014") == "2025-Q3"


# --- US TTM ----------------------------------------------------------------
def test_ttm_value_formula():
    # ttm = last FY (1000) + latest YTD (600) - prior-year YTD (500) = 1100
    gaap = {
        "Revenues": {
            "units": {"USD": [
                {"start": "2024-01-01", "end": "2024-12-31", "val": 1000, "form": "10-K", "fy": 2024, "fp": "FY"},
                {"start": "2025-01-01", "end": "2025-06-30", "val": 600, "form": "10-Q", "fy": 2025, "fp": "Q2"},
                {"start": "2024-01-01", "end": "2024-06-30", "val": 500, "form": "10-Q", "fy": 2024, "fp": "Q2"},
            ]}
        }
    }
    val, end = _ttm_value(gaap, ["Revenues"])
    assert val == 1100
    assert end == "2025-06-30"


def test_ttm_falls_back_to_annual_without_interim():
    gaap = {"Revenues": {"units": {"USD": [
        {"start": "2024-01-01", "end": "2024-12-31", "val": 1000, "form": "10-K", "fy": 2024, "fp": "FY"},
    ]}}}
    val, end = _ttm_value(gaap, ["Revenues"])
    assert val == 1000 and end == "2024-12-31"


# --- report_period filter --------------------------------------------------
def test_report_period_filter_bounds():
    f = ReportPeriodFilters(None, date(2023, 1, 1), date(2023, 12, 31), None, None)
    rows = [
        type("R", (), {"report_period": date(2024, 9, 30)})(),
        type("R", (), {"report_period": date(2023, 9, 30)})(),
    ]
    out = f.apply(rows, 10)
    assert len(out) == 1 and out[0].report_period == date(2023, 9, 30)


def test_report_period_inactive_is_passthrough():
    f = ReportPeriodFilters(None, None, None, None, None)
    assert not f.active
    assert f.fetch_limit(4) == 4


# --- insider / 13F parsers + KR date --------------------------------------
def test_parse_form4():
    xml = """<ownershipDocument>
      <issuer><issuerName>Apple Inc.</issuerName></issuer>
      <reportingOwner>
        <reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isDirector>1</isDirector><officerTitle>CEO</officerTitle></reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable><nonDerivativeTransaction>
        <securityTitle><value>Common Stock</value></securityTitle>
        <transactionDate><value>2026-05-27</value></transactionDate>
        <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
        <transactionAmounts>
          <transactionShares><value>1000</value></transactionShares>
          <transactionPricePerShare><value>200</value></transactionPricePerShare>
          <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
        </transactionAmounts>
        <postTransactionAmounts><sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      </nonDerivativeTransaction></nonDerivativeTable>
    </ownershipDocument>"""
    issuer, owner, title, is_dir, txns = _parse_form4(xml, "AAPL")
    assert issuer == "Apple Inc." and owner == "DOE JANE" and title == "CEO" and is_dir is True
    assert len(txns) == 1
    assert txns[0]["shares"] == -1000  # disposal -> negative
    assert txns[0]["price"] == 200 and txns[0]["owned_after"] == 5000


def test_parse_13f_with_namespace():
    xml = """<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
      <infoTable>
        <nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
        <cusip>037833100</cusip><value>1000</value>
        <shrsOrPrnAmt><sshPrnamt>50</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
      </infoTable>
    </informationTable>"""
    rows = _parse_13f(xml, "2026-03-31", "2026-05-15", "13F-HR", "ACCN")
    assert len(rows) == 1
    assert rows[0].name_of_issuer == "APPLE INC" and rows[0].cusip == "037833100"
    assert rows[0].shares == 50 and rows[0].value_usd == 1000


def test_kr_date_normalization():
    assert _kr_date("20240607") == "2024-06-07"
    assert _kr_date("2024-06-07") == "2024-06-07"
    assert _kr_date("2024.06.07") == "2024-06-07"
    assert _kr_date("") is None


# --- scheduler + selftest classifier --------------------------------------
def test_resolve_universe_legacy_and_presets():
    from app.store.universes import resolve_universe

    # legacy explicit form
    u = dict((m.value, t) for m, t in resolve_universe("US:AAPL,MSFT;KR:005930"))
    assert u["US"] == ["AAPL", "MSFT"] and u["KR"] == ["005930"]
    # preset ids (comma-separated) resolve to the curated lists, merged per market
    u2 = dict((m.value, t) for m, t in resolve_universe("us_mega,kr_large"))
    assert "AAPL" in u2["US"] and "005930" in u2["KR"]
    # mixed: a preset + an explicit extra ticker for the same market → de-duplicated union
    u3 = dict((m.value, t) for m, t in resolve_universe("us_mega;US:AAPL,TSLA"))
    assert u3["US"].count("AAPL") == 1 and "TSLA" in u3["US"]


def test_scheduler_controls():
    from app.scheduler import Scheduler

    s = Scheduler()
    s.pause()
    assert s.enabled is False
    s.resume()
    assert s.enabled is True
    s.trigger()
    assert s._force is True


def test_selftest_classifier():
    from app.selftest import _classify

    assert _classify(200, "{}")[0] == "pass"
    assert _classify(503, "FRED served a bot-verification challenge")[0] == "skipped"
    assert _classify(400, "OPENDART_API_KEY is not configured.")[0] == "skipped"
    assert _classify(404, "not found")[0] == "fail"


# --- app-level (no upstream) ----------------------------------------------
def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_macro_banks_static():
    body = client.get("/macro/interest-rates/banks?market=KR").json()
    assert body["banks"][0]["bank"] == "BOK"


def test_scaffold_returns_501():
    r = client.get("/financials/segments?ticker=AAPL&market=US")
    assert r.status_code == 501
    assert r.json()["error"] == "Not Implemented"


def test_missing_param_maps_to_400_envelope():
    r = client.get("/prices?market=US&interval=day&start_date=2024-01-01&end_date=2024-01-02")
    assert r.status_code == 400
    assert set(r.json().keys()) == {"error", "message"}


# --- screener over the store ----------------------------------------------
def test_screener_over_store():
    from datetime import date as _date

    from sqlalchemy import delete

    from app.store.db import SessionLocal, init_db
    from app.store.models import FinancialFact
    from app.store.screener import run_line_items, run_screener

    init_db()
    with SessionLocal() as db:
        db.execute(delete(FinancialFact).where(FinancialFact.market == "ZZ"))
        for tk, val in [("ZTESTA", 100.0), ("ZTESTB", 10.0)]:
            db.add(
                FinancialFact(
                    market="ZZ", ticker=tk, statement="income", line_item="revenue", value=val,
                    currency="USD", period="annual", report_period=_date(2025, 1, 1),
                    accession_number="t", source="test",
                )
            )
        db.commit()
    try:
        res = run_screener([{"field": "revenue", "operator": "gt", "value": 50}], 10, "annual", "ZZ")
        assert {r["ticker"] for r in res} == {"ZTESTA"}
        li = run_line_items(["ZTESTA"], ["revenue"], "annual", 1)
        assert li and li[0]["revenue"] == 100.0
    finally:
        with SessionLocal() as db:
            db.execute(delete(FinancialFact).where(FinancialFact.market == "ZZ"))
            db.commit()


# --- PH-1: ingestion jobs + backfill operability --------------------------
async def test_ingestion_job_log_lifecycle_and_list():
    from app.store.db import init_db
    from app.store import jobs as J

    init_db()
    jid = J.start_job("backfill", "US", "AAPL · deep")
    J.finish_job(jid, "success", rows=42)
    listed = J.list_jobs(50)
    mine = next(j for j in listed if j["id"] == jid)
    assert mine["status"] == "success" and mine["rows"] == 42 and mine["market"] == "US"
    assert mine["started_at"] and mine["ended_at"]


async def test_run_backfill_records_job(monkeypatch):
    from app.store.db import init_db
    from app.store import jobs as J

    init_db()

    async def fake_us(tickers=None, zip_path=None, limit=None, on_progress=None):
        return {"AAPL": 120, "MSFT": -1}  # one ok, one per-ticker failure

    monkeypatch.setattr(J, "bulk_load_us", fake_us)
    out = await J.run_backfill("US", ["AAPL", "MSFT"], deep=True, limit=None)
    assert out["status"] == "success" and out["rows"] == 120 and out["failed"] == ["MSFT"]
    row = next(j for j in J.list_jobs(50) if j["id"] == out["job_id"])
    assert row["status"] == "success" and row["rows"] == 120


async def test_run_backfill_records_error(monkeypatch):
    from app.store.db import init_db
    from app.store import jobs as J

    init_db()

    async def boom(tickers=None, zip_path=None, limit=None, on_progress=None):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(J, "bulk_load_us", boom)
    out = await J.run_backfill("US", ["AAPL"], deep=True, limit=None)
    assert out["status"] == "error" and "upstream down" in out["error"]
    row = next(j for j in J.list_jobs(50) if j["id"] == out["job_id"])
    assert row["status"] == "error" and "upstream down" in (row["error"] or "")


def test_admin_jobs_endpoint():
    r = client.get("/admin/jobs")
    assert r.status_code == 200 and "jobs" in r.json()


def test_universe_presets_listed_and_endpoint():
    from app.store.universes import get_preset, list_presets
    ids = {u["id"] for u in list_presets()}
    assert {"us_mega", "us_large", "kr_large"} <= ids
    assert get_preset("us_mega")["market"] == "US" and "AAPL" in get_preset("us_mega")["tickers"]
    assert get_preset("nope") is None
    r = client.get("/admin/universes")
    assert r.status_code == 200 and any(u["id"] == "kr_large" for u in r.json()["universes"])


async def test_run_backfill_by_preset_sets_progress(monkeypatch):
    from app.store.db import init_db
    from app.store import jobs as J

    init_db()
    seen_progress = []

    async def fake_us(tickers=None, zip_path=None, limit=None, on_progress=None):
        for i, _t in enumerate(tickers, 1):
            if on_progress:
                on_progress(i, len(tickers))
        return {t: 10 for t in tickers}

    monkeypatch.setattr(J, "bulk_load_us", fake_us)
    out = await J.run_backfill(preset="us_mega")
    assert out["status"] == "success" and out["rows"] > 0
    row = next(j for j in J.list_jobs(50) if j["id"] == out["job_id"])
    assert row["total"] == row["done"] and row["total"] >= 15  # progressed to completion
    assert row["spec"].startswith("universe:us_mega")
    # unknown preset is rejected
    assert (await J.run_backfill(preset="bogus"))["status"] == "error"


async def test_backfill_guard_blocks_concurrent(monkeypatch):
    from app.store.db import SessionLocal, init_db
    from app.store import jobs as J
    from app.store.models import IngestionJob

    init_db()
    # simulate an in-flight backfill
    with SessionLocal() as db:
        db.add(IngestionJob(kind="backfill", market="US", status="running", total=5, done=1))
        db.commit()
    assert J.backfill_running() is True
    out = await J.run_backfill(market="US", tickers=["AAPL"])
    assert out["status"] == "busy"
    # clean up
    with SessionLocal() as db:
        from sqlalchemy import delete
        db.execute(delete(IngestionJob).where(IngestionJob.status == "running"))
        db.commit()


# --- PH-2b: news → RAG ingestion pipeline -------------------------------------
class _FakeNewsProvider:
    async def news(self, market, ticker, limit):
        from app.models.generated import News

        return [
            News(ticker=ticker, title=f"{ticker} ships record chips", source="Reuters",
                 date="2026-06-14", url="https://news.example/a"),
            News(ticker=ticker, title="", source="X"),  # no title → skipped
        ]


async def test_run_news_ingest_indexes_headlines(monkeypatch):
    from app.store.db import init_db
    from app.store import jobs as J
    from app.store import news_ingest as N

    init_db()
    captured = {}

    async def fake_ingest(rag_url, docs):
        captured["rag_url"], captured["docs"] = rag_url, docs
        return len(docs)

    monkeypatch.setattr(N, "get_news_provider", lambda mkt: _FakeNewsProvider())
    monkeypatch.setattr(N, "_ingest_to_rag", fake_ingest)
    out = await N.run_news_ingest("US", ["AAPL"], limit=5)

    assert out["status"] == "success" and out["rows"] == 1 and out["docs"] == 1
    doc = captured["docs"][0]
    assert doc["doc_type"] == "news" and doc["ticker"] == "AAPL" and doc["source"] == "Reuters"
    assert doc["text"].startswith("AAPL") and "tenant" not in doc  # global corpus
    row = next(j for j in J.list_jobs(50) if j["id"] == out["job_id"])
    assert row["kind"] == "news" and row["status"] == "success" and row["done"] == row["total"]


async def test_run_news_ingest_records_error(monkeypatch):
    from app.store.db import init_db
    from app.store import jobs as J
    from app.store import news_ingest as N

    init_db()

    async def boom(rag_url, docs):
        raise RuntimeError("rag unreachable")

    monkeypatch.setattr(N, "get_news_provider", lambda mkt: _FakeNewsProvider())
    monkeypatch.setattr(N, "_ingest_to_rag", boom)
    out = await N.run_news_ingest("US", ["AAPL"])
    assert out["status"] == "error" and "rag unreachable" in out["error"]
    row = next(j for j in J.list_jobs(50) if j["id"] == out["job_id"])
    assert row["status"] == "error"


async def test_news_ingest_guard_blocks_concurrent():
    from app.store.db import SessionLocal, init_db
    from app.store import news_ingest as N
    from app.store.models import IngestionJob

    init_db()
    with SessionLocal() as db:
        db.add(IngestionJob(kind="news", market="US", status="running", total=1, done=0))
        db.commit()
    assert N.news_ingest_running() is True
    out = await N.run_news_ingest("US", ["AAPL"])
    assert out["status"] == "busy"
    with SessionLocal() as db:
        from sqlalchemy import delete
        db.execute(delete(IngestionJob).where(IngestionJob.status == "running"))
        db.commit()


def test_admin_news_ingest_endpoint(monkeypatch):
    # the endpoint fires the pipeline in the background and returns started=True
    import app.routers.admin as A

    async def fake_run(market, tickers, limit=None):
        return {"status": "success"}

    monkeypatch.setattr(A, "run_news_ingest", fake_run)
    monkeypatch.setattr(A, "news_ingest_running", lambda: False)
    r = client.post("/admin/news/ingest", json={"market": "US", "tickers": ["AAPL"]})
    assert r.status_code == 200 and r.json()["started"] is True


async def test_ingest_ticker_builds_evidence_docs_when_flagged(monkeypatch):
    # PH-PROV3: with PRECOMPUTE_LOCATIONS on, a backfill (manual OR scheduled/deep — both go
    # through ingest_ticker) also caches each filing as a PDF so /evidence works — US AND KR.
    import app.store.evidence_docs as ED
    import app.store.ingest as I
    from app.symbols import Market

    class _Prov:
        async def income_statements(self, *a, **k): return []
        async def balance_sheets(self, *a, **k): return []
        async def cash_flow_statements(self, *a, **k): return []
        async def company_facts(self, *a, **k): raise RuntimeError("skip")

    monkeypatch.setattr(I, "build_ref", lambda market, ticker: type("R", (), {"ticker": ticker, "cik": "0"})())
    monkeypatch.setattr(I, "get_financials_provider", lambda m: _Prov())
    monkeypatch.setattr(I, "get_company_provider", lambda m: _Prov())

    calls = []

    async def fake_build(market, ticker, *a, **k):
        calls.append((market, ticker))
        return {}

    monkeypatch.setattr(ED, "build_evidence_docs_for_ticker", fake_build)
    monkeypatch.setattr(I.settings, "precompute_locations", True)

    await I.ingest_ticker(Market.US, "AAPL")
    await I.ingest_ticker(Market.KR, "005930")
    assert calls == [("US", "AAPL"), ("KR", "005930")]   # both markets cache evidence PDFs


# --- PH-5: cheap universe-enumeration endpoints ---------------------------
_SEC_TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}


@respx.mock
def test_ph5_filings_company_earnings_enumerations_us():
    from app.cache import cache
    cache.clear()  # ensure the respx-mocked SEC index is the one used
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=_SEC_TICKERS)
    )
    # filings/tickers + filings/ciks
    rt = client.get("/filings/tickers?market=US")
    assert rt.status_code == 200 and rt.json()["resource"] == "filings"
    assert set(rt.json()["tickers"]) == {"AAPL", "MSFT"}
    rc = client.get("/filings/ciks?market=US")
    assert rc.status_code == 200 and "0000320193" in rc.json()["ciks"]
    # company/facts/ciks + earnings/tickers reuse the same universe
    assert "0000789019" in client.get("/company/facts/ciks?market=US").json()["ciks"]
    assert "MSFT" in client.get("/earnings/tickers?market=US").json()["tickers"]


def test_ph5_kr_list_ciks_uses_corp_code(monkeypatch):
    import asyncio

    from app.providers.kr import opendart

    async def fake_corp_map():
        return {"005930": {"corp_code": "00126380", "corp_name": "삼성전자"}}

    monkeypatch.setattr(opendart, "_corp_map", fake_corp_map)
    assert asyncio.run(opendart.OpenDartProvider().list_ciks()) == ["00126380"]


def test_ph5_prices_snapshot_market_skips_unpriceable(monkeypatch):
    import app.routers.prices as P
    from app.models.generated import PriceSnapshot

    monkeypatch.setattr(P, "store_tickers", lambda market, limit: ["AAPL", "MSFT"])

    class _Prov:
        async def snapshot(self, ref):
            if ref.ticker == "MSFT":
                raise RuntimeError("no price")  # skipped, never fabricated
            return PriceSnapshot(ticker=ref.ticker, price=185.6)

    monkeypatch.setattr(P, "get_prices_provider", lambda market: _Prov())
    r = client.get("/prices/snapshot/market?market=US&limit=10")
    assert r.status_code == 200
    snaps = r.json()["snapshots"]
    assert len(snaps) == 1 and snaps[0]["ticker"] == "AAPL"


def test_ph5_endpoints_no_longer_scaffold_501(monkeypatch):
    # /prices/snapshot/market used to be a scaffolded 501; now a real route
    import app.routers.prices as P
    monkeypatch.setattr(P, "store_tickers", lambda market, limit: [])
    assert client.get("/prices/snapshot/market?market=US").status_code == 200


# --- PH-6: historical financial-metrics (store-backed ratios) -------------
def test_ph6_metrics_history_derives_ratios_and_growth():
    from datetime import date

    from sqlalchemy import delete

    from app.store.db import SessionLocal, init_db
    from app.store.metrics_history import metrics_history
    from app.store.models import FinancialFact

    init_db()

    def fact(rp, item, val, accn="0000320193-25-000079", cik="320193"):
        return FinancialFact(market="US", ticker="ZZTEST", statement="x", line_item=item,
                             value=val, period="annual", report_period=rp, source="SEC EDGAR",
                             accession_number=accn, cik=cik)

    with SessionLocal() as db:
        db.execute(delete(FinancialFact).where(FinancialFact.ticker == "ZZTEST"))
        rows = []
        for rp, rev, gp, ni in [(date(2024, 12, 31), 100.0, 40.0, 10.0),
                                (date(2025, 12, 31), 120.0, 60.0, 24.0)]:
            rows += [fact(rp, "revenue", rev), fact(rp, "gross_profit", gp), fact(rp, "net_income", ni),
                     fact(rp, "total_assets", 200.0), fact(rp, "shareholders_equity", 80.0),
                     fact(rp, "current_assets", 50.0), fact(rp, "current_liabilities", 25.0)]
        db.add_all(rows)
        db.commit()

    hist = metrics_history("US", "ZZTEST", "annual", 8)
    assert len(hist) == 2
    latest = hist[0]  # newest first → 2025
    # each period ties to the exact filing its inputs came from (per-figure provenance)
    assert latest["accession_number"] == "0000320193-25-000079"
    assert latest["filing_url"].endswith("/0000320193-25-000079-index.htm")
    assert abs(latest["gross_margin"] - 0.5) < 1e-9       # 60/120
    assert abs(latest["net_margin"] - 0.2) < 1e-9         # 24/120
    assert abs(latest["return_on_equity"] - 0.3) < 1e-9   # 24/80
    assert abs(latest["current_ratio"] - 2.0) < 1e-9      # 50/25
    assert abs(latest["revenue_growth"] - 0.2) < 1e-9     # (120-100)/100
    assert hist[1].get("revenue_growth") is None          # oldest period has no prior → null, not faked

    with SessionLocal() as db:
        db.execute(delete(FinancialFact).where(FinancialFact.ticker == "ZZTEST"))
        db.commit()


@respx.mock
def test_ph7_as_reported_returns_raw_xbrl():
    from app.cache import cache
    cache.clear()
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}))
    respx.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json").mock(
        return_value=httpx.Response(200, json={"facts": {"us-gaap": {
            "Revenues": {"label": "Revenues", "units": {"USD": [
                {"end": "2024-09-28", "start": "2023-10-01", "val": 391035000000, "form": "10-K",
                 "fy": 2024, "fp": "FY", "filed": "2024-11-01", "accn": "acc-1"}]}},
            "Assets": {"label": "Assets", "units": {"USD": [
                {"end": "2024-09-28", "val": 352755000000, "form": "10-K",
                 "fy": 2024, "fp": "FY", "filed": "2024-11-01", "accn": "acc-1"}]}},
        }}}))
    r = client.get("/financials/as-reported?ticker=AAPL&market=US&period=annual")
    assert r.status_code == 200  # was a scaffolded 501
    body = r.json()
    assert body["ticker"] == "AAPL" and body["periods"]
    p = body["periods"][0]
    assert p["report_period"] == "2024-09-28"
    concepts = {it["concept"]: it["value"] for it in p["line_items"]}
    assert concepts["Revenues"] == 391035000000.0 and concepts["Assets"] == 352755000000.0  # raw, as filed


def test_ph6_metrics_history_endpoint_no_longer_501(monkeypatch):
    import app.routers.metrics as M
    from app.models.generated import FinancialMetricsResponse

    monkeypatch.setattr(M, "metrics_history_models",
                        lambda market, ticker, period, limit: [FinancialMetricsResponse(ticker="AAPL", gross_margin=0.46)])
    r = client.get("/financial-metrics?ticker=AAPL&market=US&period=annual")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "AAPL" and body["period"] == "annual"
    assert body["metrics"][0]["gross_margin"] == 0.46


# --- one provider path with mocked upstream -------------------------------
@respx.mock
def test_us_company_facts_with_mocked_sec():
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})
    )
    respx.get("https://data.sec.gov/submissions/CIK0000320193.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Apple Inc.",
                "tickers": ["AAPL"],
                "exchanges": ["Nasdaq"],
                "sic": "3571",
                "sicDescription": "Electronic Computers",
                "category": "Large accelerated filer",
                "addresses": {"business": {"city": "CUPERTINO", "stateOrCountry": "CA"}},
            },
        )
    )
    r = client.get("/company/facts?ticker=AAPL&market=US")
    assert r.status_code == 200
    facts = r.json()["company_facts"]
    assert facts["name"] == "Apple Inc."
    assert facts["cik"] == "0000320193"
    assert facts["exchange"] == "Nasdaq"


# --- company search (U1-01) ----------------------------------------------
def test_rank_company_matches_orders_exact_prefix_substring():
    from app.providers.search_util import rank_company_matches

    rows = [
        {"ticker": "AAPL", "name": "Apple Inc."},
        {"ticker": "APP", "name": "Applovin Corp"},
        {"ticker": "MSFT", "name": "Microsoft (pineapple supplier)"},
    ]
    # "app": exact ticker (APP) first, then ticker-prefix (AAPL), then name-substring (MSFT).
    out = [r["ticker"] for r in rank_company_matches("app", rows)]
    assert out == ["APP", "AAPL", "MSFT"]
    # empty query → no matches; non-matching query → dropped.
    assert rank_company_matches("", rows) == []
    assert rank_company_matches("zzz", rows) == []


@respx.mock
def test_company_search_us_route():
    from app.cache import cache

    cache.clear()  # don't inherit a prior test's ticker index
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json={
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
            "2": {"cik_str": 1018724, "ticker": "AMZN", "title": "Amazon Com Inc"},
        })
    )
    r = client.get("/company/search?q=app&market=US&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "SEC EDGAR"
    assert body["query"] == "app"
    results = body["results"]
    assert results and results[0]["ticker"] == "AAPL"  # ticker-prefix beats name-substring
    assert results[0]["market"] == "US"
    assert results[0]["cik"] == "0000320193"
    cache.clear()


def test_company_search_kr_provider(monkeypatch):
    import asyncio

    from app.providers.kr import opendart

    async def fake_corp_map():
        return {
            "005930": {"corp_code": "00126380", "corp_name": "삼성전자"},
            "006400": {"corp_code": "00126186", "corp_name": "삼성SDI"},
            "000660": {"corp_code": "00164779", "corp_name": "SK하이닉스"},
        }

    monkeypatch.setattr(opendart, "_corp_map", fake_corp_map)
    results = asyncio.run(opendart.OpenDartProvider().search_companies("삼성", 10))
    names = [r.name for r in results]
    assert "삼성전자" in names and "삼성SDI" in names
    assert all(r.market == "KR" for r in results)
    assert "SK하이닉스" not in names  # not a 삼성 match
    # ticker lookup works too
    by_code = asyncio.run(opendart.OpenDartProvider().search_companies("005930", 10))
    assert by_code[0].name == "삼성전자"


# ==========================================================================
# Expanded coverage: helpers, providers, store, ops, and app-level integration
# ==========================================================================

# --- errors ---------------------------------------------------------------
def test_error_helper_status_codes():
    from app.errors import bad_request, not_found, not_implemented, service_unavailable, unauthorized

    assert bad_request("x").status_code == 400
    assert unauthorized().status_code == 401
    assert not_found("x").status_code == 404
    assert not_implemented("x").status_code == 501
    assert service_unavailable("x").status_code == 503


# --- cache ----------------------------------------------------------------
async def test_ttl_cache_caches():
    from app.cache import TTLCache

    c = TTLCache(60)
    calls = []

    async def factory():
        calls.append(1)
        return 42

    assert await c.get_or_set("k", factory) == 42
    assert await c.get_or_set("k", factory) == 42
    assert len(calls) == 1  # second call served from cache


# --- symbols --------------------------------------------------------------
def test_kr_market_suffix():
    from app.symbols import kr_market_suffix

    assert kr_market_suffix("005930", "KOSPI") == "005930.KS"
    assert kr_market_suffix("035720", "KOSDAQ") == "035720.KQ"


def test_build_ref_with_cik_only():
    r = build_ref(Market.US, cik="320193")
    assert r.cik == "320193" and r.ticker == ""


# --- US XBRL helpers ------------------------------------------------------
def test_filing_url_and_fiscal_label():
    from app.providers.us.sec_edgar import _filing_url, _fiscal_label

    # the filing *index page*, not the bare directory listing
    assert _filing_url("0000320193", "0000320193-25-000079") == \
        "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm"
    assert _filing_url("1", None) is None
    assert _fiscal_label({"fy": 2025, "fp": "FY"}) == "2025-FY"
    assert _fiscal_label({}) is None


def test_filing_link_canonical_per_market():
    from app.store.provenance import filing_link
    # US → SEC index page (needs CIK)
    assert filing_link("US", "0000320193-25-000079", "320193") == \
        "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm"
    assert filing_link("US", "0000320193-25-000079", None) is None  # no CIK → no SEC link
    # KR → DART rcpNo viewer (deterministic from the receipt number alone)
    assert filing_link("KR", "20260605000073") == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260605000073"
    assert filing_link("US", None, "320193") is None


def test_days_between():
    from app.providers.us.sec_edgar import _days_between

    assert _days_between("2025-06-30", "2024-06-30") == 365
    assert _days_between("bad", "x") == 10**6


def test_latest_instant_rows():
    from app.providers.us.sec_edgar import BALANCE_MAP, _latest_instant_rows

    gaap = {"Assets": {"units": {"USD": [
        {"end": "2025-12-31", "val": 1000, "form": "10-Q", "fy": 2025},
        {"end": "2024-12-31", "val": 900, "form": "10-K", "fy": 2024},
    ]}}}
    rows = _latest_instant_rows(gaap, BALANCE_MAP, ["Assets"], 1)
    assert rows[0]["report_period"] == "2025-12-31" and rows[0]["total_assets"] == 1000


def test_parse_13f_no_namespace_and_putcall():
    from app.providers.us.sec_edgar import _parse_13f

    xml = (
        "<informationTable><infoTable><nameOfIssuer>X CORP</nameOfIssuer>"
        "<cusip>000000000</cusip><value>5</value>"
        "<shrsOrPrnAmt><sshPrnamt>2</sshPrnamt></shrsOrPrnAmt><putCall>Put</putCall></infoTable>"
        "</informationTable>"
    )
    rows = _parse_13f(xml, None, None, "13F-HR", "A")
    assert len(rows) == 1 and rows[0].name_of_issuer == "X CORP"
    assert rows[0].value_usd == 5 and rows[0].shares == 2 and rows[0].put_call is not None


# --- KR DART helpers ------------------------------------------------------
def test_kr_extract_balance_and_cashflow():
    from app.providers.kr.opendart import BALANCE_MAP as KB, CASHFLOW_MAP as KC, _extract

    b = [{"sj_div": "BS", "account_id": "ifrs-full_Assets", "thstrm_amount": "1,000"}]
    assert _extract(b, KB, {"BS"})["total_assets"] == 1000.0
    c = [{"sj_div": "CF", "account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities", "thstrm_amount": "50"}]
    assert _extract(c, KC, {"CF"})["net_cash_flow_from_operations"] == 50.0


def test_kr_periods_annual_and_quarterly():
    from app.providers.kr.opendart import _periods

    annual = _periods("annual", 3)
    assert all(code == "11011" for _, code, _ in annual) and annual[0][2].endswith("-12-31")
    quarterly = _periods("quarterly", 2)
    assert any(code in ("11013", "11012", "11014") for _, code, _ in quarterly)


# --- yahoo / stooq / news / fred / ecos provider helpers ------------------
def test_yahoo_symbols_intervals_at():
    from app.providers.us.yahoo import _INTERVALS, _at, _symbols
    from app.symbols import SecurityRef

    assert _symbols(SecurityRef(Market.US, "AAPL")) == ["AAPL"]
    assert _symbols(SecurityRef(Market.KR, "005930")) == ["005930.KS", "005930.KQ"]
    assert _INTERVALS["day"] == "1d" and _INTERVALS["year"] == "1mo"
    assert _at([1, 2, 3], 1) == 2 and _at([1], 5) is None and _at(None, 0) is None


def test_stooq_parse_and_price():
    from app.providers.us.stooq import _parse_csv, _to_price

    rows = _parse_csv("Date,Open,High,Low,Close,Volume\n2024-01-02,1,2,0.5,1.5,100\n")
    assert len(rows) == 1
    p = _to_price(rows[0])
    assert p.close == 1.5 and p.volume == 100 and p.time == "2024-01-02"
    assert _parse_csv("<html>blocked</html>") == []


def test_news_to_date():
    from app.providers.news import _to_date

    assert _to_date("Mon, 09 Jun 2026 12:00:00 GMT") == "2026-06-09"
    assert _to_date(None) is None and _to_date("garbage") is None


async def test_news_query_for_us():
    from app.providers.news import _query_for

    assert await _query_for(Market.US, "AAPL") == "AAPL stock"
    assert await _query_for(Market.US, None) == "stock market"


def test_fred_series_and_rate():
    import pytest

    from app.errors import APIError
    from app.providers.us.fred import _series, _to_rate

    assert _series("FED")[1] == "DFEDTARU"
    with pytest.raises(APIError):
        _series("NOPE")
    assert _to_rate("FED", "Fed", {"value": "5.5", "date": "2025-01-01"}).rate == 5.5
    assert _to_rate("FED", "Fed", {"value": ".", "date": "x"}) is None


def test_ecos_helpers():
    from datetime import date as _date

    from app.providers.kr.ecos import _bank, _fmt, _to_iso

    assert _to_iso("20250101", "D") == "2025-01-01"
    assert _to_iso("202501", "M") == "2025-01-01"
    assert _fmt(_date(2025, 1, 1), "D") == "20250101"
    assert _bank("BOK")[1] == "722Y001"


# --- PH-MACRO: DBnomics (BIS) cloud-safe macro + FRED fallback ------------
def test_dbnomics_helpers():
    import pytest

    from datetime import date as _date

    from app.errors import APIError
    from app.providers.us.dbnomics import _parse_period, _series, _to_rate

    assert _series("FED")[1] == "US"
    assert _series("ecb")[1] == "XM"  # case-insensitive; euro area
    with pytest.raises(APIError):
        _series("NOPE")
    assert _parse_period("2025-07-08") == _date(2025, 7, 8)
    assert _parse_period("2025-06") == _date(2025, 6, 1)  # monthly tolerated
    assert _parse_period("garbage") is None
    assert _to_rate("FED", "Fed", "2025-07-08", 4.375).rate == 4.375
    assert _to_rate("FED", "Fed", "2025-07-08", "NA") is None  # missing marker
    assert _to_rate("FED", "Fed", "bad-period", 4.0) is None


_DBN_URL = "https://api.db.nomics.world/v22/series/BIS/WS_CBPOL"


@respx.mock
async def test_dbnomics_provider_mocked():
    from datetime import date as _date

    from app.providers.us.dbnomics import DBnomicsProvider

    payload = {"series": {"docs": [{"series_code": "D.US",
                                    "period": ["2025-05-01", "2025-06-01", "2025-07-08"],
                                    "value": ["NA", 4.25, 4.375]}]}}
    respx.get(f"{_DBN_URL}/D.US").mock(return_value=httpx.Response(200, json=payload))

    p = DBnomicsProvider()
    rows = await p.interest_rates("FED", None, None)
    assert [r.rate for r in rows] == [4.25, 4.375]  # "NA" dropped, never faked
    assert rows[0].date == "2025-06-01" and rows[0].name == "U.S. Federal Reserve"
    snap = await p.snapshot("FED")
    assert snap[0].rate == 4.375 and snap[0].date == "2025-07-08"
    filtered = await p.interest_rates("FED", _date(2025, 7, 1), None)
    assert [r.rate for r in filtered] == [4.375]


@respx.mock
async def test_auto_macro_keyless_uses_dbnomics(monkeypatch):
    from app.config import settings
    from app.providers.us.macro_auto import AutoMacroProvider

    payload = {"series": {"docs": [{"period": ["2025-06-01", "2025-07-08"], "value": ["NA", 2.0]}]}}
    respx.get(f"{_DBN_URL}/D.XM").mock(return_value=httpx.Response(200, json=payload))

    monkeypatch.setattr(settings, "fred_api_key", "")
    rows = await AutoMacroProvider().interest_rates("ECB", None, None)
    assert [r.rate for r in rows] == [2.0]
    assert rows[0].name == "European Central Bank"


@respx.mock
async def test_auto_macro_falls_back_when_fred_bot_walled(monkeypatch):
    from app.config import settings
    from app.providers.us.macro_auto import AutoMacroProvider

    # FRED serves the JS bot-wall (200 but HTML, not JSON) → upstream_error → fallback.
    respx.get("https://api.stlouisfred.org/fred/series/observations").mock(
        return_value=httpx.Response(200, text="<html>window.location.replace('/x')</html>"))
    payload = {"series": {"docs": [{"period": ["2025-07-08"], "value": [4.375]}]}}
    respx.get(f"{_DBN_URL}/D.US").mock(return_value=httpx.Response(200, json=payload))

    monkeypatch.setattr(settings, "fred_api_key", "test-key")
    snap = await AutoMacroProvider().snapshot("FED")
    assert snap[0].rate == 4.375 and snap[0].bank == "FED"


# --- report_period filter operators ---------------------------------------
def test_report_period_filter_gt_lt():
    from datetime import date as _date

    from app.filters import ReportPeriodFilters

    rows = [type("R", (), {"report_period": _date(2022, 1, 1)})(), type("R", (), {"report_period": _date(2024, 1, 1)})()]
    gt = ReportPeriodFilters(None, None, None, _date(2023, 1, 1), None)
    assert [r.report_period.year for r in gt.apply(rows, 10)] == [2024]
    lt = ReportPeriodFilters(None, None, None, None, _date(2023, 1, 1))
    assert [r.report_period.year for r in lt.apply(rows, 10)] == [2022]


# --- screener operators + restatement -------------------------------------
def test_screener_operators():
    from app.store.screener import _OPS

    assert _OPS["gte"](5, 5) and _OPS["lt"](3, 5) and _OPS["lte"](5, 5)
    assert _OPS["gt"](6, 5) and _OPS["eq"](2, 2) and not _OPS["eq"](1, 2)


def test_screener_restatement_latest_filing_wins():
    from datetime import date as _date

    from sqlalchemy import delete

    from app.store.db import SessionLocal, init_db
    from app.store.models import FinancialFact
    from app.store.screener import run_line_items

    init_db()
    with SessionLocal() as db:
        db.execute(delete(FinancialFact).where(FinancialFact.market == "ZR"))
        for accn, fdate, val in [("orig", _date(2025, 2, 1), 100.0), ("restated", _date(2025, 8, 1), 120.0)]:
            db.add(FinancialFact(
                market="ZR", ticker="ZR1", statement="income", line_item="revenue", value=val,
                currency="USD", period="annual", report_period=_date(2024, 12, 31),
                filing_date=fdate, accession_number=accn, source="t",
            ))
        db.commit()
    try:
        li = run_line_items(["ZR1"], ["revenue"], "annual", 1)
        assert li and li[0]["revenue"] == 120.0  # later filing wins (restatement)
    finally:
        with SessionLocal() as db:
            db.execute(delete(FinancialFact).where(FinancialFact.market == "ZR"))
            db.commit()


# --- scheduler ------------------------------------------------------------
def test_resolve_universe_edges():
    from app.store.universes import resolve_universe

    assert resolve_universe("") == []
    assert resolve_universe("garbage") == []   # unknown preset id → nothing
    assert resolve_universe("US:") == []        # empty ticker list dropped
    u = resolve_universe("us:aapl")
    assert u[0][0] is Market.US and u[0][1] == ["aapl"]


async def test_scheduler_run_once_runs_pipelines(monkeypatch):
    # PH-PIPE: a sweep dispatches the configured pipelines over the universe via run_pipelines.
    from app import scheduler as sched_mod
    from app.scheduler import Scheduler

    calls = []

    async def fake_run_pipelines(market, tickers, pipeline_ids):
        calls.append((market, tuple(tickers), tuple(pipeline_ids)))
        return {pid: "ok" for pid in pipeline_ids}

    monkeypatch.setattr(sched_mod, "run_pipelines", fake_run_pipelines)
    s = Scheduler()
    s.universe = [(Market.US, ["AAPL"])]
    s.pipeline_ids = ["financials", "prices"]
    s.enabled = True
    await s._run_once()
    assert s.last_status == "ok" and s.run_count == 1
    assert calls == [("US", ("AAPL",), ("financials", "prices"))]
    assert s.last_summary == {"US": {"financials": "ok", "prices": "ok"}}


async def test_run_pipelines_dispatches_and_isolates_failures(monkeypatch):
    import app.pipelines as P

    ran = []

    async def ok_runner(market, tickers):
        ran.append(("ok", market))

    async def boom_runner(market, tickers):
        raise RuntimeError("upstream down")

    monkeypatch.setitem(P.PIPELINE_BY_ID["prices"], "runner", ok_runner)
    monkeypatch.setitem(P.PIPELINE_BY_ID["financials"], "runner", boom_runner)
    summary = await P.run_pipelines("US", ["AAPL"], ["financials", "prices"])
    assert summary["financials"].startswith("error")   # one failing pipeline…
    assert summary["prices"] == "ok"                     # …never sinks the others
    assert ("ok", "US") in ran


# --- selftest classifier --------------------------------------------------
def test_selftest_classifier_cases():
    from app.selftest import _classify

    assert _classify(200, "{}")[0] == "pass"
    assert _classify(402, "Active subscription required")[0] == "fail"
    assert _classify(503, "bot-verification challenge")[0] == "skipped"
    assert _classify(400, "OPENDART_API_KEY is not configured.")[0] == "skipped"
    assert _classify(500, "boom")[0] == "fail"


# --- app-level integration (no upstream network) --------------------------
def test_admin_scheduler_endpoint():
    body = client.get("/admin/scheduler").json()
    assert "enabled" in body and "run_count" in body


def test_admin_store_stats_endpoint():
    body = client.get("/admin/store/stats").json()
    assert "total_facts" in body and "by_market" in body
    # PH-PIPE: prices + corporate-actions coverage is reported too
    assert "price_bars" in body and "corporate_actions" in body


def test_admin_pipelines_endpoint():
    body = client.get("/admin/pipelines").json()
    ids = {p["id"] for p in body["pipelines"]}
    assert {"financials", "prices", "corp_actions", "news"} <= ids
    prices = next(p for p in body["pipelines"] if p["id"] == "prices")
    assert prices["store"] == "price_bars" and "latest" in prices
    assert body["scheduler"]["state"] in ("enabled", "paused", "running")


def test_admin_pipelines_run_dispatches(monkeypatch):
    import app.routers.admin as A

    seen = {}

    async def fake_run_pipelines(market, tickers, ids):
        seen["call"] = (market, tuple(tickers), tuple(ids))

    monkeypatch.setattr(A, "run_pipelines", fake_run_pipelines)
    r = client.post("/admin/pipelines/run", json={"preset": "us_mega", "pipelines": ["prices"]})
    body = r.json()
    assert r.status_code == 200 and body["started"] is True and body["pipelines"] == ["prices"]
    assert body["universe"][0]["market"] == "US"


async def test_prices_ingest_shapes_and_upserts(monkeypatch):
    import app.store.prices_ingest as PI
    from datetime import date

    class _Bar:
        def __init__(self, **k):
            self.__dict__.update(k)

        def model_dump(self):
            return dict(self.__dict__)

    class FakeProv:
        async def prices(self, ref, interval, start, end):
            return [_Bar(time="2024-01-02", open=10, high=11, low=9, close=10.5, volume=1000),
                    _Bar(time="bad-date", open=1, high=1, low=1, close=1, volume=1)]  # dropped

    monkeypatch.setattr(PI, "get_prices_provider", lambda m: FakeProv())
    added = []

    class FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            class _R:
                def scalar_one_or_none(self_inner):
                    return None
            return _R()

        def add(self, o):
            added.append(o)

        def commit(self):
            pass

    monkeypatch.setattr(PI, "SessionLocal", lambda: FakeDB())
    n = await PI.ingest_prices_ticker(PI.Market.US, "AAPL", date(2024, 1, 1), date(2024, 1, 3))
    assert n == 1  # the unparseable-date bar is dropped, never fabricated
    assert added[0].ticker == "AAPL" and added[0].close == 10.5 and added[0].bar_date == date(2024, 1, 2)


def test_bad_period_returns_400():
    r = client.get("/financials/income-statements?ticker=AAPL&market=US&period=monthly")
    assert r.status_code == 400 and r.json()["error"] == "Bad Request"


def test_missing_identifier_returns_400():
    r = client.get("/financials/income-statements?market=US&period=annual")
    assert r.status_code == 400


def test_invalid_market_enum_returns_400():
    r = client.get("/company/facts?ticker=AAPL&market=ZZ")
    assert r.status_code == 400


def test_invalid_interval_returns_400():
    r = client.get("/prices?ticker=AAPL&market=US&interval=hour&start_date=2024-01-01&end_date=2024-01-02")
    assert r.status_code == 400


def test_screener_no_match_returns_empty():
    r = client.post(
        "/financials/search/screener?market=US",
        json={"limit": 5, "filters": [{"field": "revenue", "operator": "gt", "value": 1e18}]},
    )
    assert r.status_code == 200 and r.json()["search_results"] == []


def test_institutional_requires_exactly_one_arg():
    r = client.get("/institutional-holdings")  # neither filer_cik nor ticker
    assert r.status_code == 400


def test_more_scaffold_501s():
    for path in ("/kpi/metrics", "/financials/segments?ticker=AAPL", "/institutional-holdings/tickers"):
        assert client.get(path).status_code == 501


# --- bulk backfill --------------------------------------------------------
def test_all_facts_from_companyfacts_multi_period():
    from app.providers.us.sec_edgar import all_facts_from_companyfacts

    gaap = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"start": "2020-01-01", "end": "2020-12-31", "val": 100, "form": "10-K", "fy": 2020, "fp": "FY", "accn": "a"},
            {"start": "2021-01-01", "end": "2021-12-31", "val": 110, "form": "10-K", "fy": 2021, "fp": "FY", "accn": "b"},
            {"start": "2021-07-01", "end": "2021-09-30", "val": 30, "form": "10-Q", "fy": 2021, "fp": "Q3", "accn": "c"},
        ]}},
        "Assets": {"units": {"USD": [{"end": "2021-12-31", "val": 500, "form": "10-K", "fy": 2021}]}},
    }}}
    rows = all_facts_from_companyfacts(gaap, "0000000001")
    periods = {(r["statement"], r["period"], r["report_period"]) for r in rows}
    assert ("income", "annual", "2020-12-31") in periods
    assert ("income", "annual", "2021-12-31") in periods
    assert ("income", "quarterly", "2021-09-30") in periods
    assert ("balance", "annual", "2021-12-31") in periods


async def test_bulk_zip_loads(monkeypatch, tmp_path):
    import json as _json
    import zipfile as _zip

    from sqlalchemy import delete, func, select

    from app.store import bulk
    from app.store.db import SessionLocal, init_db
    from app.store.models import FinancialFact

    async def fake_index():
        return {"ZBULK": {"cik_str": 9000001, "ticker": "ZBULK", "title": "Z"}}

    monkeypatch.setattr(bulk, "_ticker_index", fake_index)
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2022-01-01", "end": "2022-12-31", "val": 500, "form": "10-K", "fy": 2022, "fp": "FY", "accn": "x"},
    ]}}}}}
    zp = tmp_path / "cf.zip"
    with _zip.ZipFile(zp, "w") as zf:
        zf.writestr("CIK0009000001.json", _json.dumps(facts))
    init_db()
    with SessionLocal() as db:
        db.execute(delete(FinancialFact).where(FinancialFact.ticker == "ZBULK"))
        db.commit()
    try:
        res = await bulk.bulk_load_us(zip_path=str(zp))
        assert res.get("ZBULK", 0) > 0
        with SessionLocal() as db:
            n = db.scalar(select(func.count()).select_from(FinancialFact).where(FinancialFact.ticker == "ZBULK"))
        assert n and n > 0
    finally:
        with SessionLocal() as db:
            db.execute(delete(FinancialFact).where(FinancialFact.ticker == "ZBULK"))
            db.commit()


# --- connector catalog (P0) -----------------------------------------------
def test_catalog_manifests_valid():
    from app.connectors.catalog import get_catalog

    cons = get_catalog()
    assert cons, "catalog is empty"
    ids = [c.id for c in cons]
    assert len(ids) == len(set(ids)), "duplicate connector ids"
    for c in cons:
        assert c.id and c.name and c.domain and c.markets and c.resources
        assert c.license is not None and isinstance(c.license.redistribution, bool)
        for r in c.resources:
            assert r.name and r.path.startswith("/")
            assert r.provenance and r.provenance.source  # trust envelope present


def test_ticker_is_required_where_a_company_is_mandatory():
    # A user/agent must name a company for price + fundamentals pulls — the manifest
    # (and thus the MCP/OpenAPI schema) must mark ticker required there, so clients
    # can't issue a doomed call. company_facts (cik alternative) + news stay optional.
    from app.connectors.catalog import get_catalog

    by_id = {c.id: c for c in get_catalog()}

    def ticker_required(connector_id: str, resource_name: str) -> bool:
        res = next(r for r in by_id[connector_id].resources if r.name == resource_name)
        return any(p.name == "ticker" and p.required for p in res.params)

    for cid, rname in [
        ("yahoo", "prices"), ("yahoo", "price_snapshot"),
        ("sec_edgar", "income_statements"), ("sec_edgar", "earnings"), ("sec_edgar", "metrics_snapshot"),
        ("opendart", "income_statements"), ("opendart", "earnings"), ("opendart", "metrics_snapshot"),
    ]:
        assert ticker_required(cid, rname), f"{cid}.{rname} must require ticker"

    # …but endpoints with an alternative or a general mode keep it optional
    assert not ticker_required("sec_edgar", "company_facts")  # cik works instead
    assert not ticker_required("google_news", "news")          # general feed


def test_catalog_resource_paths_are_real_routes():
    from fastapi.routing import APIRoute

    from app.connectors.catalog import all_resource_paths
    from app.main import app

    real = {(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in r.methods}
    for method, path in all_resource_paths():
        assert (method, path) in real, f"manifest references a non-existent route: {method} {path}"


def test_catalog_endpoints():
    body = client.get("/catalog").json()
    assert body["count"] > 0 and len(body["connectors"]) == body["count"]
    cid = body["connectors"][0]["id"]
    one = client.get(f"/catalog/{cid}")
    assert one.status_code == 200 and one.json()["id"] == cid
    assert client.get("/catalog/does-not-exist").status_code == 404


def test_catalog_restricted_license_flagged():
    # Yahoo + news must be marked non-redistributable (governance signal).
    from app.connectors.catalog import get_connector

    assert get_connector("yahoo").license.redistribution is False
    assert get_connector("google_news").license.redistribution is False
    assert get_connector("sec_edgar").license.redistribution is True


# --- RAG connector in the catalog (routed to the rag service) -------------
def test_catalog_has_rag_connector_routed_to_rag_service():
    from app.connectors.catalog import all_resource_paths, get_connector

    rag = get_connector("rag")
    assert rag is not None and rag.service == "rag"
    assert any(r.path == "/rag/search" and r.method == "POST" for r in rag.resources)
    # rag paths are served elsewhere, so excluded from the data-plane integrity set
    assert ("POST", "/rag/search") not in all_resource_paths()
    assert ("POST", "/rag/search") in all_resource_paths(service="rag")
    assert rag.license.redistribution is False


# --- PH-PROV3: PDF-normalized evidence document store ---------------------
async def test_ph_prov3_ensure_doc_caches_kr_official_pdf(tmp_path, monkeypatch):
    """KR uses DART's official PDF directly (Chromium-free); it's written to the data
    volume + indexed as an EvidenceDoc, and the second call is served from cache."""
    import app.store.evidence_docs as ED
    from app.config import settings

    monkeypatch.setattr(settings, "evidence_docs_dir", str(tmp_path))
    calls = {"n": 0}

    async def _fake_pdf(rcept):
        calls["n"] += 1
        return b"%PDF-1.4 official-dart"

    monkeypatch.setattr(ED, "fetch_dart_pdf", _fake_pdf)

    r1 = await ED.ensure_doc("KR", "005930", "20260310002820",
                             canonical_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260310002820")
    assert r1 == "stored"
    assert (tmp_path / "KR" / "20260310002820.pdf").read_bytes().startswith(b"%PDF")
    doc = ED.get_evidence_doc("KR", "20260310002820")
    assert doc and doc["status"] == "stored" and "dart.fss.or.kr" in doc["source_url"]

    r2 = await ED.ensure_doc("KR", "005930", "20260310002820", canonical_url="x")  # idempotent
    assert r2 == "cached" and calls["n"] == 1  # no second fetch


@respx.mock
async def test_ph_prov3_ensure_doc_us_renders_via_chromium(tmp_path, monkeypatch):
    """US has no official PDF → iXBRL HTML is rendered to PDF once by the renderer."""
    import app.store.evidence_docs as ED
    from app.config import settings

    monkeypatch.setattr(settings, "evidence_docs_dir", str(tmp_path))

    async def _fake_markup(accession, fetch_url):
        return "<html><body><table><tr><td>Revenue</td><td>391,035</td></tr></table></body></html>"

    monkeypatch.setattr(ED, "_us_markup", _fake_markup)
    respx.post("http://renderer:8006/pdf/from-html").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.7 us", headers={"content-type": "application/pdf"}))

    r = await ED.ensure_doc("US", "AAPL", "0000320193-24-000123",
                            fetch_url="https://www.sec.gov/x.htm", canonical_url="https://www.sec.gov/i.htm")
    assert r == "stored"
    assert (tmp_path / "US" / "0000320193-24-000123.pdf").read_bytes().startswith(b"%PDF")


def _make_pdf(path, line):
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 200), line)
    doc.save(str(path))
    doc.close()


def test_ph_prov3b_pymupdf_highlight(tmp_path, monkeypatch):
    """PyMuPDF locates the cited value (at the millions scale) next to its label, highlights
    it, and rasterizes a PNG — cache-first; a value not present returns None (graceful)."""
    from app.config import settings
    from app.store.evidence_render import highlight_png, labels_for

    monkeypatch.setattr(settings, "evidence_docs_dir", str(tmp_path))
    pdf = tmp_path / "us.pdf"
    _make_pdf(pdf, "Net sales      391,035")  # millions, as a 10-K renders it
    labels = labels_for("US", "Revenues")
    assert "Net sales" in labels

    png = highlight_png(str(pdf), 391_035_000_000.0, labels)
    assert png and png.startswith(b"\x89PNG")
    assert highlight_png(str(pdf), 391_035_000_000.0, labels) == png      # cache hit
    assert highlight_png(str(pdf), 999.0, labels) is None                 # value absent → None


def test_ph_prov3b_evidence_pdf_endpoint(tmp_path, monkeypatch):
    """/evidence highlights the cited figure in the cached PDF; /evidence/doc serves the PDF."""
    from app.config import settings
    from app.store.evidence_docs import _upsert_doc

    monkeypatch.setattr(settings, "evidence_docs_dir", str(tmp_path))
    pdf = tmp_path / "us.pdf"
    _make_pdf(pdf, "Net sales      391,035")  # ASCII fixture → US 'Net sales' label anchors deterministically
    _upsert_doc({"market": "US", "ticker": "AAPL", "accession_number": "0000320193-24-000123",
                 "source_url": "https://www.sec.gov/...-index.htm",
                 "pdf_path": str(pdf), "page_count": 1, "status": "stored"})

    r = client.get("/evidence?market=US&accession=0000320193-24-000123&concept=Revenues"
                   "&report_period=2024-09-28&value=391035000000")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"

    d = client.get("/evidence/doc?market=US&accession=0000320193-24-000123")
    assert d.status_code == 200 and d.headers["content-type"] == "application/pdf"
    assert client.get("/evidence/doc?market=US&accession=NOPE").status_code == 204


def test_ph_prov3a_admin_evidence_docs_endpoint(monkeypatch):
    import app.routers.admin as A

    fired: dict = {}

    async def _fake_run(market, tickers):
        fired["market"], fired["tickers"] = market, tickers

    monkeypatch.setattr(A, "run_build_evidence_docs", _fake_run)
    assert client.post("/admin/evidence-docs", json={"market": "KR", "tickers": ["005930"]}).json()["started"] is True
    assert fired == {"market": "KR", "tickers": ["005930"]}
    # unsupported market / no tickers → not started
    assert client.post("/admin/evidence-docs", json={"market": "JP", "tickers": ["7203"]}).json()["started"] is False
    assert client.post("/admin/evidence-docs", json={"market": "US"}).json()["started"] is False


# --- PH-PROV3e: filing PDF text → RAG corpus ------------------------------
def test_ph_prov3e_pdf_to_docs(tmp_path):
    """Each non-empty PDF page → one RAG IngestDoc carrying accession + section (p.N) so a
    search hit points back to the exact page for evidence highlighting."""
    import fitz

    from app.store.filing_ingest import _pdf_to_docs

    pdf = tmp_path / "f.pdf"
    d = fitz.open()
    d.new_page().insert_text((72, 200), "Net sales were 391,035; risks include supply concentration.")
    d.new_page()  # 2nd page near-empty → skipped
    d.save(str(pdf))
    d.close()

    docs = _pdf_to_docs(str(pdf), "US", "AAPL", "0000320193-24-000123", "SEC EDGAR", "https://sec.gov/x")
    assert len(docs) == 1  # empty page dropped
    doc = docs[0]
    assert doc["section"] == "p.1" and doc["accession"] == "0000320193-24-000123"
    assert doc["doc_type"] == "filing" and doc["ticker"] == "AAPL" and doc["market"] == "US"
    assert "Net sales" in doc["text"]


def test_ph_prov3e_admin_filings_ingest_endpoint(monkeypatch):
    import app.routers.admin as A

    fired: dict = {}

    async def _fake_run(market, tickers):
        fired["market"], fired["tickers"] = market, tickers

    monkeypatch.setattr(A, "run_filing_text_ingest", _fake_run)
    assert client.post("/admin/filings/ingest", json={"market": "US", "tickers": ["AAPL"]}).json()["started"] is True
    assert fired == {"market": "US", "tickers": ["AAPL"]}
    assert client.post("/admin/filings/ingest", json={"market": "JP", "tickers": ["7203"]}).json()["started"] is False


def test_ph_prov3e_text_evidence_endpoint(tmp_path, monkeypatch):
    """/evidence text mode highlights a cited PASSAGE in the cached filing PDF."""
    from app.config import settings
    from app.store.evidence_docs import _upsert_doc

    monkeypatch.setattr(settings, "evidence_docs_dir", str(tmp_path))
    pdf = tmp_path / "f.pdf"
    _make_pdf(pdf, "Net sales were 391,035 and supply chain risks remain significant.")
    _upsert_doc({"market": "US", "ticker": "AAPL", "accession_number": "0000320193-24-000123",
                 "source_url": "https://sec.gov/i.htm", "pdf_path": str(pdf), "page_count": 1, "status": "stored"})

    r = client.get("/evidence", params={"market": "US", "accession": "0000320193-24-000123",
                                        "text": "Net sales were 391,035 and supply chain risks remain"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    # a passage that isn't in the doc → 204 (graceful)
    r2 = client.get("/evidence", params={"market": "US", "accession": "0000320193-24-000123",
                                         "text": "totally unrelated sentence not present anywhere here"})
    assert r2.status_code == 204


# --- PH-8: index-fund / ETF holdings (SEC N-PORT) -------------------------
_NPORT = """<edgarSubmission><formData>
 <genInfo><regName>Test S&amp;P 500 ETF Trust</regName><regCik>0000884394</regCik><repPdDate>2026-03-31</repPdDate></genInfo>
 <fundInfo><totAssets>1000.00</totAssets><netAssets>950.00</netAssets></fundInfo>
 <invstOrSecs>
  <invstOrSec><name>Apple Inc</name><title>Apple Inc</title><cusip>037833100</cusip>
   <identifiers><isin value="US0378331005"/></identifiers>
   <balance>100.0</balance><units>NS</units><valUSD>500.0</valUSD><pctVal>52.6</pctVal><assetCat>EC</assetCat></invstOrSec>
  <invstOrSec><name>Microsoft Corp</name><cusip>594918104</cusip>
   <balance>50.0</balance><units>NS</units><valUSD>300.0</valUSD><pctVal>31.6</pctVal><assetCat>EC</assetCat></invstOrSec>
 </invstOrSecs>
</formData></edgarSubmission>"""


def test_ph8_nport_parse():
    from app.providers.us.sec_edgar import _parse_nport

    meta, holdings = _parse_nport(_NPORT)
    assert meta["name"] == "Test S&P 500 ETF Trust" and meta["cik"] == "0000884394"
    assert meta["as_of"] == "2026-03-31" and meta["net_assets"] == 950.0
    assert len(holdings) == 2
    aapl = holdings[0]
    assert aapl.cusip == "037833100" and aapl.isin == "US0378331005"
    assert aapl.shares == 100.0 and aapl.market_value == 500.0
    assert abs(aapl.weight - 0.526) < 1e-9      # pctVal 52.6 → fraction


def test_ph8_index_funds_endpoint(monkeypatch):
    import app.routers.funds as F
    from app.models.generated import Fund, FundHolding

    class _Fake:
        async def holdings(self, ref, limit):
            return (Fund(name="SPDR S&P 500 ETF Trust", cik="0000884394", source="SEC EDGAR (N-PORT)",
                         total_net_assets=6.5e11, total_holdings=2, returned=2),
                    [FundHolding(name="Apple Inc", cusip="037833100", weight=0.07,
                                 market_value=4.5e10, shares=1.0, asset_class="EC")])

    monkeypatch.setattr(F, "get_fund_provider", lambda m: _Fake())
    b = client.get("/index-funds?ticker=SPY&market=US").json()
    assert b["ticker"] == "SPY" and b["fund"]["name"].startswith("SPDR")
    assert b["holdings"][0]["cusip"] == "037833100"
    # reverse direction → 501; neither/both → 400
    assert client.get("/index-funds?holding=AAPL&market=US").status_code == 501
    assert client.get("/index-funds").status_code == 400
    t = client.get("/index-funds/tickers").json()
    assert "SPY" in t["tickers"] and t["resource"] == "index_funds"


# --- PH-DATA-1: superinvestor (거장) 13F portfolios -----------------------
def test_phdata1_gurus_list_and_holdings(monkeypatch):
    from app.models.generated import InstitutionalHolding
    import app.routers.gurus as G

    # list mode → curated registry (every entry has a verified CIK)
    body = client.get("/gurus").json()
    slugs = {g["slug"] for g in body["gurus"]}
    assert {"buffett", "burry", "ackman"} <= slugs
    assert all(g["cik"] and g["investor"] for g in body["gurus"])

    # slug mode → that filer's 13F holdings (provider mocked; each carries an accession)
    class _Fake:
        async def by_filer(self, cik, limit):
            assert cik == "0001067983"
            return [InstitutionalHolding(name_of_issuer="Apple Inc", cusip="037833100",
                                         value_usd=1000, accession_number="0001067983-26-000001")]
    monkeypatch.setattr(G, "get_institutional_provider", lambda m: _Fake())
    b = client.get("/gurus?slug=buffett&limit=5").json()
    assert b["guru"]["investor"] == "Warren Buffett" and b["filer_cik"] == "0001067983"
    assert b["holdings"][0]["cusip"] == "037833100"
    assert b["holdings"][0]["accession_number"] == "0001067983-26-000001"  # → provenance to SEC 13F

    # unknown slug → 404
    assert client.get("/gurus?slug=nobody").status_code == 404


# --- PH-DATA-2: peer valuation comparables --------------------------------
def test_phdata2_comparables(monkeypatch):
    from app.models.generated import FinancialMetricSnapshot
    import app.routers.metrics as M

    class _Fake:
        async def metrics_snapshot(self, ref):
            return FinancialMetricSnapshot(ticker=ref.ticker, price_to_earnings_ratio=30.0,
                                           net_margin=0.25, return_on_equity=0.5)

    monkeypatch.setattr(M, "get_metrics_provider", lambda m: _Fake())
    b = client.get("/comparables?tickers=AAPL,MSFT,GOOGL&market=US").json()
    assert b["market"] == "US" and b["tickers"] == ["AAPL", "MSFT", "GOOGL"]
    assert len(b["comparables"]) == 3
    assert b["comparables"][0]["price_to_earnings_ratio"] == 30.0
    assert client.get("/comparables?tickers=&market=US").status_code == 400  # no tickers


# --- PH-DATA-3: corporate actions (dividends + splits) --------------------
@respx.mock
async def test_phdata3_yahoo_corporate_actions_parse():
    from datetime import date as _date

    from app.providers.us.yahoo import YahooProvider
    from app.symbols import Market, build_ref

    payload = {"chart": {"result": [{"meta": {"currency": "USD"}, "events": {
        "dividends": {"1": {"amount": 0.24, "date": 1700000000}, "2": {"amount": 0.25, "date": 1710000000}},
        "splits": {"1": {"date": 1598880600, "numerator": 4.0, "denominator": 1.0, "splitRatio": "4:1"}},
    }}]}}
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/AAPL").mock(
        return_value=httpx.Response(200, json=payload))
    data = await YahooProvider().corporate_actions(build_ref(Market.US, "AAPL"), _date(2020, 1, 1), _date(2026, 1, 1))
    assert data["currency"] == "USD"
    assert [d["amount"] for d in data["dividends"]] == [0.25, 0.24]  # newest first
    assert data["splits"][0]["ratio"] == "4:1"


def test_phdata3_corporate_actions_endpoint(monkeypatch):
    import app.routers.corporate_actions as C

    class _Fake:
        async def corporate_actions(self, ref, start, end):
            return {"currency": "USD",
                    "dividends": [{"ex_date": "2026-02-07", "amount": 0.25}],
                    "splits": [{"date": "2020-08-31", "ratio": "4:1", "numerator": 4.0, "denominator": 1.0}]}

    monkeypatch.setattr(C, "get_prices_provider", lambda m: _Fake())
    b = client.get("/corporate-actions?ticker=AAPL&market=US&years=10").json()
    assert b["ticker"] == "AAPL" and b["currency"] == "USD"
    assert b["dividends"][0]["amount"] == 0.25 and b["splits"][0]["ratio"] == "4:1"


# --- PH-DATA-4: economic indicators DB (DBnomics) -------------------------
@respx.mock
async def test_phdata4_indicators_fetch():
    from app.providers.macro_indicators import fetch_indicator, list_indicators

    payload = {"series": {"docs": [{"period": ["2025-11", "2025-12"], "value": ["NA", 319.1]}]}}
    respx.get("https://api.db.nomics.world/v22/series/BLS/cu/CUSR0000SA0").mock(
        return_value=httpx.Response(200, json=payload))
    res = await fetch_indicator("cpi", 24)
    assert res["source"] == "DBnomics" and res["source_url"].endswith("BLS/cu/CUSR0000SA0")
    assert res["observations"] == [{"date": "2025-12", "value": 319.1}]  # "NA" dropped, never faked
    assert any(i["slug"] == "cpi" for i in list_indicators())
    assert await fetch_indicator("nope") is None


def test_phdata4_indicators_endpoint():
    b = client.get("/macro/indicators").json()  # list mode, no upstream
    assert b["resource"] == "economic_indicators"
    assert {"cpi", "unemployment", "gdp_growth"} <= {i["slug"] for i in b["indicators"]}
    assert client.get("/macro/indicators?indicator=nope").status_code == 404  # unknown → 404


# --- PH-DATA-6: technical indicators (descriptive, computed from prices) ----
def test_phdata6_compute_funcs():
    from app.store.technical import _sma, _ema, _rsi, _macd, _bbands, _volatility
    c = [float(x) for x in range(1, 41)]  # strictly rising
    sma = _sma(c, 5)
    assert sma[3] is None and sma[4] == 3.0          # mean(1..5) = 3
    ema = _ema(c, 5)
    assert ema[3] is None and ema[4] == 3.0          # seeded with the SMA
    rsi = _rsi(c, 14)
    assert rsi[13] is None and rsi[14] == 100.0      # all gains → RSI 100
    macd, signal, hist = _macd(c)
    assert macd[24] is None and macd[25] is not None  # defined once both EMAs exist
    assert signal[-1] is not None and hist[-1] is not None
    up, mid, lo = _bbands(c, 5)
    assert up[4] > mid[4] > lo[4]                     # bands straddle the middle
    assert _volatility(c, 20)[-1] is not None


async def test_phdata6_endpoint(monkeypatch):
    import app.store.technical as T
    from datetime import date, timedelta
    from app.models.generated import Price
    base = date(2024, 1, 1)
    series = [Price(time=str(base + timedelta(days=i)), open=100.0 + i, high=100.0 + i,
                    low=100.0 + i, close=100.0 + i, volume=1000) for i in range(40)]

    class _FakeP:
        async def prices(self, ref, interval, start, end):
            return series
    monkeypatch.setattr(T, "get_prices_provider", lambda m: _FakeP())

    b = client.get("/technical-indicators?ticker=AAPL&indicators=sma_5,rsi_14,macd&interval=day").json()
    assert b["ticker"] == "AAPL" and b["source"].startswith("Technical indicators")
    assert b["as_of"] == str(base + timedelta(days=39)) and b["note"]  # descriptive label present
    assert {i["key"] for i in b["indicators"]} == {"sma_5", "rsi_14", "macd"}
    sma = next(i for i in b["indicators"] if i["key"] == "sma_5")
    assert sma["pane"] == "price" and sma["lines"][0]["latest"] is not None  # sourced latest, not faked
    macd = next(i for i in b["indicators"] if i["key"] == "macd")
    assert {ln["label"] for ln in macd["lines"]} == {"MACD", "Signal", "Histogram"}


def test_phdata6_bad_interval_400():
    assert client.get("/technical-indicators?ticker=AAPL&interval=minute").status_code == 400
