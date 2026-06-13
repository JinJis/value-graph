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
