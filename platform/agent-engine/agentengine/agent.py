"""The agent loop: guardrail → plan → call tool (via gateway) → observe → finalize.

Tools = the tenant's activated connectors + RAG (resolved from the gateway
catalog). Every tool result's provenance is collected into citations, so agent
answers are sourced.
"""

from __future__ import annotations

import json
import logging
import re
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


def _rag_type(prov: dict) -> str:
    dt = (prov.get("doc_type") or "").lower()
    if dt == "news":
        return "news"
    if prov.get("accession") or any(h in dt for h in _FILING_HINTS):
        return "filing"
    return "data"


def _datasets_type(tool: dict) -> str:
    return "metric" if any(h in tool["name"].lower() for h in _METRIC_HINTS) else "data"


def _find_urls(obj, out: list | None = None) -> list:
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("http") and ("url" in k.lower() or "filing" in k.lower()):
                out.append(v)
            else:
                _find_urls(v, out)
    elif isinstance(obj, list):
        for x in obj[:30]:
            _find_urls(x, out)
    return out


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
        src, url = prov.get("source"), prov.get("url")
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
    # financials / metrics: enrich with the figure's as-of (latest report period) + freshness
    src = tool.get("source")
    ctype = _datasets_type(tool)
    as_of = _latest_date(data)
    fresh = compute_freshness(as_of)
    urls = list(dict.fromkeys(_find_urls(data)))[:5]
    if not urls:
        return [Citation(tool=tool["name"], source=src, kind=ctype, as_of=as_of, freshness=fresh)]
    return [Citation(tool=tool["name"], source=src, url=u, kind=ctype, as_of=as_of, freshness=fresh) for u in urls]


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _timeseries(title: str, series: list[ArtifactSeries], source, tool_name, ticker) -> Artifact | None:
    series = [s for s in series if s.points]
    if not series:
        return None
    as_of = max((p.x for s in series for p in s.points if p.x), default=None)
    lengths = {len(s.points) for s in series}
    return Artifact(
        kind="timeseries", title=title.strip() or "추이", series=series, source=source,
        as_of=as_of, freshness=compute_freshness(as_of), ticker=ticker,
        has_gap=len(lengths) > 1,  # series of differing coverage → a gap to draw
        tool=tool_name,
    )


# Chartable tool results → a typed artifact. Pure data-shaping of a known API shape
# (like _citations) — NOT reasoning; which tools to call is still the model's job.
def _artifacts(tool: dict, result: dict) -> list[Artifact]:
    data = result.get("data")
    if not isinstance(data, dict):
        return []
    name, src = tool["name"], tool.get("source")
    out: list[Artifact] = []

    if name.endswith("__prices") and isinstance(data.get("prices"), list):
        # the Price model's date lives in `time` (no `date` field); take the date part.
        pts = [ArtifactPoint(x=str(p.get("time"))[:10], y=_num(p.get("close")))
               for p in data["prices"] if p.get("time")]
        a = _timeseries(f"{data.get('ticker') or ''} 종가", [ArtifactSeries(label="종가", points=pts)],
                        src, name, data.get("ticker"))
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
        a = _timeseries(f"{data.get('ticker') or ''} 재무비율 추이", series, src, name, data.get("ticker"))
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
        a = _timeseries(f"{ticker or ''} 매출·순이익", series, src, name, ticker)
        if a:
            out.append(a)

    return out


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
                    artifacts.append(a)
            history.append((decision, result))
        if not answer:
            answer = fallback_answer(dedup_citations(citations))
    except Exception as e:
        logger.exception("Error in run_agent loop")
        # Honest degrade on a planner/LLM error rather than a 500.
        answer = answer or f"답변 생성 중 문제가 발생했어요. 잠시 후 다시 시도해 주세요. ({type(e).__name__}: {str(e)})"

    cites = dedup_citations(citations)
    # Ensure the answer is source-anchored: if the planner didn't write inline [n]
    # markers, append a trailing anchor group so every claim ties to the citations.
    if cites and answer and not has_anchors(answer):
        answer = answer.rstrip() + " " + anchor_markers([c.index for c in cites])
    return RunResult(answer=answer, steps=steps, citations=cites, artifacts=artifacts, usage={"steps": len(steps)})
