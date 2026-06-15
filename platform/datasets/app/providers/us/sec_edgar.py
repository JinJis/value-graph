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
from xml.etree import ElementTree

from app.cache import cache
from app.config import settings
from app.errors import not_found, not_implemented, upstream_error
from app.http import fetch_json, fetch_text
from app.models.generated import (
    BalanceSheet,
    CashFlowStatement,
    CompanyFacts,
    CompanySearchResult,
    EarningsRecord,
    EarningsTimeDimension,
    Filing,
    FinancialMetricSnapshot,
    IncomeStatement,
    InsiderTrade,
    InstitutionalHolding,
    Price,
    PriceSnapshot,
)
from app.providers.search_util import rank_company_matches
from app.symbols import SecurityRef

# SEC Form 4 transaction codes -> human-readable description.
_TXN_CODES = {
    "P": "Open market purchase",
    "S": "Open market sale",
    "A": "Grant or award",
    "D": "Disposition to issuer",
    "F": "Payment of exercise/tax by shares",
    "G": "Gift",
    "M": "Exercise of derivative",
    "X": "Exercise of in-the-money derivative",
    "C": "Conversion of derivative",
    "J": "Other acquisition or disposition",
}

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

    async def list_ciks(self) -> list[str]:
        idx = await _ticker_index()
        return sorted({_cik10(row["cik_str"]) for row in idx.values()})

    async def as_reported(self, ref: SecurityRef, period: str = "annual", limit: int = 4) -> list[dict]:
        """Financials EXACTLY as filed in XBRL — every us-gaap concept for each of the
        most recent ``limit`` report periods (not normalised to our model). Keeps the
        latest-filed value per concept; gaps stay absent, never fabricated (PH-7)."""
        cik10 = await _resolve_cik(ref)
        raw = await _company_facts_raw(cik10)
        gaap = (raw.get("facts") or {}).get("us-gaap") or {}
        periods: dict[str, dict] = {}
        for concept, node in gaap.items():
            label = node.get("label")
            for unit, rows in (node.get("units") or {}).items():
                for row in rows:
                    if not isinstance(row.get("val"), (int, float)):
                        continue
                    if not _period_ok(row, period, instant="start" not in row):
                        continue
                    end = row.get("end")
                    if not end:
                        continue
                    bucket = periods.setdefault(end, {})
                    prev = bucket.get(concept)
                    if prev is None or (row.get("filed") or "") > (prev.get("filed") or ""):
                        bucket[concept] = {
                            "concept": concept, "label": label, "value": float(row["val"]),
                            "unit": unit, "form": row.get("form"),
                            "accession_number": row.get("accn"), "filed": row.get("filed"),
                        }
        out: list[dict] = []
        for end in sorted(periods, reverse=True)[:limit]:
            items = sorted(periods[end].values(), key=lambda x: x["concept"])
            out.append({"report_period": end, "period": period, "line_items": items})
        return out

    async def search_companies(self, query: str, limit: int) -> list[CompanySearchResult]:
        idx = await _ticker_index()
        rows = (
            {"ticker": tk, "name": row.get("title"), "cik": _cik10(row["cik_str"])}
            for tk, row in idx.items()
        )
        ranked = rank_company_matches(query, rows)
        return [
            CompanySearchResult(name=r["name"], ticker=r["ticker"], market="US", cik=r["cik"])
            for r in ranked[:limit]
        ]

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


# --- XML / number helpers (insider + 13F) --------------------------------
def _num(text: str | None) -> float | None:
    if text in (None, ""):
        return None
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return None


def _local(tag: str) -> str:
    return tag.split("}")[-1]


async def _filing_meta(cik10: str) -> dict[str, tuple[str, str]]:
    """accession_number -> (filing_date, form) from the submissions 'recent' block."""
    sub = await _submissions(cik10)
    recent = (sub.get("filings") or {}).get("recent") or {}
    accns = recent.get("accessionNumber") or []
    fdates = recent.get("filingDate") or []
    forms = recent.get("form") or []
    return {accns[i]: (fdates[i] if i < len(fdates) else None, forms[i] if i < len(forms) else None) for i in range(len(accns))}


