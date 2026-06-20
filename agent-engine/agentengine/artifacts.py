"""Chartable tool results → typed live artifacts (U3).

Pure data-shaping of known datasets shapes (prices / metrics-history / income
statements) into `Artifact` timeseries, plus the refresh path that re-runs a pinned
artifact's tool through the gateway. NOT reasoning — which tools to call is the
planner's job.
"""

from __future__ import annotations

from agentengine.client import PlatformClient
from agentengine.freshness import compute_freshness
from agentengine.models import Artifact, ArtifactPoint, ArtifactSeries
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
        pts = [ArtifactPoint(x=str(p.get("time"))[:10], y=_num(p.get("close")))
               for p in data["prices"] if p.get("time")]
        a = _timeseries(f"{data.get('ticker') or ''} 종가", [ArtifactSeries(label="종가", points=pts)],
                        src, name, data.get("ticker"), url)
        if a:
            out.append(a)

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
