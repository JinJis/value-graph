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

from typing import AsyncIterator

from agentengine import guardrails
from agentengine.agent import _citations
from agentengine.client import PlatformClient
from agentengine.config import settings
from agentengine.models import AgentSpec
from agentengine.planner import get_planner


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

    refusal = guardrails.check(task)
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
        tools = {k: v for k, v in tools.items() if k in spec.allowed_tools}

    planner = get_planner()
    max_steps = (spec.max_steps if spec and spec.max_steps else settings.max_steps)
    history: list = []
    citations: list[dict] = []
    answered = False
    for _ in range(max_steps):
        decision = await planner.plan(task, tools, history)
        if decision.final is not None:
            for ch in _chunks(decision.final):
                yield {"type": "token", "text": ch}
            answered = True
            break
        tool = tools.get(decision.tool)
        if tool is None:
            yield {"type": "token", "text": f"(planner chose an unavailable tool '{decision.tool}')"}
            answered = True
            break
        yield {"type": "tool", "name": decision.tool, "args": decision.args or {}}
        result = await client.call_tool(tool, decision.args or {})
        yield {"type": "tool_result", "status": result["status"], "connector": result.get("connector")}
        for c in _citations(tool, result):
            cit = c.model_dump()
            citations.append(cit)
            yield {"type": "citation", **cit}
        history.append((decision, result))
    if not answered:
        final = await planner.plan(task, tools, history)
        for ch in _chunks(final.final or "Reached the step limit."):
            yield {"type": "token", "text": ch}

    yield {"type": "done", "citations": citations, "refused": False}