class SecEdgarEarningsProvider:
    """Earnings actuals from XBRL (revenue/EPS/margins by reported period).

    Consensus estimates and surprise fields are intentionally null — there is no
    free estimates feed; we never fabricate them."""

    async def earnings(self, ref: SecurityRef, limit: int) -> list[EarningsRecord]:
        cik10 = await _resolve_cik(ref)
        facts = await _company_facts_raw(cik10)
        gaap = facts.get("facts", {}).get("us-gaap", {})
        meta = await _filing_meta(cik10)
        spine = INCOME_MAP["revenue"] + INCOME_MAP["net_income"]
        rows = _assemble(gaap, INCOME_MAP, spine, "quarterly", limit, instant=False, cik10=cik10)
        out: list[EarningsRecord] = []
        for r in rows:
            accn = r.get("accession_number")
            fdate, form = meta.get(accn, (None, None))
            source = form if form in ("8-K", "10-Q", "10-K", "20-F") else "10-Q"
            dim = EarningsTimeDimension(
                revenue=r.get("revenue"),
                earnings_per_share=r.get("earnings_per_share"),
                gross_profit=r.get("gross_profit"),
                operating_income=r.get("operating_income"),
                net_income=r.get("net_income"),
                weighted_average_shares=r.get("weighted_average_shares"),
                weighted_average_shares_diluted=r.get("weighted_average_shares_diluted"),
            )
            out.append(
                EarningsRecord(
                    ticker=ref.ticker.upper(),
                    report_period=r["report_period"],
                    fiscal_period=r.get("fiscal_period"),
                    currency="USD",
                    source_type=source,
                    filing_date=fdate or r["report_period"],
                    filing_url=r.get("filing_url"),
                    accession_number=accn or "",
                    quarterly=dim,
                )
            )
        if not out:
            raise not_found(f"No earnings data for '{ref.ticker}'.")
        return out


