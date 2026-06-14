"""Curated backfill universes (PH-1).

Picking which companies to backfill should be a choice in the admin console, not a
hand-typed ticker list. These presets are sensible, rate-limit-friendly sets of
large caps; an operator selects one and the store fills with a meaningful sample
(so the screener / historical endpoints become useful, not a 4-ticker demo).

Full-market US backfill (the ~10k+ SEC `companyfacts.zip` stream) is intentionally
NOT a preset here — it's a heavy, separate path (bulk._load_us_zip) for later.
"""

from __future__ import annotations

# US: clean SEC tickers (avoid dotted symbols like BRK.B for now).
_US_MEGA = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "LLY", "JPM",
    "V", "UNH", "XOM", "MA", "COST",
]
_US_LARGE = _US_MEGA + [
    "HD", "PG", "JNJ", "ABBV", "WMT", "NFLX", "CRM", "BAC", "KO", "AMD",
    "PEP", "TMO", "CSCO", "ADBE", "MCD", "WFC", "ABT", "INTC", "QCOM", "TXN",
    "DIS", "CAT", "GE", "VZ", "INTU", "AMAT", "PFE", "CMCSA", "NKE", "HON",
]

# KR: KRX 6-digit codes (KOSPI large caps).
_KR_LARGE = [
    "005930", "000660", "005380", "035420", "035720", "051910", "006400", "207940",
    "005490", "105560", "055550", "000270", "068270", "012330", "028260", "066570",
    "003550", "015760", "017670", "030200",
]

# id -> (label, market, tickers)
PRESETS: dict[str, dict] = {
    "us_mega": {"label": "US 메가캡 (~15)", "market": "US", "tickers": _US_MEGA},
    "us_large": {"label": "US 대형주 (~45)", "market": "US", "tickers": _US_LARGE},
    "kr_large": {"label": "KR 대형주 (~20)", "market": "KR", "tickers": _KR_LARGE},
}


def list_presets() -> list[dict]:
    return [
        {"id": k, "label": v["label"], "market": v["market"], "count": len(v["tickers"])}
        for k, v in PRESETS.items()
    ]


def get_preset(preset_id: str) -> dict | None:
    return PRESETS.get(preset_id)
