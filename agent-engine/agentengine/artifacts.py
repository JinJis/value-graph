"""Chartable tool results → typed live artifacts (U3).

Pure data-shaping of known datasets shapes (prices / metrics-history / income
statements) into `Artifact` timeseries, plus the refresh path that re-runs a pinned
artifact's tool through the gateway. NOT reasoning — which tools to call is the
planner's job.
"""

from __future__ import annotations

from agentengine.client import PlatformClient
from agentengine.freshness import compute_freshness
from agentengine.models import (
    Artifact,
    ArtifactCandle,
    ArtifactMarker,
    ArtifactPoint,
    ArtifactPriceLine,
    ArtifactSeries,
)
from agentengine.provenance import _canonical_provenance, _filing_link, _market_hint


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _timeseries(title: str, series: list[ArtifactSeries], source, tool_name, ticker, url=None) -> Artifact | None:
    series = [s for s in series if s.points]
    if not series:
        return None
    as_of = max((p.x for s in series for p in s.points if p.x), default=None)
    lengths = {len(s.points) for s in series}
    return Artifact(
        kind="timeseries", title=title.strip() or "추이", series=series, source=source,
        as_of=as_of, freshness=compute_freshness(as_of), ticker=ticker,
        has_gap=len(lengths) > 1,  # series of differing coverage → a gap to draw
        url=url, tool=tool_name,
    )


# Chartable tool results → a typed artifact. Pure data-shaping of a known API shape
# (like _citations) — NOT reasoning; which tools to call is still the model's job.
def _artifacts(tool: dict, result: dict) -> list[Artifact]:
    data = result.get("data")
    if not isinstance(data, dict):
        return []
    name, src = tool["name"], tool.get("source")
    out: list[Artifact] = []
    # canonical link to the filing the figures came from (drawn on the artifact card)
    url, accn, cik = _canonical_provenance(data)
    if not url and accn:
        url = _filing_link(_market_hint(tool, data), accn, cik)

    if name.endswith("__prices") and isinstance(data.get("prices"), list):
        # the Price model's date lives in `time` (no `date` field); take the date part.
        rows = sorted((p for p in data["prices"] if p.get("time")), key=lambda p: str(p.get("time")))
        # PH-VIZ-1: real OHLCV → candlestick + volume. Keep a close-line series too (table view).
        candles = [ArtifactCandle(time=str(p.get("time"))[:10], open=_num(p.get("open")), high=_num(p.get("high")),
                                  low=_num(p.get("low")), close=_num(p.get("close")), volume=_num(p.get("volume")))
                   for p in rows]
        has_ohlc = any(c.open is not None and c.high is not None and c.low is not None for c in candles)
        pts = [ArtifactPoint(x=c.time, y=c.close) for c in candles]
        series = [ArtifactSeries(label="종가", points=pts)]
        as_of = max((p.x for p in pts if p.x), default=None)
        if pts:
            out.append(Artifact(
                kind="candlestick" if has_ohlc else "timeseries",
                title=f"{data.get('ticker') or ''} 주가".strip(), series=series,
                candles=candles if has_ohlc else [], source=src, as_of=as_of,
                freshness=compute_freshness(as_of), ticker=data.get("ticker"), url=url, tool=name,
            ))

    if name.endswith("__metrics_history") and isinstance(data.get("metrics"), list):
        rows = data["metrics"]
        series = []
        for key, label in (("gross_margin", "매출총이익률"), ("operating_margin", "영업이익률"), ("net_margin", "순이익률")):
            pts = [ArtifactPoint(x=str(r.get("report_period")), y=_num(r.get(key)))
                   for r in rows if r.get("report_period") and r.get(key) is not None]
            if pts:
                series.append(ArtifactSeries(label=label, unit="ratio", points=sorted(pts, key=lambda p: p.x)))
        a = _timeseries(f"{data.get('ticker') or ''} 재무비율 추이", series, src, name, data.get("ticker"), url)
        if a:
            out.append(a)

    if name.endswith("__income_statements") and isinstance(data.get("income_statements"), list):
        rows = data["income_statements"]
        ticker = (rows[0].get("ticker") if rows else None)
        series = []
        for key, label in (("revenue", "매출"), ("net_income", "순이익")):
            pts = [ArtifactPoint(x=str(r.get("report_period")), y=_num(r.get(key)))
                   for r in rows if r.get("report_period") and r.get(key) is not None]
            if pts:
                series.append(ArtifactSeries(label=label, points=sorted(pts, key=lambda p: p.x)))
        a = _timeseries(f"{ticker or ''} 매출·순이익", series, src, name, ticker, url)
        if a:
            out.append(a)

    return out


