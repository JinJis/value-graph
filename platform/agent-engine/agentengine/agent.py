"""The agent loop: guardrail → plan → call tool (via gateway) → observe → finalize.

Tools = the tenant's activated connectors + RAG (resolved from the gateway
catalog). Every tool result's provenance is collected into citations, so agent
answers are sourced.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlencode

from agentengine import guardrails
from agentengine.client import PlatformClient
from agentengine.config import settings
from agentengine.freshness import compute_freshness
from agentengine.models import Artifact, ArtifactPoint, ArtifactSeries, AgentSpec, Citation, RunResult, Step
from agentengine.planner import get_planner

logger = logging.getLogger(__name__)

# filing-ish doc_type hints (RAG provenance) → the "filing" preview-card variant.
_FILING_HINTS = ("10-k", "10-q", "8-k", "20-f", "6-k", "s-1", "filing", "annual", "quarterly")
# datasets tools whose citation renders as a "metric computation" card, not raw data.
_METRIC_HINTS = ("price", "metric", "snapshot", "financ", "ratio", "screener", "earnings")


# --- canonical filing links ---------------------------------------------------
# Mirror of datasets `app.store.provenance` — agent-engine is a separate deployable,
# so the tiny builder is duplicated here on purpose (can't import across services).
def _sec_index_url(cik, accession) -> str | None:
    if not accession or not cik:
        return None
    nodash = str(accession).replace("-", "")
    if len(nodash) != 18:
        return None
    dashed = accession if "-" in str(accession) else f"{nodash[:10]}-{nodash[10:12]}-{nodash[12:]}"
    try:
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nodash}/{dashed}-index.htm"
    except (TypeError, ValueError):
        return None


def _filing_link(market, accession, cik=None) -> str | None:
    """Canonical link to the *specific filing* — SEC index page / DART rcpNo viewer."""
    if not accession:
        return None
    m = (market or "").upper()
    if m == "KR":
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={accession}"
    if m == "US":
        return _sec_index_url(cik, accession)
    return None


def _evidence_url(data, accn, cik, market) -> str | None:
    """PH-PROV2: the datasets `/evidence?…` URL for a US filing-backed result's headline
    figure (an as-reported line item, which carries an explicit us-gaap concept). The
    frontend fetches the highlighted screenshot lazily — we only attach the link here, so
    the answer stream is never blocked on a render. None when there's nothing to point at."""
    if (market or "").upper() != "US" or not accn or not isinstance(data, dict):
        return None
    periods = data.get("periods")  # as-reported shape: [{report_period, line_items:[{concept,value}]}]
    if not isinstance(periods, list) or not periods:
        return None
    p = periods[0] if isinstance(periods[0], dict) else {}
    items = [it for it in (p.get("line_items") or []) if isinstance(it, dict)]
    if not items:
        return None
    pick = next((it for it in items if "Revenue" in (it.get("concept") or "")), items[0])
    if pick.get("value") is None or not pick.get("concept"):
        return None
    q = {"market": "US", "accession": accn, "concept": pick["concept"],
         "report_period": p.get("report_period"), "value": pick["value"]}
    if cik:
        q["cik"] = cik
    return "/evidence?" + urlencode(q)


def _market_hint(tool: dict, data) -> str | None:
    """KR vs US for link-building: the data's own market field, else the connector."""
    if isinstance(data, dict) and isinstance(data.get("market"), str) and data["market"]:
        return data["market"].upper()
    conn = (tool.get("connector") or tool.get("name") or "").lower()
    if "dart" in conn or "opendart" in conn or "kis" in conn:
        return "KR"
    if "sec" in conn or "edgar" in conn or "yahoo" in conn or "fred" in conn:
        return "US"
    return None


_CANON_URL_KEYS = ("filing_url", "source_url")
_PROV_KEYS = {"filing_url", "source_url", "accession_number", "cik", "url", "ticker",
              "market", "currency", "period", "fiscal_period", "source"}


