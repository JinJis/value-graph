"""Canonical company identity — a ticker that includes its exchange.

A bare ticker is NOT globally unique: the same symbol can mean different companies on different
exchanges, and the same company has a different symbol per listing. Worse, formats differ by
market (alphabetic ``AAPL`` vs numeric ``6857``/``005930``). We canonicalize to a
Yahoo-Finance-style ``SYMBOL[.SUFFIX]`` from the company's country/exchange — so 6857 in Tokyo
becomes ``6857.T`` and Samsung in Seoul ``005930.KS``, while US symbols stay bare (``AAPL``).
This is the stable identity the graph keys on; :func:`base_symbol` recovers the bare symbol for
loose matching.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

# Country (ISO-2) -> Yahoo-style exchange suffix. US (and anything unmapped) stays bare.
_SUFFIX_BY_COUNTRY: dict[str, str] = {
    "JP": ".T",  # Tokyo
    "KR": ".KS",  # KOSPI (KOSDAQ is .KQ; we default to .KS)
    "TW": ".TW",  # Taiwan
    "HK": ".HK",  # Hong Kong
    "CN": ".SS",  # Shanghai (Shenzhen is .SZ — ambiguous; default SSE)
    "GB": ".L",
    "UK": ".L",
    "DE": ".DE",
    "FR": ".PA",
    "NL": ".AS",
    "CH": ".SW",
    "CA": ".TO",
    "IN": ".NS",
    "AU": ".AX",
    "SG": ".SI",
}


def canonical_ticker(
    ticker: str, *, country: str | None = None, exchange: str | None = None
) -> str:
    """Canonical ``SYMBOL[.SUFFIX]`` for a company. Idempotent; trusts an existing suffix."""
    sym = (ticker or "").strip().upper()
    if not sym:
        return sym
    if ":" in sym:  # "KRX:005930" / "NASDAQ:NVDA" -> bare symbol
        sym = sym.rsplit(":", 1)[-1].strip()
    if "." in sym:  # already carries a suffix (e.g. "6857.T") -> trust it
        return sym
    suffix = _SUFFIX_BY_COUNTRY.get((country or "").strip().upper(), "")
    return f"{sym}{suffix}" if suffix else sym


def base_symbol(ticker: str) -> str:
    """The bare symbol without the exchange suffix ("6857.T" -> "6857")."""
    return (ticker or "").split(".")[0].strip().upper()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class _Identifiable(Protocol):
    ticker: str
    name: str


def build_ticker_index(companies: Iterable[_Identifiable]) -> dict[str, str]:
    """Index a set of known companies for loose resolution: their canonical ticker, the bare
    symbol, and the normalized name all map back to the canonical ticker. So a Deep-Research
    "6857" / "Advantest" / "6857.T" all resolve to the canonical "6857.T"."""
    index: dict[str, str] = {}
    for c in companies:
        index[c.ticker.upper()] = c.ticker
        index[base_symbol(c.ticker)] = c.ticker
        index[_norm(c.name)] = c.ticker
    return index


def resolve_to_known(value: str | None, index: dict[str, str]) -> str | None:
    """Resolve an LLM-returned ticker/name to a canonical ticker in ``index`` (or None)."""
    if not value:
        return None
    raw = value.strip()
    return (
        index.get(raw.upper()) or index.get(base_symbol(raw)) or index.get(_norm(raw))
    )
