"""Streaming, multi-turn chat over the agent loop.

``stream_chat`` yields typed events for an SSE response:
  {"type":"token","text":...}        incremental answer text
  {"type":"tool","name":..,"args":..} a tool the agent is calling
  {"type":"tool_result","status":..,"connector":..}
  {"type":"citation","tool":..,"source":..,"url":..}
  {"type":"done","citations":[...],"refused":bool}

Planner-agnostic: the stub and gemini planners both flow through here (the final
answer is streamed in chunks). Tool calls go through the gateway with the tenant
key, so entitlement + metering apply to chat too.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from agentengine import guardrails
from agentengine.agent import _citations, anchor_markers, filter_tools, has_anchors
from agentengine.client import PlatformClient
from agentengine.config import settings
from agentengine.models import AgentSpec
from agentengine.planner import get_planner

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

    guardrailer = guardrails.get_guardrailer(spec.backend if spec else None)
    refusal = await guardrailer.check(task)
    if refusal:
        for ch in _chunks(refusal):
            yield {"type": "token", "text": ch}
        yield {"type": "done", "citations": [], "refused": True}
        return

    client = PlatformClient(api_key)
    try:
        tools = await client.fetch_tools()
    except Exception:
        yield {"type": "token", "text": "The data platform is unavailable right now."}
        yield {"type": "done", "citations": [], "refused": False}
        return
    if spec and spec.allowed_tools:
        tools = filter_tools(tools, spec.allowed_tools)

    system = spec.system if spec else None
    max_steps = (spec.max_steps if spec and spec.max_steps else settings.max_steps)
    history: list = []
    citations: list[dict] = []
    seen_cites: set = set()
    answered = False
    final_text = ""
    try:
        planner = get_planner(spec.backend if spec else None)
        for _ in range(max_steps):
            decision = await planner.plan(task, tools, history, system, conversation=messages)
            if decision.final is not None:
                final_text = decision.final
                for ch in _chunks(decision.final):
                    yield {"type": "token", "text": ch}
                answered = True
                break

            # Auto-resolve ticker from company name/alias
            if decision.tool and decision.args and "ticker" in decision.args:
                from agentengine.planner import resolve_ticker
                resolved = resolve_ticker(decision.args["ticker"])
                if resolved:
                    decision.args["ticker"] = resolved

            tool = tools.get(decision.tool)
            if tool is None:
                yield {"type": "token", "text": f"(planner chose an unavailable tool '{decision.tool}')"}
                answered = True
                break
            yield {"type": "tool", "name": decision.tool, "label": tool.get("friendly") or tool.get("connector_name"), "args": decision.args or {}}
            result = await client.call_tool(tool, decision.args or {})
            yield {"type": "tool_result", "status": result["status"], "connector": result.get("connector")}
            for c in _citations(tool, result):
                cit = c.model_dump()
                key = (cit.get("source"), cit.get("url"))
                if key in seen_cites:  # de-dup repeated sources across tool calls
                    continue
                seen_cites.add(key)
                cit["index"] = len(citations) + 1  # 1-based [n] anchor
                citations.append(cit)
                yield {"type": "citation", **cit}
            history.append((decision, result))
        if not answered:
            final = await planner.plan(task, tools, history, system, conversation=messages, force_final=True)
            final_text = final.final or "Reached the step limit."
            for ch in _chunks(final_text):
                yield {"type": "token", "text": ch}
    except Exception as e:
        logger.exception("Error in stream_chat loop")
        # A planner/LLM error (e.g. bad model id, missing key, upstream outage)
        # degrades to an honest message instead of breaking the stream.
        yield {"type": "token", "text": f"답변 생성 중 문제가 발생했어요. 잠시 후 다시 시도해 주세요. ({type(e).__name__}: {str(e)})"}

    # PH-4c: if the prose carries no inline [n] markers, stream a trailing anchor
    # group so the answer ties to the citation chips (deterministic floor).
    if citations and final_text and not has_anchors(final_text):
        yield {"type": "token", "text": " " + anchor_markers([c.get("index") for c in citations])}
    yield {"type": "done", "citations": citations, "refused": False}
