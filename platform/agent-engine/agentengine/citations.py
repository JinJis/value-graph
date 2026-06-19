"""Tool result → citations: provenance-bearing source cards + the extracted figures.

Pure data-shaping of known datasets/RAG/news result shapes (NOT reasoning — which
tools to call is the planner's job). Produces `Citation` objects (with the real
figures + a /evidence link where available), dedupes them, and marks which actually
backed the answer (evidence vs merely consulted).
"""

from __future__ import annotations

import re

from agentengine.evidence import _evidence_url
from agentengine.freshness import compute_freshness
from agentengine.models import Artifact, Citation
from agentengine.provenance import (
    _PROV_KEYS,
    _canonical_provenance,
    _filing_link,
    _market_hint,
    _rag_link,
)

# filing-ish doc_type hints (RAG provenance) → the "filing" preview-card variant.
_FILING_HINTS = ("10-k", "10-q", "8-k", "20-f", "6-k", "s-1", "filing", "annual", "quarterly")
# datasets tools whose citation renders as a "metric computation" card, not raw data.
_METRIC_HINTS = ("price", "metric", "snapshot", "financ", "ratio", "screener", "earnings")


def _fmt_ratio(v) -> str:
    return f"{v * 100:.1f}%" if isinstance(v, (int, float)) else "—"


def _fmt_amt(v) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    a = abs(v)
    if a >= 1e12:
        return f"{v / 1e12:.2f}T"
    if a >= 1e9:
        return f"{v / 1e9:.2f}B"
    if a >= 1e6:
        return f"{v / 1e6:.2f}M"
    return f"{v:,.0f}" if a >= 1 else f"{v:.4f}"


# known result shapes → (snippet, table[header-first]) showing the SPECIFIC figures used.
_METRIC_COLS = (("gross_margin", "매출총이익률", _fmt_ratio), ("operating_margin", "영업이익률", _fmt_ratio),
                ("net_margin", "순이익률", _fmt_ratio), ("return_on_equity", "ROE", _fmt_ratio))
_INCOME_COLS = (("revenue", "매출", _fmt_amt), ("operating_income", "영업이익", _fmt_amt),
                ("net_income", "순이익", _fmt_amt))
_BALANCE_COLS = (("total_assets", "자산총계", _fmt_amt), ("total_liabilities", "부채총계", _fmt_amt),
                 ("shareholders_equity", "자본총계", _fmt_amt))
_CASHFLOW_COLS = (("net_cash_flow_from_operations", "영업활동CF", _fmt_amt),
                  ("net_cash_flow_from_investing", "투자활동CF", _fmt_amt),
                  ("net_cash_flow_from_financing", "재무활동CF", _fmt_amt))


def _shape_table(rows: list[dict], period_key: str, cols, period_label: str):
    rows = [r for r in rows if isinstance(r, dict)][:6]
    use = [(k, lbl, fn) for k, lbl, fn in cols if any(r.get(k) is not None for r in rows)]
    if not rows or not use:
        return None, None
    header = [period_label] + [lbl for _, lbl, _ in use]
    table = [header]
    for r in rows:
        table.append([str(r.get(period_key) or "—")] + [fn(r.get(k)) for k, _, fn in use])
    top = rows[0]
    snippet = " · ".join(f"{lbl} {fn(top.get(k))}" for k, lbl, fn in use if top.get(k) is not None)
    if top.get(period_key):
        snippet += f" ({top.get(period_key)})"
    return snippet or None, table


