"""US (and other major central banks') interest rates from FRED.

https://api.stlouisfred.org/fred/series/observations?series_id=...&api_key=...

Bank codes map to a representative policy-rate series. Extendable via the
``_BANKS`` table.
"""

from __future__ import annotations

from datetime import date

from app.config import settings
from app.errors import bad_request, not_found, upstream_error
from app.http import get_client
from app.models.generated import InterestRate

_UA = {"User-Agent": "Mozilla/5.0 (compatible; ValueGraphDatasets/0.1)"}

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
    data = await _fred_json("https://api.stlouisfred.org/fred/series/observations", params)
    return data.get("observations", [])


async def _fred_json(url: str, params: dict) -> dict:
    """GET JSON from the FRED API.

    From some datacenter IPs, ``api.stlouisfred.org`` serves a JavaScript
    bot-verification challenge (a ``window.location.replace`` page / JS
    proof-of-work) instead of JSON. That can't be solved by a plain HTTP client,
    so we detect it and surface an honest error rather than a parse failure.
    FRED returns JSON directly from a normal/residential IP with the same key."""
    import httpx

    client = get_client()
    try:
        resp = await client.get(url, params=params, headers=_UA)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise upstream_error("fred", str(exc))
    body = resp.text.lstrip()
    if "window.location.replace" in body or body[:1] not in ("{", "["):
        raise upstream_error(
            "fred",
            "FRED served a bot-verification challenge instead of JSON (this server's IP is "
            "being gated by api.stlouisfred.org). The request and API key are otherwise valid; "
            "FRED responds normally from a non-datacenter IP.",
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise upstream_error("fred", str(exc))


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
