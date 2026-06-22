"""The agent loop: guardrail → plan → call tool (via gateway) → observe → finalize.

Tools = the tenant's activated connectors + RAG (resolved from the gateway catalog).
Every tool result's provenance is collected into citations, so agent answers are sourced.

The provenance/citation/artifact *shaping* lives in focused sibling modules — this file
is the orchestration only:
  * ``provenance``  — canonical filing links + (url, accession, cik) extraction
  * ``evidence``    — the PH-PROV2 ``/evidence`` link for a figure
  * ``citations``   — tool result → source cards + extracted figures + evidence marking
  * ``artifacts``   — chartable results → live timeseries artifacts + refresh
"""

from __future__ import annotations

import json
import logging
import re

from agentengine import guardrails
from agentengine.artifacts import _artifacts
from agentengine.citations import (
    _citations,
    anchor_markers,
    dedup_citations,
    has_anchors,
    mark_evidence,
)
from agentengine.client import PlatformClient
from agentengine.config import settings
from agentengine.models import AgentSpec, Artifact, Citation, RunResult, Step
from agentengine.planner import get_planner

# Re-exported for back-compat: these moved to focused modules, but importers (chat.py,
# main.py) and tests still reference them via ``agentengine.agent``.
from agentengine.artifacts import _num, _timeseries, refresh_artifact  # noqa: E402,F401
from agentengine.citations import (  # noqa: E402,F401
    _BALANCE_COLS,
    _CASHFLOW_COLS,
    _INCOME_COLS,
    _METRIC_COLS,
    _datasets_type,
    _evidence,
    _fmt_amt,
    _fmt_ratio,
    _latest_date,
    _news_citations,
    _rag_citations,
    _rag_type,
    _shape_table,
)
from agentengine.evidence import (  # noqa: E402,F401
    _FIELD_CONCEPTS,
    _STATEMENT_HEADLINES,
    _ev_qs,
    _evidence_url,
)
from agentengine.freshness import compute_freshness  # noqa: E402,F401
from agentengine.provenance import (  # noqa: E402,F401
    _canonical_provenance,
    _filing_link,
    _market_hint,
    _rag_link,
    _sec_index_url,
)

logger = logging.getLogger(__name__)


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


_ANALYZE_PROMPT = (
    "You are a financial-research planner. Read the user's question and reply with JSON ONLY:\n"
    '{"steps": <int>, "plan": "<one short sentence, IN THE SAME LANGUAGE as the question, saying what '
    'data you will look up and from which kind of source — NOT the answer, no numbers>"}.\n'
    "steps = tool-call budget (one fact about one company ≈ 2-3; a comparison or multi-source ask ≈ 8-12).\n"
    "Question: {task}"
)


async def analyze_task(task: str, backend: str | None = None) -> tuple[int, str | None]:
    """PH-THINK: one cheap LLM pass that both sizes the step budget AND returns a short
    natural-language plan to show the user ('what I'll look up'). Stub/no-key → (default, None);
    never hardcoded keyword rules, never blocks the answer."""
    cap, default, floor = settings.max_steps_cap, settings.max_steps, 3
    if (backend or settings.llm_backend) != "gemini":
        return default, None
    try:
        import asyncio
        from google import genai
        from google.genai import types

        client = genai.Client()
        resp = await asyncio.to_thread(
            client.models.generate_content, model=settings.budget_model,
            contents=_ANALYZE_PROMPT.format(task=(task or "")[:500]),
            config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                               max_output_tokens=200))
        d = json.loads(getattr(resp, "text", "") or "{}")
        try:
            n = int(d.get("steps"))
        except (TypeError, ValueError):
            n = None
        plan = (str(d.get("plan") or "")).strip() or None
        return (max(floor, min(n, cap)) if n else default), plan
    except Exception as exc:  # noqa: BLE001 — degrade to default budget, no plan
        logger.warning("task analysis failed (%s); using default budget", exc)
        return default, None


_REFINE_PROMPT = (
    "You are a meticulous research reviewer. Given the user's question and the evidence the "
    "agent gathered (each item: source + snippet/figures), write a SHORT synthesis brief "
    "(2-4 lines, SAME LANGUAGE as the question) that: (1) names which sources actually answer "
    "the question and the key figures to use; (2) flags any conflicts or gaps; (3) gives a "
    "one-line outline for the final answer. Do NOT write the answer itself, do NOT add numbers "
    "that aren't in the evidence, do NOT forecast.\n\nQuestion: {task}\n\nEvidence:\n{ev}"
)


async def refine_evidence(task: str, citations: list[dict], model: str, backend: str | None = None) -> str | None:
    """PH-THINK (verify/refine): a reviewer pass over the gathered evidence → a short brief
    that grounds the final synthesis (names the sources/figures to use, flags conflicts).
    Gemini-only, best-effort; None when stub / no evidence / on error."""
    if (backend or settings.llm_backend) != "gemini" or not citations:
        return None
    lines = []
    for c in citations[:12]:
        bit = c.get("snippet") or ""
        if not bit and c.get("table"):
            bit = " · ".join(" ".join(map(str, row)) for row in (c.get("table") or [])[:3])
        lines.append(f"- [{c.get('index')}] {c.get('source') or '?'}: {str(bit)[:220]}")
    ev = "\n".join(lines)
    try:
        import asyncio
        from google import genai
        from google.genai import types

        client = genai.Client()
        resp = await asyncio.to_thread(
            client.models.generate_content, model=model,
            contents=_REFINE_PROMPT.format(task=(task or "")[:400], ev=ev[:4000]),
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=300))
        return (getattr(resp, "text", "") or "").strip() or None
    except Exception as exc:  # noqa: BLE001 — never block the answer on the review pass
        logger.warning("evidence refine failed (%s); skipping", exc)
        return None


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

    # PH-VIZ-2: attach descriptive price lines + sourced event markers (dividends/splits/
    # earnings from this turn) to the price chart, so the chart shows the cited events.
    from agentengine.artifacts import enrich_chart_markers, enrich_chart_overlays
    enrich_chart_markers(artifacts, history)
    # PH-VIZ-4: fold technical-indicator overlays (SMA/EMA/Bollinger + RSI/MACD) onto the
    # same-ticker price chart so they render on the price; else they stand alone.
    enrich_chart_overlays(artifacts)
    # PH-VIZ-3: let Gemini annotate the price chart from the question (lines/levels/zones),
    # validated to historical points only (no projection). Gemini-only; best-effort.
    from agentengine.annotations import annotate_charts
    await annotate_charts(artifacts, task, settings.model, spec.backend if spec else settings.llm_backend)

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
