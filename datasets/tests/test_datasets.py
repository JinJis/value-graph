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
from app.providers.kr.opendart import INCOME_MAP as KR_INCOME, _amount, _extract
from app.providers.us.sec_edgar import INCOME_MAP as US_INCOME, _assemble
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


# --- app-level (no upstream) ----------------------------------------------
def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_macro_banks_static():
    body = client.get("/macro/interest-rates/banks?market=KR").json()
    assert body["banks"][0]["bank"] == "BOK"


def test_scaffold_returns_501():
    r = client.get("/news")
    assert r.status_code == 501
    assert r.json()["error"] == "Not Implemented"


def test_missing_param_maps_to_400_envelope():
    r = client.get("/prices?market=US&interval=day&start_date=2024-01-01&end_date=2024-01-02")
    assert r.status_code == 400
    assert set(r.json().keys()) == {"error", "message"}


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
