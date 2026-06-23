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
from dataclasses import dataclass, field

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
    text_fragment_url,
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
    needs_data: bool = True      # does answering require our tools/data? False = conceptual →
    #                              answer richly from expertise, skip the tool loop.
    # CLARIFY (Claude-Code-style plan/ask): when the request is broad/ambiguous, offer the user
    # 2-4 concrete choices to scope the work instead of guessing. The chat surfaces these as
    # clickable chips; picking composes a refined follow-up. Only set when it genuinely helps.
    clarify: bool = False
    clarify_prompt: str | None = None
    options: list = field(default_factory=list)   # [{"label": str, "description": str|None}]
    multi: bool = False          # may several options be combined (pick-multiple) ?
    # A2A DECOMPOSITION: for a complex, multi-facet request, the orchestrator splits it into
    # 2-4 focused sub-tasks researched by parallel sub-agents, then combined. Empty = single agent.
    subtasks: list = field(default_factory=list)  # [{"title": str, "question": str}]
    # CE-4 NARRATIVE: the user wants a holistic STORY / 관전 포인트 for a specific company →
    # gather across facets and synthesize a structured, sourced narrative (+ a narrative card).
    narrative: bool = False
    # CE-10 NEWS BRIEF: the user wants a news briefing / market pulse (시황·무슨 일·뉴스 정리) →
    # gather recent news and synthesize a structured, sourced news narrative.
    news_brief: bool = False
    # CE-14 VALUE CHAIN: the user asks about a company's 밸류체인/공급망 구조 (공급사·고객·경쟁사) →
    # extract upstream/downstream/competitors from filings+news, labelled derived.
    value_chain: bool = False


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
    "PLAN — when allowed, size the work and outline it (no answer, no numbers).\n"
    "DATA ROUTING — set needs_data=true when answering requires looking up sourced financial DATA "
    "(prices, filings, financial statements, macro indicators, holdings, news, a specific company's "
    "figures). Set needs_data=false for purely CONCEPTUAL/definitional/how-to questions answerable from "
    "general knowledge (e.g. 'PER이 뭐야?', 'how does an ETF work?', 'explain DCF') — those are answered "
    "richly from expertise without a tool call.\n"
    "CLARIFY — if the request is BROAD / open-ended / ambiguous so you can't tell which specific aspect "
    "the user wants (e.g. '엔비디아 분석해줘', '삼성전자 어때?', '반도체 시장 알려줘', 'tell me about Tesla'), "
    "set clarify=true with a short clarify_prompt and 2-4 concrete ASPECT options (each "
    "{{\"label\", \"description\"}}, same language) so the user can steer — Claude-Code style. set multi=true "
    "if several aspects can be combined. Do NOT clarify a clearly specific request (e.g. 'AAPL 최근 종가', "
    "'엔비디아 매출').\n"
    "DECOMPOSE — set subtasks ONLY when the user EXPLICITLY asks for a comprehensive / all-in-one analysis "
    "(e.g. '종합적으로 분석', '전반적으로', 'comprehensive', '다 분석해줘') → 2-4 focused "
    "{{\"title\", \"question\"}} sub-tasks researched in PARALLEL. Otherwise leave subtasks empty.\n"
    "NARRATIVE — set narrative=true when the user wants a holistic STORY / 관전 포인트 / 내러티브 / 투자 "
    "포인트 / overview of a SPECIFIC company (e.g. '엔비디아 관전 포인트', '테슬라 스토리 알려줘', "
    "'tell me the story of Apple', '이 종목 정리해줘'). Then do NOT clarify — gather across the company's "
    "business, recent financials, valuation, recent filings and news, and set steps ≈ 8-12. For a single "
    "narrow fact (e.g. '엔비디아 매출') leave narrative=false.\n"
    "NEWS BRIEF — set news_brief=true when the user wants a NEWS briefing / market pulse / 시황 / 뉴스 "
    "정리 / '무슨 일이야' / what's happening (a company's news flow, or the market's). Then gather RECENT "
    "NEWS (and related context) and do NOT clarify.\n"
    "VALUE CHAIN — set value_chain=true when the user asks about a company's 밸류체인 / 공급망 구조 / "
    "공급사·고객사 / value chain / supply chain (who it buys from, sells to, competes with). Then gather "
    "its filings + news and do NOT clarify.\n\n"
    "Reply JSON ONLY:\n"
    '{{"restricted": <bool — true ONLY if the user truly wants restricted output>, '
    '"category": "forecast|advice|price_target|none", '
    '"score": <number 0..1 — confidence it is a restricted REQUEST>, '
    '"needs_data": <bool — true if sourced data lookup is required, false if conceptual>, '
    '"clarify": <bool — true only if offering choices genuinely helps>, '
    '"clarify_prompt": "<the short question to show the user, SAME LANGUAGE; empty if clarify=false>", '
    '"multi": <bool — may several options be combined>, '
    '"options": [{{"label": "<short choice>", "description": "<one line>"}}],  '
    '"subtasks": [{{"title": "<short facet name, SAME LANGUAGE>", "question": "<self-contained sub-question>"}}],  '
    '"narrative": <bool — true for a holistic company story / 관전 포인트 request>, '
    '"news_brief": <bool — true for a news briefing / 시황 / 뉴스 정리 request>, '
    '"value_chain": <bool — true for a 밸류체인 / 공급망 구조 request>, '
    '"reason": "<one short line, SAME LANGUAGE as the question>", '
    '"steps": <int tool-call budget: one fact about one company ≈ 2-3, a comparison or multi-source '
    'ask ≈ 8-12>, '
    '"plan": "<one short sentence, SAME LANGUAGE as the question, of what data you will look up and '
    'from which kind of source — NOT the answer, no numbers; empty if restricted/conceptual/clarify>"}}\n\n'
    "CONVERSATION SO FAR (for CONTEXT only — the latest question may refer back to it). A follow-up "
    "like '배당률은?', '그 회사 주가는?', 'what about its margins?' INHERITS the company/subject named "
    "earlier. RESOLVE such references and treat the question as if it named that subject explicitly; "
    "do NOT set clarify for something the context already determines. Plan/reason should name the "
    "resolved subject.\n{context}\n\n"
    "Latest question: {task}"
)

_INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "restricted": {"type": "boolean"},
        "category": {"type": "string", "enum": ["forecast", "advice", "price_target", "none"]},
        "score": {"type": "number"},
        "reason": {"type": "string"},
        "needs_data": {"type": "boolean"},
        "clarify": {"type": "boolean"},
        "clarify_prompt": {"type": "string"},
        "multi": {"type": "boolean"},
        "options": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "description": {"type": "string"}}, "required": ["label"]}},
        "subtasks": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "question": {"type": "string"}}, "required": ["title", "question"]}},
        "narrative": {"type": "boolean"},
        "news_brief": {"type": "boolean"},
        "value_chain": {"type": "boolean"},
        "steps": {"type": "integer"},
        "plan": {"type": "string"},
    },
    "required": ["restricted", "steps"],
}


def _intake_context(conversation: list | None, limit: int = 6) -> str:
    """A short transcript of the recent turns so the intake can resolve follow-up references
    (a company/topic named earlier). Excludes the latest user turn (that's the question)."""
    msgs = [m for m in (conversation or []) if (m.get("content") or "").strip()]
    if len(msgs) <= 1:
        return "(no prior turns)"
    lines = []
    for m in msgs[:-1][-limit:]:
        role = "사용자" if m.get("role") == "user" else "분석가"
        lines.append(f"{role}: {(m.get('content') or '').strip()[:300]}")
    return "\n".join(lines) or "(no prior turns)"


