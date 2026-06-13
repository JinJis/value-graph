"""US provider backed by the free SEC EDGAR APIs.

* ticker -> CIK     https://www.sec.gov/files/company_tickers.json
* company facts     https://data.sec.gov/submissions/CIK##########.json
* financials (XBRL) https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
* filings           (submissions "recent" block)

SEC requires a descriptive User-Agent and rate-limits to ~10 req/s. Responses
are cached (TTL) so repeat calls don't re-hit EDGAR.
"""

from __future__ import annotations

from datetime import date, datetime

from app.cache import cache
from app.config import settings
from app.errors import not_found, upstream_error
from app.http import fetch_json
from app.models.generated import (
    BalanceSheet,
    CashFlowStatement,
    CompanyFacts,
    Filing,
    FinancialMetricSnapshot,
    IncomeStatement,
    Price,
    PriceSnapshot,
)
from app.symbols import SecurityRef

_UA = {"User-Agent": settings.sec_edgar_user_agent}
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def _cik10(cik: str | int) -> str:
    return str(int(cik)).zfill(10)


async def _ticker_index() -> dict[str, dict]:
    async def _load() -> dict[str, dict]:
        data = await fetch_json("sec_edgar", _TICKERS_URL, headers=_UA)
        out: dict[str, dict] = {}
        for row in data.values():  # type: ignore[union-attr]
            out[row["ticker"].upper()] = row
        return out

    return await cache.get_or_set("sec:ticker_index", _load)


async def _resolve_cik(ref: SecurityRef) -> str:
    if ref.cik:
        return _cik10(ref.cik)
    idx = await _ticker_index()
    row = idx.get(ref.ticker.upper())
    if not row:
        raise not_found(f"Unknown US ticker '{ref.ticker}'.")
    return _cik10(row["cik_str"])


