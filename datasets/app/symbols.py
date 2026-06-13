"""Market + symbol normalization.

A single API surface serves two markets, chosen with the ``market`` query
parameter. Tickers stay native to the market:

* US  — ``AAPL`` (alphabetic ticker)
* KR  — ``005930`` (6-digit issue code; optional ``.KS`` / ``.KQ`` suffix accepted)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Market(str, Enum):
    US = "US"
    KR = "KR"


# KR tickers may arrive as 005930, 5930, or 005930.KS / 005930.KQ
_KR_SUFFIX = re.compile(r"\.(KS|KQ|KN)$", re.IGNORECASE)


@dataclass(frozen=True)
class SecurityRef:
    """A resolved reference to one security in one market.

    ``ticker`` is the normalized native symbol. ``cik`` carries the US SEC CIK
    or the KR OpenDART ``corp_code`` once resolved (provider-filled).
    """

    market: Market
    ticker: str
    cik: str | None = None


def normalize_ticker(market: Market, ticker: str) -> str:
    """Normalize a raw ticker into its canonical native form for ``market``."""
    raw = (ticker or "").strip()
    if not raw:
        raise ValueError("ticker is required")
    if market is Market.KR:
        raw = _KR_SUFFIX.sub("", raw)
        if not raw.isdigit():
            raise ValueError(f"KR ticker must be a numeric issue code, got {ticker!r}")
        return raw.zfill(6)
    return raw.upper()


def build_ref(market: Market, ticker: str | None = None, cik: str | None = None) -> SecurityRef:
    """Build a SecurityRef from request params; requires at least one identifier."""
    if not ticker and not cik:
        raise ValueError("Either 'ticker' or 'cik' is required.")
    norm = normalize_ticker(market, ticker) if ticker else ""
    return SecurityRef(market=market, ticker=norm, cik=cik)


def kr_market_suffix(code: str, board: str | None) -> str:
    """Map a KR board ('KOSPI'/'KOSDAQ') to the Yahoo-style suffix for display."""
    if board and "KOSDAQ" in board.upper():
        return f"{code}.KQ"
    return f"{code}.KS"