def _evidence(tool: dict, data) -> tuple[str | None, list[list[str]] | None]:
    """The specific figures a structured result contributed — a one-line computation
    summary + a small extracted table — so the preview shows real data, not a label."""
    if not isinstance(data, dict):
        return None, None
    if isinstance(data.get("metrics"), list):
        return _shape_table(data["metrics"], "report_period", _METRIC_COLS, "기간")
    if isinstance(data.get("income_statements"), list):
        return _shape_table(data["income_statements"], "report_period", _INCOME_COLS, "기간")
    if isinstance(data.get("balance_sheets"), list):
        return _shape_table(data["balance_sheets"], "report_period", _BALANCE_COLS, "기간")
    if isinstance(data.get("cash_flow_statements"), list):
        return _shape_table(data["cash_flow_statements"], "report_period", _CASHFLOW_COLS, "기간")
    if isinstance(data.get("prices"), list):
        rows = [r for r in data["prices"] if isinstance(r, dict)]
        rows = sorted(rows, key=lambda r: str(r.get("time") or ""), reverse=True)[:6]
        pr = [r for r in rows if r.get("close") is not None]
        if pr:
            table = [["날짜", "종가"]] + [[str(r.get("time"))[:10], _fmt_amt(r.get("close"))] for r in pr]
            top = pr[0]
            return f"종가 {_fmt_amt(top.get('close'))} ({str(top.get('time'))[:10]})", table
    # generic fallback: first list-of-dicts → a compact table of its real values
    for v in data.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            rows = [r for r in v if isinstance(r, dict)][:6]
            keys = [k for k in rows[0] if k.lower() not in _PROV_KEYS
                    and isinstance(rows[0].get(k), (int, float, str))][:4]
            if not keys:
                break
            header = keys
            table = [header] + [[_fmt_amt(r.get(k)) if isinstance(r.get(k), (int, float)) else str(r.get(k) or "—")
                                 for k in keys] for r in rows]
            snippet = " · ".join(f"{k} {table[1][i]}" for i, k in enumerate(keys))
            return snippet or None, table
    return None, None


def _rag_type(prov: dict) -> str:
    dt = (prov.get("doc_type") or "").lower()
    if dt == "news":
        return "news"
    if prov.get("accession") or any(h in dt for h in _FILING_HINTS):
        return "filing"
    return "data"


def _datasets_type(tool: dict) -> str:
    return "metric" if any(h in tool["name"].lower() for h in _METRIC_HINTS) else "data"


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _collect_dates(obj, out: list) -> None:
    """Gather YYYY-MM-DD values under date-ish keys (report_period / as_of / date / filing_date)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and _DATE_RE.match(v) and any(t in k.lower() for t in ("date", "period", "as_of")):
                out.append(v[:10])
            else:
                _collect_dates(v, out)
    elif isinstance(obj, list):
        for x in obj[:50]:
            _collect_dates(x, out)


def _latest_date(data) -> str | None:
    """Most recent date-ish value in a datasets response — the figure's as-of."""
    found: list[str] = []
    _collect_dates(data, found)
    return max(found) if found else None


def _news_citations(tool: dict, data) -> list[Citation] | None:
    """Google News (/news) returns articles that each carry their OWN publisher +
    headline + date — cite those, not the connector's generic 'Google News' label."""
    items = data.get("news") if isinstance(data, dict) else None
    if not items:
        return None
    cites, seen = [], set()
    for a in items[:6]:
        if not isinstance(a, dict):
            continue
        url = a.get("url")
        src = a.get("source") or tool.get("source") or "Google News"  # publisher (Reuters/연합뉴스/…)
        key = (src, url)
        if key in seen:
            continue
        seen.add(key)
        as_of = a.get("date")
        cites.append(Citation(
            tool=tool["name"], source=src, url=url, kind="news", doc_type="news",
            as_of=as_of, freshness=compute_freshness(as_of),
            snippet=(a.get("title") or "")[:300] or None, ticker=a.get("ticker"),
        ))
    return cites or None


def _rag_citations(tool: dict, data) -> list[Citation] | None:
    """RAG returns passages that each carry their OWN provenance — cite those
    (the real document source/url), not the connector's generic label."""
    hits = data.get("hits") if isinstance(data, dict) else None
    if not hits:
        return None
    cites, seen = [], set()
    for h in hits[:5]:
        prov = (h or {}).get("provenance") or {}
        src, url = prov.get("source"), _rag_link(prov)
        key = (src, url)
        if not (src or url) or key in seen:
            continue
        seen.add(key)
        as_of = prov.get("as_of")
        cites.append(Citation(
            tool=tool["name"], source=src or tool.get("source"), url=url,
            kind=_rag_type(prov), doc_type=prov.get("doc_type"), as_of=as_of,
            freshness=compute_freshness(as_of),
            snippet=((h or {}).get("text") or "")[:300] or None,
            ticker=prov.get("ticker"), page=prov.get("section") or prov.get("accession"),
        ))
    return cites or None