async def _submissions(cik10: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    return await cache.get_or_set(
        f"sec:submissions:{cik10}", lambda: fetch_json("sec_edgar", url, headers=_UA)
    )  # type: ignore[return-value]


async def _company_facts_raw(cik10: str) -> dict:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
    return await cache.get_or_set(
        f"sec:facts:{cik10}", lambda: fetch_json("sec_edgar", url, headers=_UA)
    )  # type: ignore[return-value]


# --- XBRL concept maps (field -> ordered candidate us-gaap tags) ----------
INCOME_MAP: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "gross_profit": ["GrossProfit"],
    "operating_expense": ["OperatingExpenses", "CostsAndExpenses", "OperatingCostsAndExpenses"],
    "selling_general_and_administrative_expenses": [
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    ],
    "research_and_development": ["ResearchAndDevelopmentExpense"],
    "operating_income": ["OperatingIncomeLoss"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating"],
    "income_tax_expense": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "net_income_common_stock": ["NetIncomeLossAvailableToCommonStockholdersBasic"],
    "consolidated_income": ["ProfitLoss"],
    "earnings_per_share": ["EarningsPerShareBasic"],
    "earnings_per_share_diluted": ["EarningsPerShareDiluted"],
    "dividends_per_common_share": ["CommonStockDividendsPerShareDeclared"],
    "weighted_average_shares": ["WeightedAverageNumberOfSharesOutstandingBasic"],
    "weighted_average_shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}

BALANCE_MAP: dict[str, list[str]] = {
    "total_assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "inventory": ["InventoryNet"],
    "trade_and_non_trade_receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "non_current_assets": ["AssetsNoncurrent"],
    "property_plant_and_equipment": ["PropertyPlantAndEquipmentNet"],
    "goodwill_and_intangible_assets": ["Goodwill"],
    "outstanding_shares": ["CommonStockSharesOutstanding"],
    "total_liabilities": ["Liabilities"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "current_debt": ["LongTermDebtCurrent", "DebtCurrent", "CommercialPaper"],
    "trade_and_non_trade_payables": ["AccountsPayableCurrent"],
    "deferred_revenue": ["ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent"],
    "non_current_liabilities": ["LiabilitiesNoncurrent"],
    "non_current_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "tax_liabilities": ["TaxesPayableCurrent"],
    "shareholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
}

CASHFLOW_MAP: dict[str, list[str]] = {
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "depreciation_and_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndOther",
        "Depreciation",
    ],
    "share_based_compensation": ["ShareBasedCompensation", "ShareBasedCompensationExpense"],
    "net_cash_flow_from_operations": ["NetCashProvidedByUsedInOperatingActivities"],
    "capital_expenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "business_acquisitions_and_disposals": ["PaymentsToAcquireBusinessesNetOfCashAcquired"],
    "net_cash_flow_from_investing": ["NetCashProvidedByUsedInInvestingActivities"],
    "issuance_or_repayment_of_debt_securities": ["ProceedsFromIssuanceOfLongTermDebt"],
    "issuance_or_purchase_of_equity_shares": ["PaymentsForRepurchaseOfCommonStock"],
    "dividends_and_other_cash_distributions": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "net_cash_flow_from_financing": ["NetCashProvidedByUsedInFinancingActivities"],
    "change_in_cash_and_equivalents": [
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "CashAndCashEquivalentsPeriodIncreaseDecrease",
    ],
}

_ANNUAL_FORMS = {"10-K", "20-F", "40-F"}
_QUARTER_FORMS = {"10-Q", "6-K"}


def _observations(gaap: dict, concept: str) -> list[dict]:
    node = gaap.get(concept)
    if not node:
        return []
    obs: list[dict] = []
    for unit_rows in node.get("units", {}).values():
        for row in unit_rows:
            obs.append(row)
    return obs


def _duration_days(row: dict) -> int | None:
    start, end = row.get("start"), row.get("end")
    if not start or not end:
        return None
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
    except ValueError:
        return None


def _period_ok(row: dict, period: str, instant: bool) -> bool:
    form = row.get("form")
    if period == "quarterly":
        if form not in _QUARTER_FORMS:
            return False
    else:  # annual / ttm
        if form not in _ANNUAL_FORMS:
            return False
    if not instant:
        days = _duration_days(row)
        if days is None:
            return False
        if period == "quarterly":
            return 50 <= days <= 115
        return 300 <= days <= 400
    return True


def _assemble(
    gaap: dict, field_map: dict[str, list[str]], spine: list[str], period: str, limit: int, instant: bool, cik10: str
) -> list[dict]:
    # 1) enumerate report periods from the spine concepts
    spine_obs = [
        row
        for concept in spine
        for row in _observations(gaap, concept)
        if _period_ok(row, period, instant)
    ]
    # newest first, dedupe by end date
    spine_obs.sort(key=lambda r: (r["end"], r.get("fy", 0)), reverse=True)
    periods: list[dict] = []
    seen: set[str] = set()
    for row in spine_obs:
        if row["end"] in seen:
            continue
        seen.add(row["end"])
        periods.append(row)
        if len(periods) >= limit:
            break

    # 2) for each period, pull each field's value matching that end date
    results: list[dict] = []
    for prow in periods:
        end = prow["end"]
        accn = prow.get("accn")
        rec: dict = {
            "report_period": end,
            "fiscal_period": _fiscal_label(prow),
            "accession_number": accn,
            "filing_url": _filing_url(cik10, accn),
        }
        for field, concepts in field_map.items():
            for concept in concepts:
                match = _value_at(gaap, concept, end, period, instant)
                if match is not None:
                    rec[field] = match
                    break
        results.append(rec)
    return results


def _days_between(end_a: str, end_b: str) -> int:
    try:
        return abs((datetime.fromisoformat(end_a) - datetime.fromisoformat(end_b)).days)
    except ValueError:
        return 10**6


def _ttm_value(gaap: dict, concepts: list[str]) -> tuple[float | None, str | None]:
    """Trailing-twelve-months for a flow concept = last FY + latest YTD interim −
    prior-year YTD interim. Degrades to the last FY value (and its end) when no
    newer interim is available. Returns (value, report_period_end)."""
    obs = [r for c in concepts for r in _observations(gaap, c) if r.get("start") and r.get("end")]
    annual = [r for r in obs if r.get("form") in _ANNUAL_FORMS and 300 <= (_duration_days(r) or 0) <= 400]
    if not annual:
        return None, None
    fy = max(annual, key=lambda r: (r["end"], r.get("fy", 0)))
    fy_end, fy_val = fy["end"], fy.get("val")
    interim = [r for r in obs if r.get("form") in _QUARTER_FORMS and 60 <= (_duration_days(r) or 0) <= 300 and r["end"] > fy_end]
    if not interim or fy_val is None:
        return fy_val, fy_end
    cur = max(interim, key=lambda r: r["end"])
    cur_dd = _duration_days(cur) or 0
    prior = [
        r for r in obs
        if r.get("form") in _QUARTER_FORMS
        and abs((_duration_days(r) or 0) - cur_dd) <= 10
        and abs(_days_between(r["end"], cur["end"]) - 365) <= 25
    ]
    if not prior or cur.get("val") is None:
        return fy_val, cur["end"]
    p = min(prior, key=lambda r: abs(_days_between(r["end"], cur["end"]) - 365))
    if p.get("val") is None:
        return fy_val, cur["end"]
    return fy_val + cur["val"] - p["val"], cur["end"]


def _ttm_rows(gaap: dict, field_map: dict[str, list[str]], spine: list[str]) -> list[dict]:
    _, report_end = _ttm_value(gaap, spine)
    if report_end is None:
        return []
    rec: dict = {"report_period": report_end, "fiscal_period": "TTM"}
    for field, concepts in field_map.items():
        val, _ = _ttm_value(gaap, concepts)
        if val is not None:
            rec[field] = val
    return [rec]


def _latest_instant_rows(gaap: dict, field_map: dict[str, list[str]], spine: list[str], limit: int) -> list[dict]:
    """Balance-sheet TTM: the most recent instant values regardless of form."""
    ends = sorted(
        {r["end"] for c in spine for r in _observations(gaap, c) if r.get("end") and not r.get("start")},
        reverse=True,
    )[:limit]
    rows: list[dict] = []
    for end in ends:
        rec: dict = {"report_period": end, "fiscal_period": "TTM"}
        for field, concepts in field_map.items():
            for concept in concepts:
                cands = [r for r in _observations(gaap, concept) if r.get("end") == end and not r.get("start")]
                if cands:
                    rec[field] = max(cands, key=lambda r: (r.get("fy", 0), r.get("accn", ""))).get("val")
                    break
        rows.append(rec)
    return rows


def _value_at(gaap: dict, concept: str, end: str, period: str, instant: bool) -> float | None:
    candidates = [
        row
        for row in _observations(gaap, concept)
        if row.get("end") == end and _period_ok(row, period, instant)
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda r: (r.get("fy", 0), r.get("accn", "")))
    return best.get("val")


def _fiscal_label(row: dict) -> str | None:
    fy, fp = row.get("fy"), row.get("fp")
    if fy and fp:
        return f"{fy}-{fp}"
    return None


def _filing_url(cik10: str, accn: str | None) -> str | None:
    if not accn:
        return None
    nodash = accn.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{nodash}/"


class SecEdgarProvider:
    # --- company ---------------------------------------------------------
    async def company_facts(self, ref: SecurityRef) -> CompanyFacts:
        cik10 = await _resolve_cik(ref)
        sub = await _submissions(cik10)
        tickers = sub.get("tickers") or []
        exchanges = sub.get("exchanges") or []
        addr = (sub.get("addresses") or {}).get("business") or {}
        location = ", ".join(
            x for x in [addr.get("city"), addr.get("stateOrCountry")] if x
        ) or None
        return CompanyFacts(
            ticker=(tickers[0] if tickers else ref.ticker).upper(),
            name=sub.get("name"),
            cik=cik10,
            industry=sub.get("sicDescription"),
            sector=sub.get("sicDescription"),
            category=sub.get("category"),
            exchange=exchanges[0] if exchanges else None,
            is_active=True,
            location=location,
            sec_filings_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik10}&type=&dateb=&owner=include&count=40",
            sic_code=sub.get("sic"),
            sic_industry=sub.get("sicDescription"),
            sic_sector=sub.get("sicDescription"),
        )

    async def list_tickers(self) -> list[str]:
        idx = await _ticker_index()
        return sorted(idx.keys())

    # --- financial statements -------------------------------------------
    async def income_statements(self, ref: SecurityRef, period: str, limit: int) -> list[IncomeStatement]:
        cik10 = await _resolve_cik(ref)
        facts = await _company_facts_raw(cik10)
        gaap = facts.get("facts", {}).get("us-gaap", {})
        spine = INCOME_MAP["revenue"] + INCOME_MAP["net_income"]
        if period == "ttm":
            rows = _ttm_rows(gaap, INCOME_MAP, spine)
        else:
            rows = _assemble(gaap, INCOME_MAP, spine, period, limit, instant=False, cik10=cik10)
        return [
            IncomeStatement(ticker=ref.ticker, period=period, currency="USD", **r)
            for r in rows
        ]

    async def balance_sheets(self, ref: SecurityRef, period: str, limit: int) -> list[BalanceSheet]:
        cik10 = await _resolve_cik(ref)
        facts = await _company_facts_raw(cik10)
        gaap = facts.get("facts", {}).get("us-gaap", {})
        if period == "ttm":
            rows = _latest_instant_rows(gaap, BALANCE_MAP, ["Assets"], limit)
        else:
            rows = _assemble(gaap, BALANCE_MAP, ["Assets"], period, limit, instant=True, cik10=cik10)
        out = []
        for r in rows:
            cur, noncur = r.get("current_debt"), r.get("non_current_debt")
            if cur is not None or noncur is not None:
                r["total_debt"] = (cur or 0) + (noncur or 0)
            out.append(BalanceSheet(ticker=ref.ticker, period=period, currency="USD", **r))
        return out

    async def cash_flow_statements(self, ref: SecurityRef, period: str, limit: int) -> list[CashFlowStatement]:
        cik10 = await _resolve_cik(ref)
        facts = await _company_facts_raw(cik10)
        gaap = facts.get("facts", {}).get("us-gaap", {})
        spine = ["NetCashProvidedByUsedInOperatingActivities"]
        if period == "ttm":
            rows = _ttm_rows(gaap, CASHFLOW_MAP, spine)
        else:
            rows = _assemble(gaap, CASHFLOW_MAP, spine, period, limit, instant=False, cik10=cik10)
        out = []
        for r in rows:
            ops, capex = r.get("net_cash_flow_from_operations"), r.get("capital_expenditure")
            if ops is not None and capex is not None:
                r["free_cash_flow"] = ops - capex
            out.append(CashFlowStatement(ticker=ref.ticker, period=period, currency="USD", **r))
        return out

    # --- filings ---------------------------------------------------------
    async def filings(self, ref: SecurityRef, filing_types: list[str] | None, limit: int) -> list[Filing]:
        cik10 = await _resolve_cik(ref)
        sub = await _submissions(cik10)
        recent = (sub.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accns = recent.get("accessionNumber") or []
        fdates = recent.get("filingDate") or []
        rdates = recent.get("reportDate") or []
        prim = recent.get("primaryDocument") or []
        wanted = {t.upper() for t in filing_types} if filing_types else None
        out: list[Filing] = []
        for i in range(len(forms)):
            if wanted and forms[i].upper() not in wanted:
                continue
            accn = accns[i]
            nodash = accn.replace("-", "")
            doc = prim[i] if i < len(prim) and prim[i] else ""
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{nodash}/{doc}"
            out.append(
                Filing(
                    cik=int(cik10),
                    accession_number=accn,
                    filing_type=forms[i],
                    report_date=rdates[i] or None if i < len(rdates) else None,
                    filing_date=fdates[i] if i < len(fdates) else None,
                    ticker=ref.ticker,
                    url=url,
                )
            )
            if len(out) >= limit:
                break
        return out


class SecEdgarMetricsProvider:
    """Best-effort US metrics snapshot derived from XBRL + the EOD price feed.

    market_cap = latest reported shares outstanding x latest close. A handful of
    valuation ratios are derived from the most recent annual statement. Fields
    that cannot be derived are left null (honest gaps, not zeros)."""

    async def metrics_snapshot(self, ref: SecurityRef) -> FinancialMetricSnapshot:
        from app.providers.us.yahoo import YahooProvider

        cik10 = await _resolve_cik(ref)
        facts = await _company_facts_raw(cik10)
        gaap = facts.get("facts", {}).get("us-gaap", {})

        shares = _latest(gaap, ["CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding"])
        eps = _latest(gaap, ["EarningsPerShareDiluted", "EarningsPerShareBasic"])
        equity = _latest(gaap, ["StockholdersEquity"])

        snap = FinancialMetricSnapshot(ticker=ref.ticker)
        try:
            price_snap = await YahooProvider().snapshot(ref)
            price = price_snap.price
        except Exception:
            price = None
        if price and shares:
            snap.market_cap = price * shares
        if price and eps:
            snap.price_to_earnings_ratio = round(price / eps, 4) if eps else None
        if snap.market_cap and equity:
            snap.price_to_book_ratio = round(snap.market_cap / equity, 4)
        return snap


def _latest(gaap: dict, concepts: list[str]) -> float | None:
    best = None
    best_end = ""
    for concept in concepts:
        for row in _observations(gaap, concept):
            end = row.get("end", "")
            if end > best_end and row.get("val") is not None:
                best, best_end = row["val"], end
    return best
