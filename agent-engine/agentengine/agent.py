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
from dataclasses import dataclass

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


# --- PH-15 / PH-THINK: LLM-assessed step budget + guardrail, folded into one intake ----
# A light model both judges the request (guardrail) and rates how many tool hops it needs
# (not hardcoded keyword rules): simple single-fact asks finish fast; multi-source asks
# ("공급망·리스크 공시 요약") get headroom. The numbered budget is then strictly honored
# (the loop reserves its last step for synthesis, so it never leaks "Reached the step limit").
@dataclass
class TaskIntake:
    """The first-pass LLM analysis of a user turn: the GUARDRAIL decision (judged from
    intent, in context — no keyword rules, invariant #9) folded together with PLANNING
    (step budget + a short plan). One Gemini call produces all of it."""

    steps: int
    plan: str | None = None
    restricted: bool = False     # the user asked for forecast/advice/target as output → refuse
    score: float = 0.0           # confidence (0..1) it's a restricted REQUEST
    reason: str | None = None    # one-line why (shown for telemetry)


_INTAKE_PROMPT = (
    "You are the intake analyst for a financial RESEARCH service that provides ONLY sourced, "
    "historical/descriptive facts (public filings, financials, prices, macro data, news). It must "
    "REFUSE to *produce* forward-looking or advisory content. Read the user's question and reply "
    "with JSON.\n\n"
    "GUARDRAIL — decide whether the user is REQUESTING, as the desired output, any of:\n"
    "- a price/market PREDICTION or FORECAST (future direction, 'will it go up', earnings forecast)\n"
    "- BUY/SELL/HOLD advice, an investment recommendation, or entry/exit timing\n"
    "- a PRICE TARGET (목표가 / 목표주가)\n"
    "Judge INTENT, not vocabulary. A request is NOT restricted merely because it MENTIONS these "
    "words. If the user EXCLUDES or NEGATES them it is ALLOWED — they want facts. ALLOWED examples: "
    "'목표가는 제시하지 말고 가격 흐름만', '전망·매수의견은 넣지 말고 사실 위주로', 'do NOT give a "
    "forecast, just what happened'. Descriptive past/current facts, news summaries, filings, "
    "financials, and macro data are ALWAYS allowed.\n\n"
    "PLAN — when allowed, size the work and outline it (no answer, no numbers).\n\n"
    "Reply JSON ONLY:\n"
    '{{"restricted": <bool — true ONLY if the user truly wants restricted output>, '
    '"category": "forecast|advice|price_target|none", '
    '"score": <number 0..1 — confidence it is a restricted REQUEST>, '
    '"reason": "<one short line, SAME LANGUAGE as the question>", '
    '"steps": <int tool-call budget: one fact about one company ≈ 2-3, a comparison or multi-source '
    'ask ≈ 8-12>, '
    '"plan": "<one short sentence, SAME LANGUAGE as the question, of what data you will look up and '
    'from which kind of source — NOT the answer, no numbers; empty string if restricted>"}}\n\n'
    "Question: {task}"
)

_INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "restricted": {"type": "boolean"},
        "category": {"type": "string", "enum": ["forecast", "advice", "price_target", "none"]},
        "score": {"type": "number"},
        "reason": {"type": "string"},
        "steps": {"type": "integer"},
        "plan": {"type": "string"},
    },
    "required": ["restricted", "steps"],
}