def _is_date(s: str) -> bool:
    import re
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", s or ""))


def _price_lines(a: Artifact) -> list[ArtifactPriceLine]:
    """PH-VIZ-2: descriptive period high/low reference lines, drawn from the price data
    itself (no extra source needed). 52-week label only when the span really covers ~1y."""
    highs = [c.high for c in a.candles if c.high is not None]
    lows = [c.low for c in a.candles if c.low is not None]
    if not highs or not lows:
        closes = [p.y for s in a.series for p in s.points if p.y is not None]
        if not closes:
            return []
        highs, lows = closes, closes
    n = len(a.candles) if a.candles else (len(a.series[0].points) if a.series else 0)
    span = "52주" if n >= 200 else "기간"
    return [ArtifactPriceLine(price=round(max(highs), 4), label=f"{span} 고가", color="#1FA463"),
            ArtifactPriceLine(price=round(min(lows), 4), label=f"{span} 저가", color="#D1483A")]


def _event_markers(history: list, ticker: str | None) -> list[ArtifactMarker]:
    """Sourced event markers for the price chart, gathered from THIS turn's corporate-actions
    + earnings results (same ticker). Each marker keeps its source so a click opens evidence."""
    tk = (ticker or "").upper()
    out: list[ArtifactMarker] = []
    for dec, res in history:
        data = (res or {}).get("data")
        if not isinstance(data, dict):
            continue
        name = getattr(dec, "tool", "") or ""
        dtk = str(data.get("ticker") or "").upper()
        if tk and dtk and dtk != tk:
            continue
        if name.endswith("__corporate_actions"):
            for d in (data.get("dividends") or []):
                ex = str((d or {}).get("ex_date") or "")[:10]
                amt = (d or {}).get("amount")
                if _is_date(ex):
                    out.append(ArtifactMarker(time=ex, label="배당", kind="dividend", position="belowBar",
                                              color="#4f8cff", source="Yahoo Finance",
                                              snippet=f"배당락일 {ex}" + (f" · 주당 {amt}" if amt is not None else "")))
            for s in (data.get("splits") or []):
                dt = str((s or {}).get("date") or "")[:10]
                ratio = (s or {}).get("ratio")
                if _is_date(dt):
                    out.append(ArtifactMarker(time=dt, label="분할", kind="split", position="belowBar",
                                              color="#D9A300", source="Yahoo Finance",
                                              snippet=f"주식분할 {dt}" + (f" · {ratio}" if ratio else "")))
        elif name.endswith("__earnings"):
            mkt = str(data.get("market") or "").upper()
            esrc = "OpenDART (FSS)" if mkt == "KR" else "SEC EDGAR"
            for e in (data.get("earnings") or []):
                dt = str((e or {}).get("filing_date") or (e or {}).get("report_period") or "")[:10]
                if _is_date(dt):
                    out.append(ArtifactMarker(time=dt, label="실적", kind="earnings", position="aboveBar",
                                              color="#9aa7bd", source=esrc, url=(e or {}).get("filing_url"),
                                              snippet=f"실적 공시 {dt}"))
    seen, dedup = set(), []
    for m in sorted(out, key=lambda m: m.time):
        k = (m.time, m.kind)
        if k not in seen:
            seen.add(k)
            dedup.append(m)
    return dedup[:50]


def enrich_chart_markers(artifacts: list[Artifact], history: list) -> None:
    """PH-VIZ-2: attach descriptive price lines + sourced event markers to price charts.
    Mutates the artifacts in place. The chart literally shows the cited events on the timeline."""
    for a in artifacts:
        if a.kind != "candlestick" or not a.candles:  # markers/lines belong on the price chart
            continue
        if not a.pricelines:
            a.pricelines = _price_lines(a)
        if not a.markers:
            a.markers = _event_markers(history, a.ticker)


async def refresh_artifact(tool_name: str, args: dict | None, api_key: str | None, title: str | None = None) -> Artifact | None:
    """Re-run one tool through the gateway and re-shape its result into a fresh artifact
    (U3-03b). Returns the artifact matching `title` if given, else the first produced."""
    client = PlatformClient(api_key)
    tools = await client.fetch_tools()
    tool = tools.get(tool_name)
    if tool is None:
        return None
    result = await client.call_tool(tool, args or {})
    arts = _artifacts(tool, result)
    for a in arts:
        a.args = args or {}
    if title:
        match = next((a for a in arts if a.title == title), None)
        if match is not None:
            return match
    return arts[0] if arts else None
