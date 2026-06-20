"""Central-bank policy rates from DBnomics — a keyless, cloud-safe FRED alternative.

FRED's ``api.stlouisfred.org`` serves a JavaScript bot-wall (not JSON) to
datacenter IPs even with a valid key, so US macro breaks when deployed in the
cloud. DBnomics (``api.db.nomics.world``) is keyless, has no datacenter gate, and
redistributes the BIS *Central bank policy rates* dataset (``BIS/WS_CBPOL``),
which covers the FED/ECB/BOE/BOJ policy rates in one place — a drop-in source for
the same ``bank`` enum the FRED provider serves.

Note: BIS reports the policy *target/midpoint* (e.g. US 4.375), which can differ
slightly from a specific FRED series convention (e.g. DFEDTARU = target upper),
but both are the same central-bank policy rate — fully sourced either way.
"""

from __future__ import annotations

from datetime import date

from app.errors import bad_request, not_found, upstream_error
from app.http import fetch_json
from app.models.generated import InterestRate

_DATASET = "BIS/WS_CBPOL"

# bank code -> (display name, BIS REF_AREA code). One daily-frequency series per area.
_BANKS: dict[str, tuple[str, str]] = {
    "FED": ("U.S. Federal Reserve", "US"),
    "ECB": ("European Central Bank", "XM"),  # XM = euro area
    "BOE": ("Bank of England", "GB"),
    "BOJ": ("Bank of Japan", "JP"),
}


def _series(bank: str) -> tuple[str, str]:
    info = _BANKS.get(bank.upper())
    if not info:
        raise bad_request(f"Unknown bank '{bank}'. Use one of: {', '.join(_BANKS)}.")
    return info  # (name, ref_area)


def _parse_period(period: str) -> date | None:
    """BIS periods are ISO 'YYYY-MM-DD' (daily) but tolerate 'YYYY-MM' / 'YYYY'."""
    parts = (period or "").split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def _to_rate(bank: str, name: str, period: str, value: object) -> InterestRate | None:
    if value in (None, "", "NA", "."):
        return None
    iso = _parse_period(period)
    if iso is None:
        return None
    try:
        return InterestRate(bank=bank.upper(), name=name, rate=float(value), date=iso.isoformat())
    except (TypeError, ValueError):
        return None


async def _observations(ref_area: str) -> list[tuple[str, object]]:
    """Return ``[(period, value), …]`` for the daily policy-rate series of one area."""
    url = f"https://api.db.nomics.world/v22/series/{_DATASET}/D.{ref_area}"
    data = await fetch_json("dbnomics", url, params={"observations": "1"})
    docs = (data.get("series") or {}).get("docs") or [] if isinstance(data, dict) else []
    if not docs:
        raise upstream_error("dbnomics", f"no series for {_DATASET}/D.{ref_area}")
    doc = docs[0]
    return list(zip(doc.get("period") or [], doc.get("value") or []))


class DBnomicsProvider:
    """Keyless macro provider backed by BIS policy rates via DBnomics."""

    def banks(self) -> list[dict]:
        return [{"bank": code, "name": name} for code, (name, _) in _BANKS.items()]

    async def interest_rates(
        self, bank: str, start: date | None, end: date | None
    ) -> list[InterestRate]:
        name, ref_area = _series(bank)
        out: list[InterestRate] = []
        for period, value in await _observations(ref_area):
            rate = _to_rate(bank, name, period, value)
            if not rate:
                continue
            iso = _parse_period(period)
            if start and iso < start:
                continue
            if end and iso > end:
                continue
            out.append(rate)
        if not out:
            raise not_found(f"No interest-rate data for bank '{bank}'.")
        return out

    async def snapshot(self, bank: str) -> list[InterestRate]:
        name, ref_area = _series(bank)
        for period, value in reversed(await _observations(ref_area)):
            rate = _to_rate(bank, name, period, value)
            if rate:
                return [rate]
        raise not_found(f"No current interest rate for bank '{bank}'.")