def _citations(tool: dict, result: dict) -> list[Citation]:
    data = result.get("data")
    if "search" in tool["name"] or tool.get("connector") == "rag":
        rag = _rag_citations(tool, data)
        if rag is not None:
            return rag
    if tool.get("connector") == "google_news" or tool["name"].endswith("__news"):
        news = _news_citations(tool, data)
        if news is not None:
            return news
    src = tool.get("source")
    ctype = _datasets_type(tool)
    market = _market_hint(tool, data)
    # A filings *listing* → one evidence card per distinct filing document (each its
    # own source: its filing_url + what the filing is).
    if isinstance(data, dict) and isinstance(data.get("filings"), list):
        out, seen = [], set()
        for f in data["filings"][:6]:
            if not isinstance(f, dict):
                continue
            u = (f.get("filing_url") or f.get("source_url") or f.get("url")
                 or _filing_link(market, f.get("accession_number"), f.get("cik")))
            if not u or u in seen:
                continue
            seen.add(u)
            fa = f.get("filed") or f.get("report_period") or f.get("as_of")
            fa = str(fa)[:10] if fa else None
            out.append(Citation(
                tool=tool["name"], source=src, url=u, kind="filing", as_of=fa,
                freshness=compute_freshness(fa), page=f.get("accession_number"),
                snippet=(f.get("title") or f.get("form") or f.get("filing_type") or None)))
        if out:
            return out
    # Derived figures (financials / metrics / prices): show the SPECIFIC figures used +
    # link to the exact filing they came from — not a label or a directory listing.
    as_of = _latest_date(data)
    url, accn, cik = _canonical_provenance(data)        # canonical filing link / accession
    if not url and accn:                                # build it from the identifier
        url = _filing_link(market, accn, cik)
    snippet, table = _evidence(tool, data)              # the real figures + extracted table
    return [Citation(tool=tool["name"], source=src, url=url, kind=ctype, as_of=as_of,
                     freshness=compute_freshness(as_of), snippet=snippet, table=table, page=accn,
                     evidence_image_url=_evidence_url(data, accn, cik, market))]


def dedup_citations(cites: list[Citation]) -> list[Citation]:
    """Collapse repeats — the same (source, url) cited by several tool calls should
    appear once (fixes the '📎 OpenDART · 📎 OpenDART · …' repetition)."""
    seen: set = set()
    out: list[Citation] = []
    for c in cites:
        key = (c.source, c.url)
        if key in seen:
            continue
        seen.add(key)
        c.index = len(out) + 1  # 1-based [n] anchor
        out.append(c)
    return out


# --- PH-4c: inline [n] source anchors -----------------------------------------
_ANCHOR_RE = re.compile(r"\[\d+\]")


def has_anchors(text: str | None) -> bool:
    """True if the prose already carries inline [n] markers (e.g. gemini wrote them)."""
    return bool(_ANCHOR_RE.search(text or ""))


def anchor_markers(indices) -> str:
    """Compact trailing anchor group: [1][2][3] (the deterministic floor when the
    model didn't place markers inline — keeps every answer source-anchored)."""
    return "".join(f"[{i}]" for i in indices if i)


def mark_evidence(cites: list[Citation], answer: str, artifacts: list[Artifact]) -> list[Citation]:
    """Flag which citations are *evidence* (actually backed the answer) vs merely
    consulted. Evidence = cited by [n] in the prose OR backs a rendered artifact.
    The Live Context shows only evidence; everything consulted stays in 도구·출처.
    When the model wrote no inline [n] at all, evidence falls back to the citations
    that actually returned data (a url / snippet / table) — never the bare labels."""
    cited = {int(m) for m in re.findall(r"\[(\d+)\]", answer or "")}
    art_tools = {a.tool for a in artifacts if a.tool}
    for c in cites:
        c.used = (c.index in cited) or (c.tool in art_tools)
    if cites and not any(c.used for c in cites):
        data_bearing = [c for c in cites if c.url or c.snippet or c.table]
        for c in (data_bearing or cites):
            c.used = True
    return cites
