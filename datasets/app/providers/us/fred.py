"""US (and other major central banks') interest rates from FRED.

https://api.stlouisfred.org/fred/series/observations?series_id=...&api_key=...

Bank codes map to a representative policy-rate series. Extendable via the
``_BANKS`` table.
"""

from __future__ import annotations

from datetime import date

from app.config import settings
from app.errors import bad_request, not_found
from app.http import fetch_json
from app.models.generated import InterestRate

# bank code -> (display name, FRED series id)
_BANKS: dict[str, tuple[str, str]] = {
    "FED": ("U.S. Federal Reserve", "DFEDTARU"),  # federal funds target rate (upper)
    "ECB": ("European Central Bank", "ECBDFR"),  # ECB deposit facility rate
    "BOE": ("Bank of England", "BOERUKM"),  # BoE official bank rate (monthly)
    "BOJ": ("Bank of Japan", "INTDSRJPM193N"),  # Japan discount rate
}


def _series(bank: str) -> tuple[str, str]:
    info = _BANKS.get(bank.upper())
    if not info:
        raise bad_request(f"Unknown bank '{bank}'. Use one of: {', '.join(_BANKS)}.")
    return info


async def _observations(series_id: str, start: date | None, end: date | None) -> list[dict]:
    if not settings.fred_api_key:
        raise bad_request("FRED_API_KEY is not configured.")
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
    }
    if start:
        params["observation_start"] = start.isoformat()
    if end:
        params["observation_end"] = end.isoformat()
    data = await fetch_json("fred", "https://api.stlouisfred.org/fred/series/observations", params=params)
    return data.get("observations", [])  # type: ignore[union-attr]


def _to_rate(bank: str, name: str, row: dict) -> InterestRate | None:
    val = row.get("value")
    if val in (None, "", "."):
        return None
    try:
        return InterestRate(bank=bank.upper(), name=name, rate=float(val), date=row.get("date"))
    except ValueError:
        return None


class FredProvider:
    def banks(self) -> list[dict]:
        return [{"bank": code, "name": name} for code, (name, _) in _BANKS.items()]

    async def interest_rates(self, bank: str, start: date | None, end: date | None) -> list[InterestRate]:
        name, series_id = _series(bank)
        rows = await _observations(series_id, start, end)
        out = [r for r in (_to_rate(bank, name, row) for row in rows) if r]
        if not out:
            raise not_found(f"No interest-rate data for bank '{bank}'.")
        return out

    async def snapshot(self, bank: str) -> list[InterestRate]:
        name, series_id = _series(bank)
        rows = await _observations(series_id, None, None)
        for row in reversed(rows):
            rate = _to_rate(bank, name, row)
            if rate:
                return [rate]
        raise not_found(f"No current interest rate for bank '{bank}'.")
