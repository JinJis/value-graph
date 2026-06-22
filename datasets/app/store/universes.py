"""Curated backfill universes (PH-1 / PH-PIPE).

Picking which companies to collect should be a choice in the admin console, not a
hand-typed ticker list. These presets are sensible, rate-limit-friendly sets of
large caps an operator selects so the store fills with a meaningful sample.

Ticker accuracy matters (a wrong KR 6-digit code = wrong company), so these lists
are HAND-VERIFIED large/mega caps — they cover the "famous names" goal, not the
literal full S&P 500 / KOSPI 200 index membership. For the full indices, paste the
official constituent list into the admin backfill's custom-tickers field (the
pipeline accepts any tickers) or extend these lists from an authoritative source.

Full-market US backfill (the ~10k SEC `companyfacts.zip` stream) stays a separate
heavy path (bulk._load_us_zip), not a preset.
"""

from __future__ import annotations

from app.symbols import Market

# --- US (clean SEC tickers; well-known S&P large/mega caps) ---------------
_US_MEGA = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "LLY", "JPM",
    "V", "UNH", "XOM", "MA", "COST",
]
_US_LARGE = _US_MEGA + [
    "HD", "PG", "JNJ", "ABBV", "WMT", "NFLX", "CRM", "BAC", "KO", "AMD",
    "PEP", "TMO", "CSCO", "ADBE", "MCD", "WFC", "ABT", "INTC", "QCOM", "TXN",
    "DIS", "CAT", "GE", "VZ", "INTU", "AMAT", "PFE", "CMCSA", "NKE", "HON",
]
# A broader ~120-name set of well-known S&P 500 constituents (hand-verified symbols).
_US_XL = _US_LARGE + [
    "ORCL", "IBM", "NOW", "UBER", "AMGN", "GILD", "BKNG", "ISRG", "MDT", "SPGI",
    "GS", "MS", "AXP", "BLK", "C", "SCHW", "PYPL", "PLTR", "MU", "LRCX",
    "KLAC", "ADI", "SNPS", "CDNS", "PANW", "CRWD", "MRVL", "FTNT", "DELL", "HPQ",
    "T", "TMUS", "CMG", "SBUX", "LOW", "TJX", "BKR", "SLB", "COP", "PSX",
    "MPC", "OXY", "KMI", "WMB", "DUK", "SO", "NEE", "D", "AEP", "EXC",
    "BMY", "MRK", "CVS", "CI", "HUM", "ELV", "ZTS", "BSX", "SYK", "BDX",
    "VRTX", "REGN", "MCK", "DHR", "TMO", "UNP", "UPS", "FDX", "BA", "LMT",
    "RTX", "GD", "NOC", "DE", "EMR", "ETN", "ITW", "PH", "MMM", "GE",
    "F", "GM", "DOW", "DD", "LIN", "APD", "SHW", "FCX", "NEM", "NUE",
    "PM", "MO", "MDLZ", "CL", "KMB", "GIS", "KHC", "STZ", "MNST", "KDP",
]

# --- KR (KRX 6-digit codes; hand-verified KOSPI large caps) ---------------
_KR_LARGE = [
    "005930", "000660", "005380", "035420", "035720", "051910", "006400", "207940",
    "005490", "105560", "055550", "000270", "068270", "012330", "028260", "066570",
    "003550", "015760", "017670", "030200",
]
_KR_KOSPI = _KR_LARGE + [
    "373220", "000810", "086790", "316140", "034730", "096770", "011200", "009150",
    "010130", "011170", "018260", "032830", "051900", "090430", "010950", "024110",
    "138040", "259960", "042660", "047810", "042700", "064350", "010140", "329180",
    "267260", "011070", "097950", "251270", "035250", "086280", "000100", "128940",
    "326030", "302440", "003670", "402340", "012450", "009830", "078930", "001570",
]
# KOSDAQ (hand-verified well-known names).
_KR_KOSDAQ = [
    "247540", "086520", "091990", "028300", "196170", "066970", "035760", "263750",
    "293490", "357780", "058470", "095340", "240810", "112040", "078600", "145020",
    "214150", "277810", "348370", "005290", "222800", "039030", "036930", "067310",
    "041510",
]

# id -> (label, market, tickers)
PRESETS: dict[str, dict] = {
    "us_mega": {"label": "US 메가캡 (~15)", "market": "US", "tickers": _US_MEGA},
    "us_large": {"label": "US 대형주 (~45)", "market": "US", "tickers": _US_LARGE},
    "us_xl": {"label": "US 주요 대형주 (~120, S&P 위주)", "market": "US", "tickers": list(dict.fromkeys(_US_XL))},
    "kr_large": {"label": "KR 대형주 (~20)", "market": "KR", "tickers": _KR_LARGE},
    "kr_kospi": {"label": "KR 코스피 주요 (~60)", "market": "KR", "tickers": list(dict.fromkeys(_KR_KOSPI))},
    "kr_kosdaq": {"label": "KR 코스닥 주요 (~25)", "market": "KR", "tickers": _KR_KOSDAQ},
}


def list_presets() -> list[dict]:
    return [
        {"id": k, "label": v["label"], "market": v["market"], "count": len(v["tickers"])}
        for k, v in PRESETS.items()
    ]


def get_preset(preset_id: str) -> dict | None:
    return PRESETS.get(preset_id)


def resolve_universe(spec: str) -> list[tuple[Market, list[str]]]:
    """Resolve a scheduler/backfill universe spec into [(Market, tickers), …].

    Accepts (a) comma-separated PRESET ids, e.g. ``"us_xl,kr_kospi"``; and/or
    (b) the legacy explicit form ``"US:AAPL,MSFT;KR:005930"``. Both may be mixed,
    separated by ``;``. Tickers for the same market are merged + de-duplicated.
    """
    by_market: dict[Market, list[str]] = {}

    def _add(mkt: Market, syms: list[str]) -> None:
        cur = by_market.setdefault(mkt, [])
        for s in syms:
            if s and s not in cur:
                cur.append(s)

    for group in (spec or "").split(";"):
        group = group.strip()
        if not group:
            continue
        if ":" in group:  # legacy explicit form "US:AAPL,MSFT"
            mkt, tickers = group.split(":", 1)
            try:
                m = Market(mkt.strip().upper())
            except ValueError:
                continue
            _add(m, [t.strip() for t in tickers.split(",") if t.strip()])
        else:  # comma-separated preset ids, e.g. "us_xl,kr_kospi"
            for pid in group.split(","):
                preset = PRESETS.get(pid.strip())
                if preset:
                    _add(Market(preset["market"]), list(preset["tickers"]))
    return [(m, t) for m, t in by_market.items() if t]
