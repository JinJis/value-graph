"""OpenDART value/date normalization, report-code labels, and period math.

Pure helpers extracted from ``opendart.py``: DART date/amount parsing, the
``reprt_code`` <-> fiscal-period mapping, the row->field statement extractor, and
the (year, reprt_code, report-period) enumeration that drives statement fetches.
No network/config dependencies. Sibling of ``sec_edgar_xbrl.py`` on the US side.
"""

from __future__ import annotations

from datetime import date

# reprt_code -> (period label, fiscal month-end)
_ANNUAL = "11011"
_QUARTER_CODES = [("11014", 9), ("11012", 6), ("11013", 3)]  # Q3, half, Q1 (cumulative)
_REPRT_LABEL = {"11011": "FY", "11013": "Q1", "11012": "H1", "11014": "Q3"}


def _kr_date(raw: str | None) -> str | None:
    """Normalize a DART date (8-digit or separator-laden) to YYYY-MM-DD."""
    if not raw:
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) < 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _amount(raw: str | None) -> float | None:
    if raw in (None, "", "-"):
        return None
    try:
        return float(str(raw).replace(",", ""))
    except ValueError:
        return None


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


def _fiscal_period(year: int, code: str) -> str:
    return f"{year}-{_REPRT_LABEL.get(code, '')}"


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
