"""KR interest rates from the Bank of Korea ECOS Open API.

ECOS encodes parameters as URL path segments:
  /api/StatisticSearch/{KEY}/json/kr/{start}/{end}/{STAT}/{CYCLE}/{FROM}/{TO}/{ITEM}

``bank=BOK`` returns the Bank of Korea base rate (기준금리). Other tables can be
added to ``_BANKS``.
"""

from __future__ import annotations

from datetime import date

from app.config import settings
from app.errors import bad_request, not_found, upstream_error
from app.http import fetch_json
from app.models.generated import InterestRate

_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
# bank code -> (display name, stat_code, item_code, cycle)
_BANKS: dict[str, tuple[str, str, str, str]] = {
    "BOK": ("Bank of Korea Base Rate", "722Y001", "0101000", "D"),
}


def _key() -> str:
    if not settings.ecos_api_key:
        raise bad_request("ECOS_API_KEY is not configured.")
    return settings.ecos_api_key


def _bank(bank: str) -> tuple[str, str, str, str]:
    info = _BANKS.get(bank.upper())
    if not info:
        raise bad_request(f"Unknown bank '{bank}'. Use one of: {', '.join(_BANKS)}.")
    return info


def _fmt(d: date, cycle: str) -> str:
    if cycle == "D":
        return d.strftime("%Y%m%d")
    if cycle == "M":
        return d.strftime("%Y%m")
    return d.strftime("%Y")


def _to_iso(time_str: str, cycle: str) -> str:
    if cycle == "D" and len(time_str) == 8:
        return f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]}"
    if cycle == "M" and len(time_str) == 6:
        return f"{time_str[:4]}-{time_str[4:6]}-01"
    return f"{time_str[:4]}-01-01"


async def _search(stat: str, cycle: str, item: str, start: date, end: date) -> list[dict]:
    url = (
        f"{_BASE}/{_key()}/json/kr/1/1000/{stat}/{cycle}/"
        f"{_fmt(start, cycle)}/{_fmt(end, cycle)}/{item}"
    )
    data = await fetch_json("ecos", url)
    if "RESULT" in data:  # error envelope
        result = data["RESULT"]  # type: ignore[index]
        raise upstream_error("ecos", f"{result.get('CODE')}: {result.get('MESSAGE')}")
    rows = (data.get("StatisticSearch") or {}).get("row") or []  # type: ignore[union-attr]
    return rows


def _to_rate(bank: str, name: str, row: dict, cycle: str) -> InterestRate | None:
    val = row.get("DATA_VALUE")
    if val in (None, "", "-"):
        return None
    try:
        return InterestRate(
            bank=bank.upper(), name=name, rate=float(val), date=_to_iso(row.get("TIME", ""), cycle)
        )
    except ValueError:
        return None


class EcosProvider:
    def banks(self) -> list[dict]:
        return [{"bank": code, "name": name} for code, (name, *_rest) in _BANKS.items()]

    async def interest_rates(self, bank: str, start: date | None, end: date | None) -> list[InterestRate]:
        name, stat, item, cycle = _bank(bank)
        start = start or date(2000, 1, 1)
        end = end or date.today()
        rows = await _search(stat, cycle, item, start, end)
        out = [r for r in (_to_rate(bank, name, row, cycle) for row in rows) if r]
        if not out:
            raise not_found(f"No ECOS interest-rate data for bank '{bank}'.")
        return out

    async def snapshot(self, bank: str) -> list[InterestRate]:
        name, stat, item, cycle = _bank(bank)
        rows = await _search(stat, cycle, item, date(date.today().year - 1, 1, 1), date.today())
        for row in reversed(rows):
            rate = _to_rate(bank, name, row, cycle)
            if rate:
                return [rate]
        raise not_found(f"No current ECOS rate for bank '{bank}'.")
