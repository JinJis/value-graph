"""A2A orchestration: run focused sub-agents in parallel, then combine.

The orchestrator DECISION (whether to decompose, and into which sub-tasks) is the LLM's — it
rides on the first-pass intake (``agent.analyze_task`` → ``TaskIntake.subtasks``). This module
only EXECUTES one sub-agent: a lean, HEADLESS gather loop over the shared tools (it collects
sourced evidence + artifacts for its focused sub-question and a short wrap-up note, but does
NOT write the final answer — the combiner synthesizes once over all sub-results so the answer
keeps one voice). Each sub-agent itself fans out independent calls in parallel (plan_batch),
so the whole turn is parallel-of-parallel. "Claude Code for finance": decompose → dispatch
(parallel) → combine.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from agentengine.agent import call_sig, number_sources
from agentengine.artifacts import _artifacts
from agentengine.citations import _citations, dedup_citations
from agentengine.client import PlatformClient
from agentengine.planner import get_planner, resolve_ticker

logger = logging.getLogger(__name__)

# A sub-agent is focused → a small budget keeps the fan-out cheap and fast.
SUBAGENT_BUDGET = 4


@dataclass
class SubResult:
    title: str
    question: str
    note: str | None = None          # the sub-agent's short wrap-up (context for the combiner)
    citations: list = field(default_factory=list)   # list[Citation]
    artifacts: list = field(default_factory=list)    # list[Artifact]
    history: list = field(default_factory=list)       # [(decision, result)] → chart markers
    steps: int = 0


async def _plan_batch(planner, task, tools, history, citations, force_final):
    kw = dict(force_final=force_final, sources=number_sources(dedup_citations(citations)))
    if hasattr(planner, "plan_batch"):
        return await planner.plan_batch(task, tools, history, None, **kw)
    return [await planner.plan(task, tools, history, None, **kw)]


async def run_subagent(title: str, question: str, api_key: str | None, tools: dict,
                       backend: str | None, budget: int = SUBAGENT_BUDGET) -> SubResult:
    """Headless gather loop for ONE focused sub-question over the shared tools. Returns the
    sourced evidence it found (citations + artifacts + history) plus a short note — never the
    final answer (the combiner does that). Best-effort: failures degrade to whatever it got."""
    planner = get_planner(backend)
    client = PlatformClient(api_key)
    history: list = []
    citations: list = []
    artifacts: list = []
    seen_art: set = set()
    note = None
    last_sig = None
    steps = 0
    try:
        for step in range(budget):
            is_last = step == budget - 1
            decisions = await _plan_batch(planner, question, tools, history, citations, is_last)
            if is_last or (decisions and decisions[0].final is not None):
                note = (decisions[0].final if decisions else None) or None
                break
            batch = [d for d in decisions if d.tool]
            for d in batch:  # company name/alias → ticker
                if d.args and "ticker" in d.args:
                    r = resolve_ticker(d.args["ticker"])
                    if r:
                        d.args["ticker"] = r
            sig = "|".join(sorted(s for s in (call_sig(d) for d in batch) if s))
            if sig and sig == last_sig:  # stuck → stop gathering
                break
            last_sig = sig
            valid = [(d, tools[d.tool]) for d in batch if d.tool in tools]
            if not valid:
                break
            results = await asyncio.gather(
                *[client.call_tool(t, d.args or {}) for (d, t) in valid], return_exceptions=True)
            steps += len(valid)
            for (d, tool), result in zip(valid, results):
                if isinstance(result, Exception):
                    continue
                citations.extend(_citations(tool, result))
                for a in _artifacts(tool, result):
                    if a.title not in seen_art:
                        seen_art.add(a.title)
                        a.args = d.args or {}
                        artifacts.append(a)
                history.append((d, result))
    except Exception:  # noqa: BLE001 — a sub-agent never sinks the whole turn
        logger.exception("sub-agent failed: %s", title)
    return SubResult(title=title, question=question, note=(note.strip() if note else None),
                     citations=citations, artifacts=artifacts, history=history, steps=steps)
