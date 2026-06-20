"""PH-PROV2: the datasets `/evidence?…` URL for a filing-backed figure.

Our normalized statement fields → ordered candidate us-gaap concepts (mirror of the
datasets INCOME/BALANCE/CASHFLOW maps; the same field maps to different tags across
filers, so the /evidence lookup tries each in order). We only compose the link
deterministically — the frontend fetches the highlighted screenshot lazily, so the
answer stream is never blocked.
"""

from __future__ import annotations

from urllib.parse import urlencode

_FIELD_CONCEPTS: dict[str, list[str]] = {
    # income statement (duration contexts)
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    # balance sheet (instant contexts)
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "shareholders_equity": ["StockholdersEquity",
                            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue",
                             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    # cash-flow statement (duration contexts)
    "net_cash_flow_from_operations": ["NetCashProvidedByUsedInOperatingActivities"],
    "net_cash_flow_from_investing": ["NetCashProvidedByUsedInInvestingActivities"],
    "net_cash_flow_from_financing": ["NetCashProvidedByUsedInFinancingActivities"],
}
# per-statement result key (datasets shape) → ordered headline fields to anchor evidence on.
# Mirrors the provider's concept maps; balance sheets resolve against instant XBRL contexts,
# income/cash-flow against duration contexts — the matcher already indexes both (PH-PROV2c).
_STATEMENT_HEADLINES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("income_statements", ("revenue", "net_income", "operating_income", "gross_profit")),
    ("balance_sheets", ("total_assets", "total_liabilities", "shareholders_equity", "cash_and_equivalents")),
    ("cash_flow_statements", ("net_cash_flow_from_operations", "net_cash_flow_from_investing",
                              "net_cash_flow_from_financing")),
)


def _ev_qs(accn, cik, concept, report_period, value) -> str | None:
    if not (accn and concept and report_period):
        return None
    q = {"market": "US", "accession": accn, "concept": concept, "report_period": report_period, "value": value}
    if cik:
        q["cik"] = cik
    return "/evidence?" + urlencode(q)


def _evidence_url(data, accn, cik, market) -> str | None:
    """PH-PROV2: the datasets `/evidence?…` URL for a US filing-backed result's headline
    figure. The frontend fetches the highlighted screenshot lazily — we only attach the
    link (deterministic, no render), so the answer stream is never blocked. Handles both
    the as-reported shape (explicit us-gaap concept) and the income-statement shape (our
    normalized fields → candidate concepts). None when there's nothing to point at."""
    if (market or "").upper() != "US" or not accn or not isinstance(data, dict):
        return None
    # as-reported: explicit us-gaap concept per line item
    periods = data.get("periods")
    if isinstance(periods, list) and periods and isinstance(periods[0], dict):
        p = periods[0]
        items = [it for it in (p.get("line_items") or []) if isinstance(it, dict)]
        pick = next((it for it in items if "Revenue" in (it.get("concept") or "")), items[0] if items else None)
        if pick and pick.get("value") is not None and pick.get("concept"):
            return _ev_qs(pick.get("accession_number") or accn, cik, pick["concept"],
                          p.get("report_period"), pick["value"])
    # financial statements (income / balance / cash-flow): normalized fields → candidate
    # concepts, anchored on the newest period's first available headline figure.
    for key, headlines in _STATEMENT_HEADLINES:
        rows = [r for r in (data.get(key) or []) if isinstance(r, dict) and r.get("report_period")]
        rows.sort(key=lambda r: str(r.get("report_period")), reverse=True)
        for r in rows:
            for field in headlines:
                if r.get(field) is not None:
                    return _ev_qs(r.get("accession_number") or accn, cik, ",".join(_FIELD_CONCEPTS[field]),
                                  r.get("report_period"), r.get(field))
    return None
