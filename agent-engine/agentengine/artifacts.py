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
    ChartOverlay,
    OverlayLine,
    OverlayPoint,
)
from agentengine.provenance import _canonical_provenance, _filing_link, _market_hint


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _timeseries(title: str, series: list[ArtifactSeries], source, tool_name, ticker, url=None,
                chart_style: str | None = None) -> Artifact | None:
    series = [s for s in series if s.points]
    if not series:
        return None
    as_of = max((p.x for s in series for p in s.points if p.x), default=None)
    lengths = {len(s.points) for s in series}
    return Artifact(
        kind="timeseries", title=title.strip() or "추이", series=series, source=source,
        # money amounts (revenue/income) read better as bars; ratios/prices stay lines.
        chart_style=chart_style,
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
        a = _timeseries(f"{ticker or ''} 매출·순이익", series, src, name, ticker, url, chart_style="bar")
        if a:
            out.append(a)

    if name.endswith("__asset_classes") and isinstance(data.get("groups"), list):
        # CE-1: cross-asset snapshot → a sourced table card (자산군 현황).
        def _px(v):
            return f"{v:,.2f}" if isinstance(v, (int, float)) else "—"

        def _pct(v):
            return f"{v:+.2f}%" if isinstance(v, (int, float)) else "—"

        rows = [["자산군", "종목", "현재가", "등락%"]]
        for g in data["groups"]:
            for m in (g.get("members") or []):
                rows.append([g.get("name", ""), m.get("label") or m.get("ticker", ""),
                             _px(m.get("price")), _pct(m.get("change_percent"))])
        if len(rows) > 1:
            out.append(Artifact(kind="table", title="자산군 현황", table=rows,
                                source=src or "Yahoo Finance", as_of=data.get("as_of"),
                                freshness=compute_freshness(data.get("as_of")), tool=name))

    if name.endswith("__valuation") and data.get("model"):
        # CE-5: a transparent valuation calc → a sourced table (projection + intrinsic value).
        model = str(data.get("model")).upper()
        vps = data.get("value_per_share")
        bd = data.get("breakdown") or {}
        rows_in = bd.get("rows") or []

        def _m(v):  # money, abbreviated
            if not isinstance(v, (int, float)):
                return "—"
            a = abs(v)
            if a >= 1e9:
                return f"{v/1e9:,.2f}B"
            if a >= 1e6:
                return f"{v/1e6:,.1f}M"
            return f"{v:,.2f}"

        if data.get("model") == "rim":
            table = [["연차", "BVPS", "잔여이익", "현재가치"]] + [
                [str(r.get("year")), _m(r.get("bvps")), _m(r.get("residual_income")), _m(r.get("pv"))] for r in rows_in]
        elif data.get("model") == "dcf":
            table = [["연차", "예상 FCF", "현재가치(PV)"]] + [
                [str(r.get("year")), _m(r.get("fcf")), _m(r.get("pv"))] for r in rows_in]
        else:  # ddm — no projection rows; show the components
            table = [["구분", "값"], ["D0 (현재 배당)", _m(bd.get("d0"))], ["D1", _m(bd.get("d1"))]]
        if isinstance(vps, (int, float)):  # summary row, padded to the table's column count
            cols = len(table[0])
            table.append((["내재가치 / 주", f"{vps:,.2f}"] + [""] * cols)[:cols])
        title = f"{data.get('ticker') or ''} {model} 내재가치"
        if isinstance(vps, (int, float)):
            title += f" — {vps:,.2f}/주 (가정 기반)"
        if len(table) > 1:
            out.append(Artifact(kind="table", title=title.strip(), table=table,
                                source=data.get("source") or "재무제표 기반 모델", as_of=data.get("as_of"),
                                freshness=compute_freshness(data.get("as_of")), tool=name,
                                ticker=data.get("ticker")))

    if name.endswith("__sector_heatmap") and isinstance(data.get("sectors"), list):
        # CE-2: US sector heatmap → a sourced, ranked table card (섹터 히트맵).
        def _pct(v):
            return f"{v:+.2f}%" if isinstance(v, (int, float)) else "—"

        rows = [["섹터", "ETF", "등락%"]]
        for s in data["sectors"]:
            rows.append([s.get("sector", ""), s.get("ticker", ""), _pct(s.get("change_percent"))])
        if len(rows) > 1:
            out.append(Artifact(kind="table", title="섹터 히트맵 (S&P 500)", table=rows,
                                source=src or "Yahoo Finance", as_of=data.get("as_of"),
                                freshness=compute_freshness(data.get("as_of")), tool=name))

    if name.endswith("__guru_trades") and isinstance(data.get("trades"), list):
        # CE-3: 거장 매매 — quarter-over-quarter 13F moves → a sourced table card.
        def _usd(v):
            if not isinstance(v, (int, float)) or v == 0:
                return "—"
            sign = "-" if v < 0 else ""
            a = abs(v)
            if a >= 1e9:
                return f"{sign}${a/1e9:,.2f}B"
            if a >= 1e6:
                return f"{sign}${a/1e6:,.1f}M"
            return f"{sign}${a:,.0f}"

        _ACTION = {"new": "신규", "added": "추가", "trimmed": "축소", "exited": "전량매도"}
        rows = [["종목", "매매", "보유가치", "가치변동", "주식수 변동"]]
        for t in data["trades"]:
            sc = t.get("shares_change")
            sc_s = f"{sc:+,}" if isinstance(sc, (int, float)) else "—"
            rows.append([
                t.get("ticker") or t.get("name_of_issuer") or t.get("cusip", ""),
                _ACTION.get(t.get("action"), t.get("action", "")),
                _usd(t.get("value_usd")), _usd(t.get("value_change_usd")), sc_s,
            ])
        if len(rows) > 1:
            guru = (data.get("guru") or {}).get("investor") or "거장"
            rp = data.get("report_period") or ""
            out.append(Artifact(kind="table", title=f"{guru} 매매내역 ({rp})".strip(),
                                table=rows, source=src or "SEC EDGAR 13F", as_of=data.get("filing_date"),
                                freshness=compute_freshness(data.get("filing_date")), url=url, tool=name))

    if name.endswith("__guru_common") and isinstance(data.get("common"), list):
        # CE-3: 공통 보유종목 — securities held by the most superinvestors → sourced table.
        rows = [["종목", "보유 거장 수", "보유 거장"]]
        for c in data["common"]:
            holders = ", ".join(h.get("investor", "") for h in (c.get("holders") or [])[:6])
            if len(c.get("holders") or []) > 6:
                holders += " 외"
            rows.append([
                c.get("ticker") or c.get("name_of_issuer") or c.get("cusip", ""),
                str(c.get("holder_count", len(c.get("holders") or []))), holders,
            ])
        if len(rows) > 1:
            out.append(Artifact(kind="table", title="거장 공통 보유종목", table=rows,
                                source=src or "SEC EDGAR 13F", as_of=None,
                                freshness=None, tool=name))

    if name.endswith("__technical_indicators") and isinstance(data.get("indicators"), list):
        # PH-VIZ-4: a descriptive indicator artifact. `enrich_chart_overlays` later folds
        # these onto a same-ticker price chart when one exists this turn; otherwise it
        # renders standalone (price-pane lines on the price scale, RSI/MACD as sub-panes).
        overlays = _overlays_from_technical(data)
        if overlays:
            tk = data.get("ticker")
            out.append(Artifact(
                kind="timeseries", title=f"{tk or ''} 기술적 지표".strip(),
                overlays=overlays, source=data.get("source"), as_of=data.get("as_of"),
                freshness=compute_freshness(data.get("as_of")), ticker=tk, tool=name,
            ))

    return out


# Descriptive, stable colors per indicator line (server-owned → consistent across turns).
_OVERLAY_COLORS = {
    "upper": "#9aa7bd", "lower": "#9aa7bd", "middle": "#4f8cff",
    "macd": "#4f8cff", "signal": "#D9A300", "histogram": "#86868C",
}
_OVERLAY_PALETTE = ["#4f8cff", "#D9A300", "#1FA463", "#A05CF5", "#D1483A"]


def _overlay_color(label: str, idx: int) -> str:
    lab = (label or "").lower()
    for key, color in _OVERLAY_COLORS.items():
        if key in lab:
            return color
    if lab.startswith("sma"):
        return "#4f8cff"
    if lab.startswith("ema"):
        return "#D9A300"
    if lab.startswith("rsi"):
        return "#A05CF5"
    if lab.startswith("vol"):
        return "#1FA463"
    return _OVERLAY_PALETTE[idx % len(_OVERLAY_PALETTE)]


def _overlays_from_technical(data: dict) -> list[ChartOverlay]:
    """Shape PH-DATA-6's `/technical-indicators` result into chart overlays — pure
    data-shaping (like _artifacts), drops gaps, no fabrication."""
    out: list[ChartOverlay] = []
    src = data.get("source")
    for ind in (data.get("indicators") or []):
        lines: list[OverlayLine] = []
        for i, li in enumerate(ind.get("lines") or []):
            pts = [OverlayPoint(time=str(p["date"])[:10], value=float(p["value"]))
                   for p in (li.get("points") or [])
                   if p.get("date") and p.get("value") is not None]
            if pts:
                lab = li.get("label") or ind.get("name") or ind.get("key") or "지표"
                lines.append(OverlayLine(label=lab, color=_overlay_color(lab, i), points=pts))
        if lines:
            out.append(ChartOverlay(
                key=str(ind.get("key") or ind.get("name") or "ind"),
                name=str(ind.get("name") or ind.get("key") or "지표"),
                pane=("sub" if ind.get("pane") == "sub" else "price"),
                unit=ind.get("unit"), lines=lines, source=src,
            ))
    return out


def enrich_chart_overlays(artifacts: list[Artifact]) -> None:
    """PH-VIZ-4: fold each standalone technical-indicator artifact onto the same-ticker
    price (candlestick) chart, so the overlays render ON the price. When no price chart
    exists this turn, the technical artifact stays and renders on its own. Mutates the
    list in place (removing the merged standalone artifacts)."""
    tech = [a for a in artifacts if a.overlays and a.kind != "candlestick"]
    if not tech:
        return
    merged: list[Artifact] = []
    for p in artifacts:
        if p.kind != "candlestick" or not p.candles or p.overlays:
            continue
        for t in tech:
            if t in merged:
                continue
            if (t.ticker or "").upper() == (p.ticker or "").upper():
                p.overlays = t.overlays
                merged.append(t)
    if merged:
        artifacts[:] = [a for a in artifacts if a not in merged]


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