async def analyze_task(task: str, backend: str | None = None, conversation: list | None = None) -> TaskIntake:
    """PH-THINK: ONE first-pass LLM call that BOTH guardrails the request (judging intent in
    context — never keyword matching) AND plans it (step budget + a short plan to show the user).
    The guardrail lives here, inside the analysis layer. `conversation` (prior turns) lets the
    intake RESOLVE follow-up references (e.g. '배당률은?' inherits the earlier company) instead of
    clarifying. Stub / no-key / error → allow with the default budget and no plan."""
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
            contents=_INTAKE_PROMPT.format(task=(task or "")[:800], context=_intake_context(conversation)),
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
        # default to needs_data=True when the model omits it (gathering data is the safe default).
        needs_data = d.get("needs_data")
        needs_data = True if needs_data is None else bool(needs_data)
        # clarify only when not restricted AND there are ≥2 concrete options to offer.
        opts = []
        for o in (d.get("options") or []):
            if isinstance(o, dict) and o.get("label"):
                opts.append({"label": str(o["label"])[:80],
                             "description": (str(o.get("description") or "").strip()[:160] or None)})
        # CE-4: a holistic company-story request → narrative synthesis (and never a clarify prompt;
        # we already know the intent). Requires data + not restricted.
        narrative = bool(d.get("narrative")) and needs_data and not restricted
        news_brief = bool(d.get("news_brief")) and needs_data and not restricted
        value_chain = bool(d.get("value_chain")) and needs_data and not restricted
        clarify = (bool(d.get("clarify")) and not restricted and not narrative
                   and not news_brief and not value_chain and len(opts) >= 2)
        # decompose only for a clear, complex request (not restricted/clarify/conceptual) with ≥2 facets.
        subs = []
        for s in (d.get("subtasks") or []):
            if isinstance(s, dict) and s.get("title") and s.get("question"):
                subs.append({"title": str(s["title"])[:80], "question": str(s["question"])[:400]})
        subtasks = subs[:4] if (not restricted and not clarify and needs_data and len(subs) >= 2) else []
        return TaskIntake(
            steps=(max(floor, min(n, cap)) if n else default),
            plan=(None if (restricted or clarify) else (str(d.get("plan") or "").strip() or None)),
            restricted=restricted, score=score,
            reason=(str(d.get("reason") or "").strip() or None),
            needs_data=needs_data,
            clarify=clarify,
            clarify_prompt=(str(d.get("clarify_prompt") or "").strip() or None) if clarify else None,
            options=(opts if clarify else []),
            multi=bool(d.get("multi")),
            subtasks=subtasks,
            narrative=narrative,
            news_brief=news_brief,
            value_chain=value_chain,
        )
    except Exception as exc:  # noqa: BLE001 — degrade to allow + default budget, never block
        logger.warning("task intake failed (%s); allowing with default budget", exc)
        return TaskIntake(steps=default)


# What our platform can uniquely show — the suggester maps follow-ups to these so each click
# experiences a real differentiator (sourced data + the capability), not a generic question.
_CAPABILITY_MENU = (
    "우리 서비스가 특히 잘 보여줄 수 있는 것 (후속 질문이 이걸 자연스럽게 경험시키게):\n"
    "- 출처·증거: 모든 수치에 [n] 출처 + 공시 원문 하이라이트·뉴스 원문 구절 딥링크.\n"
    "- 차트: 가격/캔들·재무 막대·기술지표(SMA/RSI/MACD) 시각화.\n"
    "- 공시 본문 검색: 위험요소·공급망·수요 등 실제 문단 인용.\n"
    "- 밸류에이션 모델: DCF/DDM/RIM (사용자 가정 기반, 예측 아님).\n"
    "- 퀀트 스크리너: 밸류/퀄리티/모멘텀 팩터로 종목 필터·랭킹.\n"
    "- 백테스트: 포트폴리오 과거 성과·CAGR·최대낙폭, '이런 국면 이후 N일 통계'.\n"
    "- 투자거장 13F: 거장 매매·공통 보유.\n"
    "- 한국 수급(KIS 실시간): 외국인/기관 순매수·거래량/등락률/시총 순위·ETF NAV.\n"
    "- 거시: 국가 경제 패널·금리/물가·반도체 생산자물가.\n"
    "- 자산군/원자재/반도체 사이클 프록시.\n"
    "- 컨센서스 추정치·실적 캘린더(FMP, 제3자 데이터).\n"
    "- 종목 내러티브·밸류체인·뉴스 브리핑(구조화 합성).\n"
)

# Two complementary personas, run in PARALLEL (deep model), then merged → diverse, itch-scratching,
# capability-showcasing follow-ups that span beginner→expert.
_FOLLOWUP_PERSONAS = {
    "itch": (
        "당신은 통찰 있는 리서치 멘토입니다. 방금 답변을 본 사용자가 '진짜 다음에 궁금해할' 후속 질문 3개를 제안하세요. "
        "사용자의 가려운 곳을 긁어주는 질문 — 수치 뒤의 '왜?'/드라이버, 비교, 리스크, 거시 연결, 과거 통계/시나리오. "
        "초보~전문가를 아우르게 섞으세요(쉬운 설명형 1개 + 깊은 분석형). "
    ),
    "showcase": (
        "당신은 우리 데이터 플랫폼의 제품 전문가입니다. 답변 맥락에서, 우리 서비스의 차별화 기능/데이터를 "
        "자연스럽게 경험시킬 후속 질문 3개를 제안하세요(거부감 없이). 각 질문은 아래 능력 중 서로 다른 것을 자극해야 합니다.\n"
        + _CAPABILITY_MENU
    ),
}

