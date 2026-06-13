"""KR provider backed by OpenDART (금융감독원 전자공시 Open API).

* corp_code map   /api/corpCode.xml   (zip of stock_code <-> corp_code)
* company facts   /api/company.json
* financials      /api/fnlttSinglAcntAll.json
* filings         /api/list.json

OpenDART keys statements by an 8-digit ``corp_code``; the public-facing symbol
is the 6-digit ``stock_code``. The resolver below bridges the two and is cached.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from xml.etree import ElementTree

from app.cache import cache
from app.config import settings
from app.errors import bad_request, not_found, upstream_error
from app.http import fetch_bytes, fetch_json
from app.models.generated import (
    BalanceSheet,
    CashFlowStatement,
    CompanyFacts,
    Filing,
    FinancialMetricSnapshot,
    IncomeStatement,
)
from app.symbols import SecurityRef

_BASE = "https://opendart.fss.or.kr/api"
_CORP_CLS = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX", "E": "ETC"}

# reprt_code -> (period label, fiscal month-end)
_ANNUAL = "11011"
_QUARTER_CODES = [("11014", 9), ("11012", 6), ("11013", 3)]  # Q3, half, Q1 (cumulative)


def _key() -> str:
    if not settings.opendart_api_key:
        raise bad_request("OPENDART_API_KEY is not configured.")
    return settings.opendart_api_key


def _amount(raw: str | None) -> float | None:
    if raw in (None, "", "-"):
        return None
    try:
        return float(str(raw).replace(",", ""))
    except ValueError:
        return None


async def _corp_map() -> dict[str, dict]:
    """stock_code(6) -> {corp_code, corp_name}."""

    async def _load() -> dict[str, dict]:
        content = await fetch_bytes(
            "opendart", f"{_BASE}/corpCode.xml", params={"crtfc_key": _key()}
        )
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
            xml = zf.read(zf.namelist()[0])
        except (zipfile.BadZipFile, IndexError) as exc:
            raise upstream_error("opendart", f"corpCode.xml not a zip: {exc}")
        root = ElementTree.fromstring(xml)
        out: dict[str, dict] = {}
        for node in root.iter("list"):
            stock = (node.findtext("stock_code") or "").strip()
            if stock:
                out[stock.zfill(6)] = {
                    "corp_code": (node.findtext("corp_code") or "").strip(),
                    "corp_name": (node.findtext("corp_name") or "").strip(),
                }
        return out

    return await cache.get_or_set("dart:corp_map", _load)


async def _corp_code(ref: SecurityRef) -> str:
    if ref.cik:
        return ref.cik
    cmap = await _corp_map()
    row = cmap.get(ref.ticker.zfill(6))
    if not row:
        raise not_found(f"Unknown KR issue code '{ref.ticker}'.")
    return row["corp_code"]


async def _dart_json(path: str, params: dict) -> dict:
    params = {"crtfc_key": _key(), **params}
    data = await fetch_json("opendart", f"{_BASE}/{path}", params=params)
    status = data.get("status")  # type: ignore[union-attr]
    if status == "013":  # no data
        return {"status": status, "list": []}
    if status and status != "000":
        raise upstream_error("opendart", f"{status}: {data.get('message')}")
    return data  # type: ignore[return-value]


# --- statement concept maps (account_id -> field) -------------------------
INCOME_MAP = {
    "ifrs-full_Revenue": "revenue",
    "ifrs_Revenue": "revenue",
    "ifrs-full_CostOfSales": "cost_of_revenue",
    "ifrs-full_GrossProfit": "gross_profit",
    "dart_OperatingIncomeLoss": "operating_income",
    "ifrs-full_ProfitLossFromOperatingActivities": "operating_income",
    "ifrs-full_ProfitLoss": "net_income",
    "ifrs-full_IncomeTaxExpenseContinuingOperations": "income_tax_expense",
    "ifrs-full_BasicEarningsLossPerShare": "earnings_per_share",
    "ifrs-full_DilutedEarningsLossPerShare": "earnings_per_share_diluted",
}
BALANCE_MAP = {
    "ifrs-full_Assets": "total_assets",
    "ifrs-full_CurrentAssets": "current_assets",
    "ifrs-full_NoncurrentAssets": "non_current_assets",
    "ifrs-full_CashAndCashEquivalents": "cash_and_equivalents",
    "ifrs-full_Inventories": "inventory",
    "ifrs-full_Liabilities": "total_liabilities",
    "ifrs-full_CurrentLiabilities": "current_liabilities",
    "ifrs-full_NoncurrentLiabilities": "non_current_liabilities",
    "ifrs-full_Equity": "shareholders_equity",
    "ifrs-full_RetainedEarnings": "retained_earnings",
}
CASHFLOW_MAP = {
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": "net_cash_flow_from_operations",
    "ifrs-full_CashFlowsFromUsedInInvestingActivities": "net_cash_flow_from_investing",
    "ifrs-full_CashFlowsFromUsedInFinancingActivities": "net_cash_flow_from_financing",
}


def _extract(rows: list[dict], field_map: dict[str, str], sj_divs: set[str]) -> dict:
    out: dict = {}
    for row in rows:
        if row.get("sj_div") not in sj_divs:
            continue
        field = field_map.get((row.get("account_id") or "").strip())
        if field and field not in out:
            amt = _amount(row.get("thstrm_amount"))
            if amt is not None:
                out[field] = amt
    return out


def _periods(period: str, limit: int) -> list[tuple[int, str, str]]:
    """Return (bsns_year, reprt_code, report_period_date) newest first."""
    this_year = date.today().year
    out: list[tuple[int, str, str]] = []
    if period == "quarterly":
        for year in range(this_year, this_year - 4, -1):
            for code, month in _QUARTER_CODES:
                end_day = 30 if month in (6, 9) else 31
                out.append((year, code, f"{year}-{month:02d}-{end_day:02d}"))
    else:  # annual / ttm
        for year in range(this_year - 1, this_year - 1 - (limit + 3), -1):
            out.append((year, _ANNUAL, f"{year}-12-31"))
    return out[: limit + 4]


class OpenDartProvider:
    async def company_facts(self, ref: SecurityRef) -> CompanyFacts:
        corp = await _corp_code(ref)
        data = await _dart_json("company.json", {"corp_code": corp})
        return CompanyFacts(
            ticker=(data.get("stock_code") or ref.ticker).strip() or ref.ticker,
            name=data.get("corp_name"),
            cik=corp,
            industry=data.get("induty_code"),
            sector=data.get("induty_code"),
            exchange=_CORP_CLS.get(data.get("corp_cls", ""), None),
            is_active=True,
            location=data.get("adres"),
            sic_code=data.get("induty_code"),
        )

    async def list_tickers(self) -> list[str]:
        cmap = await _corp_map()
        return sorted(cmap.keys())

    async def _statements(self, ref, period, limit, field_map, sj_divs, model):
        corp = await _corp_code(ref)
        out = []
        for year, code, rp in _periods(period, limit):
            data = await _dart_json(
                "fnlttSinglAcntAll.json",
                {"corp_code": corp, "bsns_year": str(year), "reprt_code": code, "fs_div": "CFS"},
            )
            rows = data.get("list") or []
            if not rows:
                data = await _dart_json(
                    "fnlttSinglAcntAll.json",
                    {"corp_code": corp, "bsns_year": str(year), "reprt_code": code, "fs_div": "OFS"},
                )
                rows = data.get("list") or []
            fields = _extract(rows, field_map, sj_divs)
            if fields:
                out.append(model(ticker=ref.ticker, report_period=rp, period=period, currency="KRW", **fields))
            if len(out) >= limit:
                break
        if not out:
            raise not_found(f"No OpenDART financial data for '{ref.ticker}'.")
        return out

    async def income_statements(self, ref: SecurityRef, period: str, limit: int) -> list[IncomeStatement]:
        return await self._statements(ref, period, limit, INCOME_MAP, {"IS", "CIS"}, IncomeStatement)

    async def balance_sheets(self, ref: SecurityRef, period: str, limit: int) -> list[BalanceSheet]:
        return await self._statements(ref, period, limit, BALANCE_MAP, {"BS"}, BalanceSheet)

    async def cash_flow_statements(self, ref: SecurityRef, period: str, limit: int) -> list[CashFlowStatement]:
        return await self._statements(ref, period, limit, CASHFLOW_MAP, {"CF"}, CashFlowStatement)

    async def filings(self, ref: SecurityRef, filing_types: list[str] | None, limit: int) -> list[Filing]:
        corp = await _corp_code(ref)
        this_year = date.today().year
        data = await _dart_json(
            "list.json",
            {
                "corp_code": corp,
                "bgn_de": f"{this_year - 2}0101",
                "end_de": f"{this_year}1231",
                "page_count": str(min(limit, 100)),
            },
        )
        out: list[Filing] = []
        for row in data.get("list") or []:
            rcp = row.get("rcept_no")
            rcept_dt = row.get("rcept_dt")  # YYYYMMDD
            fdate = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}" if rcept_dt else None
            out.append(
                Filing(
                    cik=int(corp),
                    accession_number=rcp,
                    filing_type=row.get("report_nm"),
                    filing_date=fdate,
                    report_date=fdate,
                    ticker=ref.ticker,
                    url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}",
                )
            )
            if len(out) >= limit:
                break
        if not out:
            raise not_found(f"No OpenDART filings for '{ref.ticker}'.")
        return out


class OpenDartMetricsProvider:
    """KR metrics derived from OpenDART fundamentals + the live (Yahoo) price.

    market_cap = issued shares x price; P/E = price / EPS; P/B = market_cap /
    equity. Requires OPENDART_API_KEY. Fields that can't be derived are null."""

    async def _shares(self, ref: SecurityRef) -> float | None:
        corp = await _corp_code(ref)
        this_year = date.today().year
        for year in range(this_year - 1, this_year - 4, -1):
            data = await _dart_json(
                "stockTotqySttus.json",
                {"corp_code": corp, "bsns_year": str(year), "reprt_code": _ANNUAL},
            )
            rows = data.get("list") or []
            # prefer the 합계 (total) row, then 보통주 (common)
            for want in ("합계", "보통주"):
                for row in rows:
                    if (row.get("se") or "").strip().startswith(want):
                        n = _amount(row.get("istc_totqy"))
                        if n:
                            return n
        return None

    async def metrics_snapshot(self, ref: SecurityRef) -> FinancialMetricSnapshot:
        from app.providers.us.yahoo import YahooProvider

        provider = OpenDartProvider()
        snap = FinancialMetricSnapshot(ticker=ref.ticker)
        try:
            price = (await YahooProvider().snapshot(ref)).price
        except Exception:
            price = None

        incomes = await provider.income_statements(ref, "annual", 1)
        balances = await provider.balance_sheets(ref, "annual", 1)
        eps = incomes[0].earnings_per_share if incomes else None
        equity = balances[0].shareholders_equity if balances else None
        shares = await self._shares(ref)

        if price and shares:
            snap.market_cap = price * shares
        if price and eps:
            snap.price_to_earnings_ratio = round(price / eps, 4)
        if snap.market_cap and equity:
            snap.price_to_book_ratio = round(snap.market_cap / equity, 4)
        return snap
