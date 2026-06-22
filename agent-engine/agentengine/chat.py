"""Streaming, multi-turn chat over the agent loop.

``stream_chat`` yields typed events for an SSE response:
  {"type":"thinking","phase":..,"text":..}  live reasoning (analyze→fetch→found→synthesize)
  {"type":"token","text":...}        incremental answer text
  {"type":"tool","name":..,"args":..} a tool the agent is calling
  {"type":"tool_result","status":..,"connector":..}
  {"type":"citation","tool":..,"source":..,"url":..}
  {"type":"done","citations":[...],"artifacts":[...],"refused":bool}

Planner-agnostic: the stub and gemini planners both flow through here (the final
answer is streamed in chunks). Tool calls go through the gateway with the tenant
key, so entitlement + metering apply to chat too.
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from agentengine import guardrails
from agentengine.agent import (
    _artifacts, _citations, analyze_task, anchor_markers, call_sig, fallback_answer,
    filter_tools, has_anchors, number_sources, refine_evidence,
)
from agentengine.client import PlatformClient
from agentengine.config import settings
from agentengine.evidence import evidence_url_for_answer
from agentengine.models import AgentSpec
from agentengine.planner import get_planner
from agentengine.provenance import _canonical_provenance, _market_hint

logger = logging.getLogger(__name__)


def _last_user(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return messages[-1].get("content", "") if messages else ""


def _chunks(text: str, size: int = 6) -> list[str]:
    words = (text or "").split()
    if not words:
        return [text or ""]
    return [" ".join(words[i : i + size]) + (" " if i + size < len(words) else "") for i in range(0, len(words), size)]


async def stream_chat(messages: list[dict], api_key: str | None, spec: AgentSpec | None = None) -> AsyncIterator[dict]:
    task = _last_user(messages)
    system = spec.system if spec else None
    bk = spec.backend if spec else None

    # PH-THINK: the first-pass intake is ONE LLM call that both GUARDRAILS the request
    # (judging intent in context — no keyword rules, invariant #9) AND plans it (budget +
    # a short plan shown as live thinking). If it's a forecast/advice/target request, refuse
    # here at the boundary — before we ever touch the data plane.
    yield {"type": "thinking", "phase": "analyze", "text": "요청을 분석하고 있어요…"}
    intake = await analyze_task(task, bk)
    if intake.restricted:
        for ch in _chunks(guardrails.REFUSAL):
            yield {"type": "token", "text": ch}
        yield {"type": "done", "citations": [], "artifacts": [], "refused": True}
        return
    max_steps = spec.max_steps if (spec and spec.max_steps) else intake.steps
    plan = intake.plan
    if plan:
        yield {"type": "thinking", "phase": "plan", "text": f"계획: {plan}"}
        # the plan guides tool selection + synthesis (quality), without hardcoding logic.
        system = ((system or "") + f"\n\n[연구 계획] {plan}").strip()

    client = PlatformClient(api_key)
    try:
        tools = await client.fetch_tools()
    except Exception:
        yield {"type": "token", "text": "The data platform is unavailable right now."}
        yield {"type": "done", "citations": [], "artifacts": [], "refused": False}
        return
    if spec and spec.allowed_tools:
        tools = filter_tools(tools, spec.allowed_tools)
    history: list = []
    citations: list[dict] = []
    cite_ctx: list[tuple[dict, dict, object]] = []  # (citation, tool, data) → re-anchor evidence post-answer
    artifacts: list[dict] = []
    art_objs: list = []          # the Artifact objects → enrich with chart markers post-loop
    seen_artifacts: set = set()
    seen_cites: set = set()
    answered = False
    refined = False              # run the verify/refine pass once, just before synthesis
    final_text = ""
    last_sig = None

    async def _maybe_refine():
        # PH-THINK verify pass: ONE review that grounds the synthesis AND scores each
        # source's confidence (shown on the source card) — the trust brand, not fine print.
        nonlocal refined, system
        if refined or not citations:
            return None
        refined = True
        note, scores = await refine_evidence(task, citations, settings.model, bk)
        if note:
            system = ((system or "") + f"\n\n[검증 메모] {note}").strip()
        for c in citations:
            sc = scores.get(c.get("index"))
            if sc:
                c["confidence"] = sc["confidence"]
                c["confidence_why"] = sc.get("why")
        return note

    async def _finalize(force: bool):
        # one synthesis call; never leak an empty/limit message to the user.
        dec = await planner.plan(task, tools, history, system, conversation=messages,
                                 force_final=force, sources=number_sources(citations))
        return dec.final or fallback_answer(citations)

    try:
        planner = get_planner(spec.backend if spec else None)
        for step in range(max_steps):
            is_last = step == max_steps - 1  # reserve the last step for guaranteed synthesis
            if is_last and not refined and citations:  # verify/refine just before the forced synthesis
                if (bk or settings.llm_backend) == "gemini":
                    yield {"type": "thinking", "phase": "verify", "text": "근거를 교차검증하는 중…"}
                await _maybe_refine()
            decision = await planner.plan(task, tools, history, system, conversation=messages,
                                          force_final=is_last, sources=number_sources(citations))
            if is_last or decision.final is not None:
                yield {"type": "thinking", "phase": "synthesize", "text": "근거를 정리해 답변을 작성하는 중…"}
                final_text = decision.final or fallback_answer(citations)
                for ch in _chunks(final_text):
                    yield {"type": "token", "text": ch}
                answered = True
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
                if not refined and citations and (bk or settings.llm_backend) == "gemini":
                    yield {"type": "thinking", "phase": "verify", "text": "근거를 교차검증하는 중…"}
                await _maybe_refine()
                yield {"type": "thinking", "phase": "synthesize", "text": "근거를 정리해 답변을 작성하는 중…"}
                final_text = await _finalize(force=True)
                for ch in _chunks(final_text):
                    yield {"type": "token", "text": ch}
                answered = True
                break
            last_sig = sig

            tool = tools.get(decision.tool)
            if tool is None:
                yield {"type": "token", "text": f"(planner chose an unavailable tool '{decision.tool}')"}
                answered = True
                break
            label = tool.get("friendly") or tool.get("connector_name") or decision.tool
            yield {"type": "tool", "name": decision.tool, "label": tool.get("friendly") or tool.get("connector_name"), "args": decision.args or {}}
            # PH-THINK: live progress — which source we're querying, then what we found.
            yield {"type": "thinking", "phase": "fetch", "text": f"{label} 살펴보는 중…", "tool": decision.tool}
            result = await client.call_tool(tool, decision.args or {})
            yield {"type": "tool_result", "status": result["status"], "connector": result.get("connector")}
            before = len(citations)
            for c in _citations(tool, result):
                cit = c.model_dump()
                key = (cit.get("source"), cit.get("url"))
                if key in seen_cites:  # de-dup repeated sources across tool calls
                    continue
                seen_cites.add(key)
                cit["index"] = len(citations) + 1  # 1-based [n] anchor
                citations.append(cit)
                cite_ctx.append((cit, tool, result.get("data")))
                yield {"type": "citation", **cit}
            for a in _artifacts(tool, result):  # U3: connector-backed figure cards
                if a.title in seen_artifacts:
                    continue
                seen_artifacts.add(a.title)
                a.args = decision.args or {}     # so a pinned card can re-fetch (U3-03)
                art_objs.append(a)
                art = a.model_dump()
                artifacts.append(art)
                yield {"type": "artifact", "artifact": art}
            added = len(citations) - before
            ok = result.get("status") == 200 and added > 0
            yield {"type": "thinking", "phase": "found",
                   "text": (f"✓ {label} · 근거 {added}건 확보" if ok else f"· {label}에서 새 근거를 찾지 못함")}
            history.append((decision, result))
        if not answered:
            yield {"type": "thinking", "phase": "synthesize", "text": "근거를 정리해 답변을 작성하는 중…"}
            final_text = fallback_answer(citations)
            for ch in _chunks(final_text):
                yield {"type": "token", "text": ch}
    except Exception as e:
        logger.exception("Error in stream_chat loop")
        # A planner/LLM error (e.g. bad model id, missing key, upstream outage)
        # degrades to an honest message instead of breaking the stream.
        yield {"type": "token", "text": f"답변 생성 중 문제가 발생했어요. 잠시 후 다시 시도해 주세요. ({type(e).__name__}: {str(e)})"}

    # PH-VIZ-2: attach sourced event markers (dividends/splits/earnings this turn) + price
    # lines to the price chart, then re-emit the enriched artifacts in `done` (the streamed
    # `artifact` events went out before the later tool results existed).
    from agentengine.artifacts import enrich_chart_markers, enrich_chart_overlays
    enrich_chart_markers(art_objs, history)
    # PH-VIZ-4: fold any technical-indicator artifact (SMA/EMA/Bollinger + RSI/MACD) onto
    # the same-ticker price chart so the overlays render on the price; else it stands alone.
    enrich_chart_overlays(art_objs)
    # PH-VIZ-3: Gemini annotates the price chart from the question (lines/levels/zones),
    # validated to historical points only (no projection). Gemini-only; best-effort.
    from agentengine.annotations import annotate_charts
    await annotate_charts(art_objs, task, settings.model, spec.backend if spec else settings.llm_backend)
    if art_objs:
        artifacts = [o.model_dump() for o in art_objs]

    # PH-PROV3d: re-anchor each filing citation's evidence image on the figure the ANSWER
    # actually cites (net income / R&D / assets …), not always the first headline (revenue).
    for cit, tool, data in cite_ctx:
        if not isinstance(data, dict):
            continue
        market = _market_hint(tool, data)
        _, accn, cik = _canonical_provenance(data)
        new_url = evidence_url_for_answer(data, cit.get("page") or accn, cik, market, final_text)
        if new_url:
            cit["evidence_image_url"] = new_url

    # Evidence vs consulted: a citation is evidence iff the answer cited its [n] or it
    # backs a rendered artifact. The Live Context shows only evidence; every consulted
    # source still appears in the answer's 도구·출처 list. When the model wrote no inline
    # [n], evidence falls back to the citations that actually returned data.
    cited = {int(m) for m in re.findall(r"\[(\d+)\]", final_text or "")}
    art_tools = {a.get("tool") for a in artifacts if a.get("tool")}
    for c in citations:
        c["used"] = (c.get("index") in cited) or (c.get("tool") in art_tools)
    if citations and not any(c.get("used") for c in citations):
        data_bearing = [c for c in citations if c.get("url") or c.get("snippet") or c.get("table")]
        for c in (data_bearing or citations):
            c["used"] = True

    # PH-4c: if the prose carries no inline [n] markers, stream a trailing anchor group
    # for the EVIDENCE only (don't claim every consulted source produced the figures).
    if citations and final_text and not has_anchors(final_text):
        used_idx = [c.get("index") for c in citations if c.get("used")] or [c.get("index") for c in citations]
        yield {"type": "token", "text": " " + anchor_markers(used_idx)}
    used = [c.get("index") for c in citations if c.get("used")]
    yield {"type": "done", "citations": citations, "artifacts": artifacts, "refused": False, "used": used}