_FOLLOWUP_PROMPT = (
    "{persona}\n"
    "규칙: 각 질문은 (1) 사용자 질문과 같은 언어, (2) 출처 기반 데이터로 답 가능(예측·목표가·매수/매도 의견 요청 "
    "금지), (3) 자기완결적(종목·지표를 명시), (4) 서로 다른 각도. 답변을 반복하지 말 것.\n"
    'JSON만: {{"followups": ["…", "…", "…"]}}\n\n'
    "사용자 질문: {task}\n{context}\n답변:\n{answer}"
)


def _merge_followups(lists: list[list[str]], limit: int = 4) -> list[str]:
    """Interleave persona candidate lists, dedup near-duplicates (normalized), cap to `limit` —
    so the final chips are DIVERSE across personas, not three variants of one idea."""
    def norm(s: str) -> str:
        return re.sub(r"[\s\W]+", "", (s or "").lower())[:60]

    out, seen = [], set()
    for i in range(max((len(c) for c in lists), default=0)):
        for cand in lists:
            if i < len(cand):
                s = cand[i].strip()
                k = norm(s)
                if s and k and k not in seen:
                    seen.add(k)
                    out.append(s)
                    if len(out) >= limit:
                        return out
    return out
_FOLLOWUP_SCHEMA = {
    "type": "object",
    "properties": {"followups": {"type": "array", "items": {"type": "string"}}},
    "required": ["followups"],
}


async def _followups_one(client, model: str, persona: str, task: str, answer: str, context: str,
                         retries: int = 3) -> list[str]:
    """One persona's follow-ups with exponential backoff — rides out transient 429/503/timeouts
    (the two personas fire in parallel, so a paid pro key can momentarily hit per-minute RPM)."""
    import asyncio
    import random

    from google.genai import types

    cfg = types.GenerateContentConfig(temperature=0.6, max_output_tokens=400,
                                      response_mime_type="application/json",
                                      response_schema=_FOLLOWUP_SCHEMA)
    contents = _FOLLOWUP_PROMPT.format(persona=persona, task=(task or "")[:400],
                                       context=context, answer=(answer or "")[:2500])
    last: Exception | None = None
    for i in range(retries):
        try:
            logger.debug("followups[%s/%s]: attempt %d/%d", model, persona, i + 1, retries)
            resp = await asyncio.to_thread(client.models.generate_content, model=model,
                                           contents=contents, config=cfg)
            raw = getattr(resp, "text", "") or "{}"
            logger.debug("followups[%s/%s]: raw response = %s", model, persona, raw[:500])
            d = json.loads(raw)
            out = [str(s).strip() for s in (d.get("followups") or []) if str(s).strip()][:3]
            logger.debug("followups[%s/%s]: parsed %d item(s): %s", model, persona, len(out), out)
            return out
        except Exception as exc:  # noqa: BLE001 — retry transient errors with backoff
            last = exc
            logger.warning("followups[%s/%s]: attempt %d/%d failed: %s: %s",
                           model, persona, i + 1, retries, type(exc).__name__, exc)
            if i < retries - 1:
                delay = 0.7 * (2 ** i) + random.uniform(0, 0.5)
                logger.debug("followups[%s/%s]: backing off %.2fs", model, persona, delay)
                await asyncio.sleep(delay)
    logger.error("followups[%s/%s]: exhausted %d retries", model, persona, retries, exc_info=last)
    raise last if last else RuntimeError("followups: no result")


def _fallback_followups(task: str, tickers: list[str] | None = None,
                        kinds: list[str] | None = None) -> list[str]:
    """Deterministic, capability-aware follow-up chips — used when the LLM suggester can't run
    (stub backend / no key) or returns nothing. GUARANTEES the chips always render: each one still
    leads into a real differentiator (공시·출처·수급·밸류에이션·거시·차트), so the UX never degrades to
    an empty footer. Not hardcoded *reasoning* (invariant #9) — just a safety net for the chip row
    when the deep suggester is unavailable; the gemini path stays primary for quality."""
    tickers = [t for t in (tickers or []) if t]
    out: list[str] = []
    if tickers:
        tk = tickers[0]
        if len(tickers) > 1:
            out.append(f"{tickers[0]}와 {tickers[1]}를 핵심 지표로 비교해줘")
        out += [
            f"{tk}의 최근 공시에서 핵심 내용을 출처와 함께 보여줘",
            f"{tk}의 매출·영업이익 추이를 차트로 보여줘",
            f"{tk}의 외국인·기관 수급 동향은 어때?",
            f"{tk}와 같은 업종 종목들과 밸류에이션을 비교해줘",
        ]
    else:
        out += [
            "관련 거시지표(금리·물가·고용)의 최신값을 출처와 함께 보여줘",
            "이 주제와 관련된 ETF·섹터 동향을 보여줘",
            "관련 기업들의 최근 공시·뉴스를 출처와 함께 정리해줘",
            "방금 답변의 근거 출처를 더 자세히 보여줘",
        ]
    seen, res = set(), []
    for s in out:
        k = re.sub(r"[\s\W]+", "", s.lower())
        if s.strip() and k not in seen:
            seen.add(k)
            res.append(s.strip())
    return res[:4]