def _canonical_provenance(data) -> tuple[str | None, str | None, str | None]:
    """(url, accession, cik) from the first row carrying a *canonical* filing link or
    accession — never an incidental url (a directory listing is not the filing)."""
    found = {"url": None, "accn": None, "cik": None}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                kl = k.lower()
                if found["url"] is None and isinstance(v, str) and v.startswith("http") and kl in _CANON_URL_KEYS:
                    found["url"] = v
                elif found["accn"] is None and kl == "accession_number" and v:
                    found["accn"] = str(v)
                elif found["cik"] is None and kl == "cik" and v:
                    found["cik"] = str(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o[:30]:
                walk(x)

    walk(data)
    return found["url"], found["accn"], found["cik"]


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


def _rag_link(prov: dict) -> str | None:
    """A RAG chunk's canonical link: its own url, else built from its accession."""
    return prov.get("url") or _filing_link(prov.get("market"), prov.get("accession"))


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


# --- PH-15: LLM-assessed step budget + strict finalize ------------------------
# A light model rates how many tool hops a query needs (not hardcoded keyword rules):
# simple single-fact asks finish fast; multi-source asks ("공급망·리스크 공시 요약")
# get headroom. The numbered budget is then strictly honored (the loop reserves its
# last step for synthesis, so it never leaks "Reached the step limit").
_BUDGET_PROMPT = (
    "You plan how many tool-calls a financial-research assistant needs to FULLY answer a query.\n"
    "Tools available: prices, news, company filings, financial statements, macro indicators, semantic search.\n"
    "Guidance: one fact about one company ≈ 2-3; a comparison or a multi-source ask "
    "(e.g. 'summarize a company's supply chain + risks from filings and news') ≈ 8-12.\n"
    "Reply with ONLY a single integer.\nQuery: {task}"
)


async def _llm_steps(task: str) -> int | None:
    """One cheap call to the light model → an integer step estimate (None on no parse)."""
    import asyncio

    from google import genai
    from google.genai import types

    client = genai.Client()
    resp = await asyncio.to_thread(
        client.models.generate_content,
        model=settings.budget_model,
        contents=_BUDGET_PROMPT.format(task=(task or "")[:500]),
        config=types.GenerateContentConfig(temperature=0, max_output_tokens=8),
    )
    m = re.search(r"\d+", getattr(resp, "text", "") or "")
    return int(m.group()) if m else None


async def assess_budget(task: str, backend: str | None = None) -> int:
    """LLM-assessed step budget (PH-15). Falls back to the plain default budget when
    the backend is the stub or the assessment fails — never hardcoded keyword rules."""
    cap, default, floor = settings.max_steps_cap, settings.max_steps, 3
    effective = backend or settings.llm_backend
    if effective != "gemini":
        return default
    try:
        n = await _llm_steps(task)
    except Exception as exc:  # noqa: BLE001 — degrade to the default, never block the answer
        logger.warning("budget assessment failed (%s); using default %d", exc, default)
        n = None
    return max(floor, min(n, cap)) if n else default


def call_sig(decision) -> str | None:
    """Stable signature of a tool call, to detect an identical consecutive repeat."""
    if not getattr(decision, "tool", None):
        return None
    return decision.tool + "|" + json.dumps(decision.args or {}, sort_keys=True, ensure_ascii=False)


def fallback_answer(cites) -> str:
    """A non-empty, honest answer when the model returns no final text — never leak
    'Reached the step limit.' to the user. Summarizes what was gathered + anchors."""
    cites = list(cites or [])
    if not cites:
        return ("요청하신 내용을 처리했지만 근거가 될 출처를 충분히 찾지 못했어요. "
                "종목·기간·자료 유형(공시/뉴스/재무)을 조금 더 구체적으로 알려주시면 다시 찾아볼게요.")
    srcs = ", ".join(dict.fromkeys(
        ((c.get("source") if isinstance(c, dict) else c.source) or "출처") for c in cites
    ))
    idxs = [(c.get("index") if isinstance(c, dict) else c.index) for c in cites]
    return (f"관련 자료 {len(cites)}건을 수집했어요 (출처: {srcs}). "
            f"핵심 수치·문장은 아래 출처 카드에서 확인하세요. " + anchor_markers(idxs))


def number_sources(cites) -> str:
    """Numbered source block for the final-answer prompt so the model cites with OUR
    indices — keeping inline [n] aligned to the citation list. Accepts Citation
    objects or dicts."""
    lines = []
    for c in cites:
        get = c.get if isinstance(c, dict) else (lambda k, _c=c: getattr(_c, k, None))
        idx, src = get("index"), get("source")
        if not idx or not src:
            continue
        bits = [f"[{idx}] {src}"]
        if get("snippet"):
            bits.append(str(get("snippet"))[:80])
        if get("as_of"):
            bits.append(str(get("as_of")))
        lines.append(" · ".join(bits))
    return "\n".join(lines)


def filter_tools(tools: dict, allowed: list[str] | None) -> dict:
    """Restrict ``tools`` to ``allowed`` — entries match a full tool name
    (``yahoo__prices``) or a connector id (``yahoo`` → all of its tools)."""
    if not allowed:
        return tools
    sel = set(allowed)
    return {name: t for name, t in tools.items() if name in sel or name.split("__")[0] in sel}


async def run_agent(task: str, api_key: str | None, spec: AgentSpec | None = None) -> RunResult:
    guardrailer = guardrails.get_guardrailer(spec.backend if spec else None)
    refusal = await guardrailer.check(task)
    if refusal:
        return RunResult(answer=refusal, refused=True, usage={"steps": 0})

    # PH-15: a spec can pin max_steps; otherwise a light model assesses the budget.
    max_steps = spec.max_steps if (spec and spec.max_steps) else await assess_budget(task, spec.backend if spec else None)
    system = spec.system if spec else None
    client = PlatformClient(api_key)
    tools = await client.fetch_tools()
    if spec and spec.allowed_tools:
        tools = filter_tools(tools, spec.allowed_tools)

    history: list = []
    steps: list[Step] = []
    citations: list[Citation] = []
    artifacts: list[Artifact] = []
    seen_artifacts: set = set()
    answer = ""
    try:
        planner = get_planner(spec.backend if spec else None)
        last_sig = None
        for step in range(max_steps):
            is_last = step == max_steps - 1  # reserve the last step for guaranteed synthesis
            sources = number_sources(dedup_citations(citations))  # OUR numbering (PH-4e)
            decision = await planner.plan(task, tools, history, system,
                                          force_final=is_last, sources=sources)
            if is_last or decision.final is not None:
                answer = decision.final or fallback_answer(dedup_citations(citations))
                break

            # Auto-resolve ticker from company name/alias
            if decision.tool and decision.args and "ticker" in decision.args:
                from agentengine.planner import resolve_ticker
                resolved = resolve_ticker(decision.args["ticker"])
                if resolved:
                    decision.args["ticker"] = resolved

            # an identical consecutive call means the model is stuck — synthesize now
            sig = call_sig(decision)
            if sig and sig == last_sig:
                final = await planner.plan(task, tools, history, system, force_final=True, sources=sources)
                answer = final.final or fallback_answer(dedup_citations(citations))
                break
            last_sig = sig

            tool = tools.get(decision.tool)
            if tool is None:
                answer = f"Planner selected an unavailable tool '{decision.tool}'."
                break
            result = await client.call_tool(tool, decision.args or {})
            steps.append(Step(tool=decision.tool, args=decision.args or {}, status=result["status"]))
            citations.extend(_citations(tool, result))
            for a in _artifacts(tool, result):
                if a.title not in seen_artifacts:
                    seen_artifacts.add(a.title)
                    a.args = decision.args or {}  # so a pinned card can re-fetch (U3-03)
                    artifacts.append(a)
            history.append((decision, result))
        if not answer:
            answer = fallback_answer(dedup_citations(citations))
    except Exception as e:
        logger.exception("Error in run_agent loop")
        # Honest degrade on a planner/LLM error rather than a 500.
        answer = answer or f"답변 생성 중 문제가 발생했어요. 잠시 후 다시 시도해 주세요. ({type(e).__name__}: {str(e)})"

    cites = dedup_citations(citations)
    # Mark which citations are evidence (cited [n] or back an artifact) vs consulted.
    mark_evidence(cites, answer, artifacts)
    # Ensure the answer is source-anchored: if the planner didn't write inline [n]
    # markers, append a trailing anchor group — but only for the *evidence*, so the
    # answer doesn't claim every consulted source produced its figures.
    if cites and answer and not has_anchors(answer):
        used = [c for c in cites if c.used] or cites
        answer = answer.rstrip() + " " + anchor_markers([c.index for c in used])
    return RunResult(answer=answer, steps=steps, citations=cites, artifacts=artifacts, usage={"steps": len(steps)})
