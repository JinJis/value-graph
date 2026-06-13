"""Bulk / deep-history backfill into the store.

US — deep per ticker (full companyfacts history):
    uv run python -m scripts.bulk_load US AAPL MSFT NVDA

US — full universe from the SEC bulk zip (download once, ~1GB):
    curl -o /tmp/companyfacts.zip https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip
    uv run python -m scripts.bulk_load US --zip /tmp/companyfacts.zip --limit 500

KR — deep per ticker over a wide year range (DART):
    uv run python -m scripts.bulk_load KR 005930 000660 --limit 15
"""

from __future__ import annotations

import asyncio
import sys

from app.store.bulk import bulk_load_kr, bulk_load_us
from app.symbols import Market


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    market = Market(argv[0].upper())
    rest = argv[1:]
    zip_path: str | None = None
    limit: int | None = None
    tickers: list[str] = []
    i = 0
    while i < len(rest):
        if rest[i] == "--zip":
            zip_path = rest[i + 1]; i += 2
        elif rest[i] == "--limit":
            limit = int(rest[i + 1]); i += 2
        else:
            tickers.append(rest[i]); i += 1

    if market is Market.US:
        result = asyncio.run(bulk_load_us(tickers or None, zip_path, limit))
    else:
        result = asyncio.run(bulk_load_kr(tickers, limit or 15))

    loaded = sum(1 for v in result.values() if v > 0)
    total = sum(v for v in result.values() if v > 0)
    print(f"Loaded {total} facts across {loaded} tickers.")
    for t, n in sorted(result.items()):
        print(f"  {t}: {n} facts" if n >= 0 else f"  {t}: FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