async def suggest_followups(task: str, answer: str, model: str, backend: str | None = None,
                            context: str | None = None, tickers: list[str] | None = None,
                            kinds: list[str] | None = None) -> list[str]:
    """PH-THINK / 고도화: capability-aware follow-up chips. On gemini, runs two personas in PARALLEL
    on the deep model — one scratches the user's curiosity (skill-spanning), one showcases our
    differentiated data/features — then merges to 3-4 DIVERSE suggestions. ALWAYS returns chips when
    there's an answer: if the backend is stub, the client init fails, or every model yields nothing,
    it falls back to deterministic capability-aware chips so the row is never empty. Each click leads
    into a real capability (수급·13F·백테스트·밸류에이션·증거·거시 등)."""
    import asyncio

    if not (answer or "").strip():
        return []
    eff_backend = backend or settings.llm_backend
    fallback = _fallback_followups(task, tickers, kinds)
    if eff_backend != "gemini":
        logger.info("followups: backend=%s → deterministic fallback (%d chips)", eff_backend, len(fallback))
        return fallback
    ctx = f"맥락: {context}" if context else ""
    # model chain — DEEP model first (pro, paid key → best suggestions), each call already does
    # backoff retry; fall back to the fast model only if the deep one is truly down.
    chain: list[str] = []
    for m in (settings.synthesis_model, model, settings.model):
        if m and m not in chain:
            chain.append(m)
    try:
        from google import genai

        client = genai.Client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("followups: genai client init failed (%s: %s) → deterministic fallback",
                       type(exc).__name__, exc, exc_info=True)
        return fallback
    logger.info("followups: generating (chain=%s, personas=%s, answer_len=%d, ctx=%r)",
                chain, list(_FOLLOWUP_PERSONAS), len(answer), context)
    for m in chain:
        try:
            results = await asyncio.gather(
                *[_followups_one(client, m, p, task, answer, ctx) for p in _FOLLOWUP_PERSONAS.values()],
                return_exceptions=True)
            lists = [r for r in results if isinstance(r, list) and r]
            errs = [r for r in results if isinstance(r, Exception)]
            merged = _merge_followups(lists, limit=4)
            logger.info("followups: model %s → %d/%d personas produced items, %d error(s), merged=%d",
                        m, len(lists), len(results), len(errs), len(merged))
            if merged:
                logger.info("followups: returning %d chip(s): %s", len(merged), merged)
                return merged
            if errs:
                logger.warning("followups: model %s yielded nothing usable; first error: %s: %s; trying next",
                               m, type(errs[0]).__name__, errs[0])
        except Exception as exc:  # noqa: BLE001 — never block on suggestions
            logger.warning("followups: model %s errored (%s: %s); trying next",
                           m, type(exc).__name__, exc, exc_info=True)
    logger.warning("followups: all models in chain %s produced nothing → deterministic fallback (%d chips)",
                   chain, len(fallback))
    return fallback


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


# CE-4: appended to the system prompt for a holistic company-story request, so the synthesis
# produces a structured, sourced 종목 내러티브 (parsed into a narrative artifact afterwards).
_NARRATIVE_GUIDE = (
    "\n\n[종목 내러티브 형식] 이 답변은 한 종목의 '관전 포인트' 내러티브입니다. 아래 다섯 섹션을 정확히 이 "
    "마크다운 제목으로, 순서대로 작성하세요 (각 섹션 2-4문장):\n"
    "## 사업 개요\n## 최근 실적·재무\n## 밸류에이션\n## 최근 이슈 (뉴스·공시)\n## 관전 포인트\n"
    "모든 구체적 수치·사실은 수집한 출처에서 가져와 문장 끝에 [n]으로 인용하세요. '관전 포인트'는 앞으로 "
    "지켜볼 모니터링 항목을 서술형으로만 적고, 가격 예측·목표가·매수/매도 의견은 절대 넣지 마세요."
)

