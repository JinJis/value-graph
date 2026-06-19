"""SEC EDGAR XBRL assembly: turn a companyfacts payload into per-period statement rows.

Pure functions over the us-gaap facts dict -- period matching (annual/quarterly/instant vs
duration), TTM roll-ups, value selection, and the full-history flatten. No HTTP, no provider
state.
"""

from __future__ import annotations

from datetime import datetime

from app.providers.us.sec_edgar_concepts import BALANCE_MAP, CASHFLOW_MAP, INCOME_MAP


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
    # the filing *index page* (lists the filing's documents), not the bare `…/{accn}/`
    # directory — a directory listing is "just reference links", not the filing itself.
    if not accn:
        return None
    nodash = accn.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{nodash}/{accn}-index.htm"


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