async def analyze_task(task: str, backend: str | None = None) -> TaskIntake:
    """PH-THINK: ONE first-pass LLM call that BOTH guardrails the request (judging intent in
    context — never keyword matching) AND plans it (step budget + a short plan to show the user).
    The guardrail lives here, inside the analysis layer. Stub / no-key / error → allow with the
    default budget and no plan (the LLM is the only judge; there is no keyword fallback)."""
    cap, default, floor = settings.max_steps_cap, settings.max_steps, 3
    if (backend or settings.llm_backend) != "gemini":
        return TaskIntake(steps=default)
    try:
        import asyncio
        from google import genai
        from google.genai import types

        client = genai.Client()
        resp = await asyncio.to_thread(
            client.models.generate_content, model=settings.budget_model,
            contents=_INTAKE_PROMPT.format(task=(task or "")[:800]),
            config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                               response_schema=_INTAKE_SCHEMA, max_output_tokens=400))
        d = json.loads(getattr(resp, "text", "") or "{}")
        try:
            n = int(d.get("steps"))
        except (TypeError, ValueError):
            n = None
        try:
            score = float(d.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        # refuse only when the model both flags it AND is confident enough (a low-confidence
        # guess never blocks a legitimate question).
        restricted = bool(d.get("restricted")) and score >= settings.guardrail_threshold
        return TaskIntake(
            steps=(max(floor, min(n, cap)) if n else default),
            plan=(None if restricted else (str(d.get("plan") or "").strip() or None)),
            restricted=restricted, score=score,
            reason=(str(d.get("reason") or "").strip() or None),
        )
    except Exception as exc:  # noqa: BLE001 — degrade to allow + default budget, never block
        logger.warning("task intake failed (%s); allowing with default budget", exc)
        return TaskIntake(steps=default)


_REFINE_PROMPT = (
    "You are a meticulous research reviewer. Given the user's question and the evidence the "
    "agent gathered (each item: [index] source + snippet/figures), return JSON with:\n"
    "- \"brief\": a SHORT synthesis brief (2-4 lines, SAME LANGUAGE as the question) that names "
    "which sources actually answer the question + the key figures to use, flags conflicts/gaps, "
    "and gives a one-line outline for the final answer. Do NOT write the answer, add numbers not "
    "in the evidence, or forecast.\n"
    "- \"sources\": for EACH evidence item, its [index] and a confidence of how well it supports "
    "answering THIS question — \"high\" (direct, specific, on-topic), \"medium\" (partial/indirect), "
    "\"low\" (tangential/weak) — plus a one-line \"why\" in the question's language. This is a "
    "descriptive judgment of evidentiary support, NOT a market prediction.\n\n"
    "Question: {task}\n\nEvidence:\n{ev}"
)

_REFINE_SCHEMA = {
    "type": "object",
    "properties": {
        "brief": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "object", "properties": {
            "index": {"type": "integer"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "why": {"type": "string"},
        }, "required": ["index", "confidence"]}},
    },
    "required": ["brief"],
}


async def refine_evidence(task: str, citations: list[dict], model: str,
                          backend: str | None = None) -> tuple[str | None, dict[int, dict]]:
    """PH-THINK (verify/refine): ONE reviewer pass over the gathered evidence that both
    (a) writes a short synthesis brief grounding the final answer, and (b) scores each
    source's confidence (how well it supports the question). Returns (brief, {index: {
    confidence, why}}). Gemini-only, best-effort; ('', {}) when stub / no evidence / error."""
    if (backend or settings.llm_backend) != "gemini" or not citations:
        return None, {}
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
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=600,
                                               response_mime_type="application/json",
                                               response_schema=_REFINE_SCHEMA))
        d = json.loads(getattr(resp, "text", "") or "{}")
        brief = (str(d.get("brief") or "")).strip() or None
        scores: dict[int, dict] = {}
        for s in (d.get("sources") or []):
            try:
                idx = int(s.get("index"))
            except (TypeError, ValueError):
                continue
            conf = str(s.get("confidence") or "").lower()
            if conf in ("high", "medium", "low"):
                scores[idx] = {"confidence": conf, "why": (str(s.get("why") or "").strip() or None)}
        return brief, scores
    except Exception as exc:  # noqa: BLE001 — never block the answer on the review pass
        logger.warning("evidence refine failed (%s); skipping", exc)
        return None, {}


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
    # PH-THINK: one intake call both guardrails (LLM judges intent — no keyword rules) and
    # sizes the budget. Refuse here at the agent boundary when the request is restricted.
    intake = await analyze_task(task, spec.backend if spec else None)
    if intake.restricted:
        return RunResult(answer=guardrails.REFUSAL, refused=True, usage={"steps": 0})

    max_steps = spec.max_steps if (spec and spec.max_steps) else intake.steps
    system = spec.system if spec else None
    if intake.plan:
        system = ((system or "") + f"\n\n[연구 계획] {intake.plan}").strip()
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
