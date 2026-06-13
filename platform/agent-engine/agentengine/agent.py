"""The agent loop: guardrail → plan → call tool (via gateway) → observe → finalize.

Tools = the tenant's activated connectors + RAG (resolved from the gateway
catalog). Every tool result's provenance is collected into citations, so agent
answers are sourced.
"""

from __future__ import annotations

from agentengine import guardrails
from agentengine.client import PlatformClient
from agentengine.config import settings
from agentengine.models import AgentSpec, Citation, RunResult, Step
from agentengine.planner import get_planner


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


def _citations(tool: dict, result: dict) -> list[Citation]:
    src = tool.get("source")
    urls = list(dict.fromkeys(_find_urls(result.get("data"))))[:5]
    if not urls:
        return [Citation(tool=tool["name"], source=src)]
    return [Citation(tool=tool["name"], source=src, url=u) for u in urls]


def filter_tools(tools: dict, allowed: list[str] | None) -> dict:
    """Restrict ``tools`` to ``allowed`` — entries match a full tool name
    (``yahoo__prices``) or a connector id (``yahoo`` → all of its tools)."""
    if not allowed:
        return tools
    sel = set(allowed)
    return {name: t for name, t in tools.items() if name in sel or name.split("__")[0] in sel}


async def run_agent(task: str, api_key: str | None, spec: AgentSpec | None = None) -> RunResult:
    refusal = guardrails.check(task)
    if refusal:
        return RunResult(answer=refusal, refused=True, usage={"steps": 0})

    max_steps = (spec.max_steps if spec and spec.max_steps else settings.max_steps)
    system = spec.system if spec else None
    client = PlatformClient(api_key)
    tools = await client.fetch_tools()
    if spec and spec.allowed_tools:
        tools = filter_tools(tools, spec.allowed_tools)

    planner = get_planner(spec.backend if spec else None)
    history: list = []
    steps: list[Step] = []
    citations: list[Citation] = []
    answer = ""
    for _ in range(max_steps):
        decision = await planner.plan(task, tools, history, system)
        if decision.final is not None:
            answer = decision.final
            break
        tool = tools.get(decision.tool)
        if tool is None:
            answer = f"Planner selected an unavailable tool '{decision.tool}'."
            break
        result = await client.call_tool(tool, decision.args or {})
        steps.append(Step(tool=decision.tool, args=decision.args or {}, status=result["status"]))
        citations.extend(_citations(tool, result))
        history.append((decision, result))
    if not answer:
        final = await planner.plan(task, tools, history, system)
        answer = final.final or "Reached the step limit without a final answer."

    return RunResult(answer=answer, steps=steps, citations=citations, usage={"steps": len(steps)})