def _parse_form4(xml: str, ticker: str) -> tuple[str | None, str | None, str | None, bool | None, list[dict]]:
    root = ElementTree.fromstring(xml)
    issuer = root.findtext("issuer/issuerName")
    owner = root.findtext("reportingOwner/reportingOwnerId/rptOwnerName")
    rel = root.find("reportingOwner/reportingOwnerRelationship")
    is_dir = None
    title = None
    if rel is not None:
        is_dir = rel.findtext("isDirector") in ("1", "true")
        title = rel.findtext("officerTitle")
    txns: list[dict] = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        shares = _num(tx.findtext("transactionAmounts/transactionShares/value"))
        price = _num(tx.findtext("transactionAmounts/transactionPricePerShare/value"))
        ad = tx.findtext("transactionAmounts/transactionAcquiredDisposedCode/value")
        signed = (shares * (-1 if ad == "D" else 1)) if shares is not None else None
        txns.append(
            {
                "code": tx.findtext("transactionCoding/transactionCode"),
                "date": tx.findtext("transactionDate/value"),
                "shares": signed,
                "price": price,
                "owned_after": _num(tx.findtext("postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                "security": tx.findtext("securityTitle/value"),
            }
        )
    return issuer, owner, title, is_dir, txns


class SecEdgarInsiderProvider:
    """Insider transactions parsed from SEC Form 4 XML."""

    async def _xml_name(self, cik10: str, nodash: str, primary: str) -> str:
        raw = primary.split("/")[-1] if primary else ""
        if raw.endswith(".xml"):
            return raw
        idx = await fetch_json(
            "sec_edgar", f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{nodash}/index.json", headers=_UA
        )
        for item in (idx.get("directory", {}) or {}).get("item", []):
            n = item.get("name", "")
            if n.endswith(".xml") and not n.startswith("xsl"):
                return n
        return ""

    async def insider_trades(self, ref: SecurityRef, limit: int) -> list[InsiderTrade]:
        cik10 = await _resolve_cik(ref)
        sub = await _submissions(cik10)
        recent = (sub.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accns = recent.get("accessionNumber") or []
        fdates = recent.get("filingDate") or []
        prim = recent.get("primaryDocument") or []
        out: list[InsiderTrade] = []
        for i in range(len(forms)):
            if forms[i] != "4":
                continue
            accn = accns[i]
            nodash = accn.replace("-", "")
            name = await self._xml_name(cik10, nodash, prim[i] if i < len(prim) else "")
            if not name:
                continue
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{nodash}/{name}"
            try:
                xml = await fetch_text("sec_edgar", url, headers=_UA)
                issuer, owner, title, is_dir, txns = _parse_form4(xml, ref.ticker)
            except Exception:
                continue
            for t in txns:
                value = t["shares"] * t["price"] if t["shares"] is not None and t["price"] else None
                out.append(
                    InsiderTrade(
                        ticker=ref.ticker.upper(),
                        issuer=issuer,
                        name=owner,
                        title=title,
                        is_board_director=is_dir,
                        transaction_date=t["date"],
                        transaction_shares=t["shares"],
                        transaction_price_per_share=t["price"],
                        transaction_value=value,
                        shares_owned_after_transaction=t["owned_after"],
                        security_title=t["security"],
                        transaction_type=_TXN_CODES.get(t["code"], t["code"]),
                        filing_date=fdates[i] if i < len(fdates) else None,
                    )
                )
            if len(out) >= limit:
                break
        if not out:
            raise not_found(f"No insider Form 4 data for '{ref.ticker}'.")
        return out[:limit]


def _parse_13f(xml: str, report_period: str | None, filing_date: str | None, form: str, accn: str) -> list[InstitutionalHolding]:
    root = ElementTree.fromstring(xml)
    out: list[InstitutionalHolding] = []
    for info in root.iter():
        if _local(info.tag) != "infoTable":
            continue
        d = {_local(c.tag): c for c in info}
        ssh = None
        shrs = d.get("shrsOrPrnAmt")
        if shrs is not None:
            for c in shrs:
                if _local(c.tag) == "sshPrnamt":
                    ssh = _num(c.text)
        value = _num(d["value"].text) if "value" in d else None
        put_call = d["putCall"].text if "putCall" in d else None
        out.append(
            InstitutionalHolding(
                ticker=None,
                name_of_issuer=d["nameOfIssuer"].text if "nameOfIssuer" in d else None,
                cusip=d["cusip"].text if "cusip" in d else None,
                report_period=report_period,
                filing_date=filing_date,
                form_type=form if form in ("13F-HR", "13F-HR/A") else "13F-HR",
                accession_number=accn,
                title_of_class=d["titleOfClass"].text if "titleOfClass" in d else None,
                put_call=put_call or None,
                shares=int(ssh) if ssh is not None else None,
                value_usd=int(value) if value is not None else None,
            )
        )
    return out


class SecEdgar13FProvider:
    """13F holdings parsed from a filer's latest information table (filer_cik mode)."""

    async def _infotable_name(self, cik10: str, nodash: str) -> str:
        idx = await fetch_json(
            "sec_edgar", f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{nodash}/index.json", headers=_UA
        )
        xmls = [
            item.get("name", "")
            for item in (idx.get("directory", {}) or {}).get("item", [])
            if item.get("name", "").endswith(".xml")
        ]
        for n in xmls:
            low = n.lower()
            if "info" in low or "table" in low:
                return n
        for n in xmls:
            if n.lower() != "primary_doc.xml":
                return n
        return ""

    async def by_filer(self, filer_cik: str, limit: int) -> list[InstitutionalHolding]:
        cik10 = _cik10(filer_cik)
        sub = await _submissions(cik10)
        recent = (sub.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accns = recent.get("accessionNumber") or []
        fdates = recent.get("filingDate") or []
        rdates = recent.get("reportDate") or []
        idx = next((i for i, f in enumerate(forms) if f in ("13F-HR", "13F-HR/A")), None)
        if idx is None:
            raise not_found(f"No 13F-HR filing for CIK {filer_cik}.")
        accn = accns[idx]
        nodash = accn.replace("-", "")
        name = await self._infotable_name(cik10, nodash)
        if not name:
            raise not_found(f"No 13F information table found for CIK {filer_cik}.")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{nodash}/{name}"
        xml = await fetch_text("sec_edgar", url, headers=_UA)
        holdings = _parse_13f(xml, rdates[idx] if idx < len(rdates) else None, fdates[idx] if idx < len(fdates) else None, forms[idx], accn)
        holdings.sort(key=lambda h: h.value_usd or 0, reverse=True)
        return holdings[:limit]

    async def by_ticker(self, ref: SecurityRef, limit: int) -> list[InstitutionalHolding]:
        raise not_implemented(
            "Ticker-mode 13F (which filers hold a security) requires a reverse CUSIP/holdings "
            "index that this build does not maintain yet. Use ?filer_cik=... for a filer's holdings."
        )


# --- bulk: all historical periods from a raw companyfacts dict -------------
_ALL_SPECS = [
    ("income", INCOME_MAP, INCOME_MAP["revenue"] + INCOME_MAP["net_income"], False),
    ("balance", BALANCE_MAP, ["Assets"], True),
    ("cashflow", CASHFLOW_MAP, ["NetCashProvidedByUsedInOperatingActivities"], False),
]


def all_facts_from_companyfacts(facts: dict, cik10: str) -> list[dict]:
    """Flatten a companyfacts payload into every (statement, period, report_period,
    line_item) row available — the deep-history feed for the bulk loader. Reuses
    the same XBRL assembler as the live endpoints (no `limit` cap)."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    big = 10**7
    out: list[dict] = []
    for statement, field_map, spine, instant in _ALL_SPECS:
        for period in ("annual", "quarterly"):
            for r in _assemble(gaap, field_map, spine, period, big, instant=instant, cik10=cik10):
                rp = r.get("report_period")
                if not rp:
                    continue
                for line_item, value in r.items():
                    if line_item in ("report_period", "fiscal_period", "accession_number", "filing_url"):
                        continue
                    if value is None or not isinstance(value, (int, float)):
                        continue
                    out.append(
                        {
                            "statement": statement, "line_item": line_item, "value": float(value),
                            "period": period, "report_period": rp, "fiscal_period": r.get("fiscal_period"),
                            "accession_number": r.get("accession_number") or "",
                        }
                    )
    return out
