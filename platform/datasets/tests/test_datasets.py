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
def test_parse_universe():
    from app.scheduler import parse_universe

    u = parse_universe("US:AAPL,MSFT;KR:005930")
    assert u[0][0].value == "US" and u[0][1] == ["AAPL", "MSFT"]
    assert u[1][0].value == "KR" and u[1][1] == ["005930"]


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
    r = client.get("/index-funds?ticker=SPY")
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

    async def fake_us(tickers=None, zip_path=None, limit=None):
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

    async def boom(tickers=None, zip_path=None, limit=None):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(J, "bulk_load_us", boom)
    out = await J.run_backfill("US", ["AAPL"], deep=True, limit=None)
    assert out["status"] == "error" and "upstream down" in out["error"]
    row = next(j for j in J.list_jobs(50) if j["id"] == out["job_id"])
    assert row["status"] == "error" and "upstream down" in (row["error"] or "")


def test_admin_jobs_endpoint():
    r = client.get("/admin/jobs")
    assert r.status_code == 200 and "jobs" in r.json()


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

    assert _filing_url("0000320193", "0000320193-25-000079").endswith("/000032019325000079/")
    assert _filing_url("1", None) is None
    assert _fiscal_label({"fy": 2025, "fp": "FY"}) == "2025-FY"
    assert _fiscal_label({}) is None


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
def test_parse_universe_edges():
    from app.scheduler import parse_universe

    assert parse_universe("") == []
    assert parse_universe("garbage") == []
    assert parse_universe("US:") == []
    u = parse_universe("us:aapl")
    assert u[0][0] is Market.US and u[0][1] == ["aapl"]


async def test_scheduler_run_once_ingests(monkeypatch):
    from app import scheduler as sched_mod
    from app.scheduler import Scheduler

    async def fake_ingest(market, tickers, *a, **k):
        return {t: 3 for t in tickers}

    monkeypatch.setattr(sched_mod, "ingest_universe", fake_ingest)
    s = Scheduler()
    s.universe = [(Market.US, ["AAPL"])]
    s.enabled = True
    await s._run_once()
    assert s.last_status == "ok" and s.run_count == 1
    assert s.last_summary == {"US": {"AAPL": 3}}


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
    for path in ("/index-funds?ticker=SPY", "/kpi/metrics", "/financials/as-reported?ticker=AAPL&period=annual"):
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