# section headings the guide asks for (used to title the parsed narrative artifact)
_NARRATIVE_HEADINGS = ("사업 개요", "최근 실적·재무", "밸류에이션", "최근 이슈", "관전 포인트")

# CE-14: appended for a value-chain request → a structured, sourced (derived) supply-chain map.
_VALUE_CHAIN_GUIDE = (
    "\n\n[밸류체인 형식] 이 답변은 한 기업의 밸류체인/공급망 구조 정리입니다. 아래 제목으로, 순서대로 "
    "작성하세요:\n## 핵심 사업\n## 주요 공급사 (상류)\n## 주요 고객 (하류)\n## 경쟁사\n## 밸류체인 내 위치\n"
    "공시(사업의 내용·위험요소)와 뉴스에서 언급된 관계만 근거로 삼고 각 항목 끝에 [n]으로 인용하세요. "
    "추측으로 관계를 만들지 말고, 근거가 없으면 '공시상 명시 없음'이라고 적으세요. 이 분석은 '공시·뉴스 "
    "기반 LLM 추출(derived) — 확정된 거래관계가 아님'임을 마지막에 한 줄로 밝히세요. 가격 예측·매수의견 금지."
)

# CE-10: appended for a news-briefing request → a structured, sourced news narrative.
_NEWS_BRIEF_GUIDE = (
    "\n\n[뉴스 브리핑 형식] 이 답변은 최신 뉴스 브리핑입니다. 아래 제목으로, 순서대로 작성하세요:\n"
    "## 핵심 흐름\n## 주요 헤드라인\n## 맥락·배경\n## 지켜볼 점\n"
    "수집한 뉴스에서 사실만 가져와 각 항목 끝에 [n]으로 발행사·날짜와 함께 인용하세요. '주요 헤드라인'은 "
    "최근 3-6개를 발행사와 함께 bullet로. '지켜볼 점'은 앞으로 모니터링할 사안을 서술형으로만 적고, 가격 "
    "예측·목표가·매수/매도 의견은 절대 넣지 마세요."
)


def build_narrative_artifact(text: str, ticker: str | None = None) -> Artifact | None:
    """CE-4: split the synthesized markdown answer into the 종목 내러티브 sections (## heading →
    body) → a pinnable narrative card. Deterministic (presentation, not reasoning); returns None
    when the answer isn't structured into ≥2 sections (e.g. the stub backend)."""
    from agentengine.models import NarrativeSection

    sections: list[NarrativeSection] = []
    heading, body = None, []
    for line in (text or "").splitlines():
        m = re.match(r"^\s{0,3}#{1,3}\s+(.*\S)\s*$", line)
        if m:
            if heading and body and "".join(body).strip():
                sections.append(NarrativeSection(heading=heading, body="\n".join(body).strip()))
            heading, body = m.group(1).strip().lstrip("#").strip(), []
        elif heading is not None:
            body.append(line)
    if heading and body and "".join(body).strip():
        sections.append(NarrativeSection(heading=heading, body="\n".join(body).strip()))
    if len(sections) < 2:
        return None
    title = f"{ticker} 종목 내러티브" if ticker else "종목 내러티브 (관전 포인트)"
    return Artifact(kind="narrative", title=title, sections=sections, ticker=ticker, tool="narrative")


def filter_tools(tools: dict, allowed: list[str] | None) -> dict:
    """Restrict ``tools`` to ``allowed``. Entries match, in order of precedence, a full tool
    name (``sec_edgar__guru_trades`` — the new per-tool selection), a user-facing category id
    (``gurus`` → every tool in that category), or a connector id (``sec_edgar`` → all of its
    tools — legacy/back-compat). Empty/None means no restriction."""
    if not allowed:
        return tools
    sel = set(allowed)
    return {
        name: t for name, t in tools.items()
        if name in sel or t.get("category") in sel or name.split("__")[0] in sel
    }


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

    # Conceptual question → answer richly from expertise, skip the tool loop (guardrail still
    # applies; the responder won't assert specific unsourced figures).
    if not intake.needs_data:
        planner = get_planner(spec.backend if spec else None)
        dec = await planner.plan(task, {}, [], system, force_final=True, sources=None)
        return RunResult(answer=(dec.final or fallback_answer([])), refused=False, usage={"steps": 0})

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
