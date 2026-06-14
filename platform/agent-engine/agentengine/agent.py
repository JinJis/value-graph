"""The agent loop: guardrail → plan → call tool (via gateway) → observe → finalize.

Tools = the tenant's activated connectors + RAG (resolved from the gateway
catalog). Every tool result's provenance is collected into citations, so agent
answers are sourced.
"""

from __future__ import annotations

import logging
from agentengine import guardrails
from agentengine.client import PlatformClient
from agentengine.config import settings
from agentengine.models import AgentSpec, Citation, RunResult, Step
from agentengine.planner import get_planner

logger = logging.getLogger(__name__)


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
        cites.append(Citation(tool=tool["name"], source=src or tool.get("source"), url=url))
    return cites or None


def _citations(tool: dict, result: dict) -> list[Citation]:
    data = result.get("data")
    if "search" in tool["name"] or tool.get("connector") == "rag":
        rag = _rag_citations(tool, data)
        if rag is not None:
            return rag
    src = tool.get("source")
    urls = list(dict.fromkeys(_find_urls(data)))[:5]
    if not urls:
        return [Citation(tool=tool["name"], source=src)]
    return [Citation(tool=tool["name"], source=src, url=u) for u in urls]


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
        out.append(c)
    return out


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

    max_steps = (spec.max_steps if spec and spec.max_steps else settings.max_steps)
    system = spec.system if spec else None
    client = PlatformClient(api_key)
    tools = await client.fetch_tools()
    if spec and spec.allowed_tools:
        tools = filter_tools(tools, spec.allowed_tools)

    history: list = []
    steps: list[Step] = []
    citations: list[Citation] = []
    answer = ""
    try:
        planner = get_planner(spec.backend if spec else None)
        for _ in range(max_steps):
            decision = await planner.plan(task, tools, history, system)
            if decision.final is not None:
                answer = decision.final
                break
            
            # Auto-resolve ticker from company name/alias
            if decision.tool and decision.args and "ticker" in decision.args:
                from agentengine.planner import resolve_ticker
                resolved = resolve_ticker(decision.args["ticker"])
                if resolved:
                    decision.args["ticker"] = resolved

            tool = tools.get(decision.tool)
            if tool is None:
                answer = f"Planner selected an unavailable tool '{decision.tool}'."
                break
            result = await client.call_tool(tool, decision.args or {})
            steps.append(Step(tool=decision.tool, args=decision.args or {}, status=result["status"]))
            citations.extend(_citations(tool, result))
            history.append((decision, result))
        if not answer:
            final = await planner.plan(task, tools, history, system, force_final=True)
            answer = final.final or "Reached the step limit without a final answer."
    except Exception as e:
        logger.exception("Error in run_agent loop")
        # Honest degrade on a planner/LLM error rather than a 500.
        answer = answer or f"답변 생성 중 문제가 발생했어요. 잠시 후 다시 시도해 주세요. ({type(e).__name__}: {str(e)})"

    return RunResult(answer=answer, steps=steps, citations=dedup_citations(citations), usage={"steps": len(steps)})
