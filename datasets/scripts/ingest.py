"""Ingest a universe of tickers into the store.

Usage:
    uv run python -m scripts.ingest US AAPL MSFT NVDA
    uv run python -m scripts.ingest KR 005930 000660 035720
    uv run python -m scripts.ingest US --period quarterly --limit 8 AAPL

Production would feed the same writer from a bulk loader (SEC companyfacts.zip /
DART batch); this CLI is the per-ticker path for dev and incremental top-ups.
"""

from __future__ import annotations

import asyncio
import sys

from app.store.ingest import ingest_universe
from app.symbols import Market


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    market = Market(argv[0].upper())
    period, limit, tickers = "annual", 8, []
    i = 1
    while i < len(argv):
        if argv[i] == "--period":
            period = argv[i + 1]; i += 2
        elif argv[i] == "--limit":
            limit = int(argv[i + 1]); i += 2
        else:
            tickers.append(argv[i]); i += 1
    if not tickers:
        print("No tickers given.")
        return 1
    print(f"Ingesting {len(tickers)} {market.value} tickers (period={period}, limit={limit})...")
    result = asyncio.run(ingest_universe(market, tickers, period, limit))
    total = sum(v for v in result.values() if v > 0)
    print(f"Done. {total} facts across {sum(1 for v in result.values() if v > 0)} tickers.")
    for t, n in result.items():
        print(f"  {t}: {n} facts" if n >= 0 else f"  {t}: FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
