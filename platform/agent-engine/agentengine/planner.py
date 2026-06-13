"""Planners: decide which tool to call (or finalize) given the task + tools.

* StubPlanner — deterministic keyword routing (dev/CI, no LLM). Calls one tool
  then summarizes. Lets the loop + provenance + guardrails be tested with no key.
* GeminiPlanner — real LLM (Gemini function calling), lazily imported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from agentengine.config import settings


@dataclass
class Decision:
    tool: str | None = None
    args: dict | None = None
    final: str | None = None


# task keyword -> tool-name suffix to prefer
_ROUTES = [
    ("price", "prices"), ("revenue", "income"), ("income", "income"), ("financ", "income"),
    ("earnings", "earnings"), ("filing", "filings"), ("insider", "insider"), ("news", "news"),
    ("interest rate", "interest"), ("macro", "interest"), ("risk", "search"), ("disclos", "search"),
    ("supplier", "search"), ("customer", "search"), ("company", "company_facts"), ("profile", "company_facts"),
]
_TICKER = re.compile(r"\b([A-Z]{1,5})\b")
_KRCODE = re.compile(r"\b(\d{6})\b")
_STOP = {"US", "KR", "I", "A", "SEC", "CEO", "Q", "FY", "AI", "ETF", "GPU"}


def _extract_ticker(task: str) -> str | None:
    kr = _KRCODE.search(task)
    if kr:
        return kr.group(1)
    for tok in _TICKER.findall(task):
        if tok not in _STOP:
            return tok
    return None


def _pick_tool(task: str, tools: dict) -> str | None:
    low = task.lower()
    for kw, suffix in _ROUTES:
        if kw in low:
            for name in tools:
                if name.split("__")[-1].startswith(suffix) or name.endswith(suffix):
                    return name
    for name in tools:
        if name.endswith("__company_facts"):
            return name
    return next(iter(tools), None)


def _args_for(task: str, tool: dict) -> dict:
    ticker = _extract_ticker(task)
    market = "KR" if (ticker and ticker.isdigit()) else "US"
    defaults = {
        "ticker": ticker, "market": market, "period": "annual", "interval": "day",
        "start_date": "2024-01-02", "end_date": "2024-01-08", "query": task, "limit": 3, "bank": "FED",
    }
    return {p["name"]: defaults[p["name"]] for p in tool.get("params", []) if defaults.get(p["name"]) is not None}


def _summarize(task: str, history: list) -> str:
    dec, res = history[-1]
    src = res.get("connector") or dec.tool.split("__")[0]
    ok = res["status"] == 200
    head = "Retrieved sourced data" if ok else f"The tool returned status {res['status']}"
    return f"{head} via `{dec.tool}` (source: {src}) for your request. See citations for provenance. (Not investment advice.)"


class StubPlanner:
    async def plan(self, task: str, tools: dict, history: list, system: str | None = None) -> Decision:
        if history:  # already observed a tool result -> finalize
            return Decision(final=_summarize(task, history))
        name = _pick_tool(task, tools)
        if not name:
            return Decision(final="No activated tool can serve this request — activate a connector first.")
        return Decision(tool=name, args=_args_for(task, tools[name]))


class GeminiPlanner:
    """Real Gemini planner (function calling). Untested without GOOGLE_API_KEY."""

    def __init__(self, model: str) -> None:
        from google import genai

        self._genai = genai
        self._client = genai.Client()
        self.model = model

    async def plan(self, task: str, tools: dict, history: list, system: str | None = None) -> Decision:
        import asyncio

        from google.genai import types

        if history:  # ask for a final, grounded answer from the observed data
            observed = "\n\n".join(f"{d.tool} -> {str(r['data'])[:1500]}" for d, r in history)
            prompt = (
                f"Task: {task}\n\nObserved tool results:\n{observed}\n\n"
                "Answer using ONLY this data. Cite the source. Do not predict prices or give advice."
            )
            resp = await asyncio.to_thread(self._client.models.generate_content, model=self.model, contents=prompt)
            return Decision(final=resp.text)
        decls = [
            types.FunctionDeclaration(name=t["name"], description=t["description"], parameters=_schema(t))
            for t in tools.values()
        ]
        base = (
            "You are a financial-data agent. Use the tools to fetch sourced facts. "
            "Never predict prices or give buy/sell advice; this is not investment advice."
        )
        config = types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=decls)],
            system_instruction=f"{base}\n\n{system.strip()}" if system and system.strip() else base,
        )
        resp = await asyncio.to_thread(self._client.models.generate_content, model=self.model, contents=task, config=config)
        calls = getattr(resp, "function_calls", None)
        if calls:
            call = calls[0]
            return Decision(tool=call.name, args=dict(call.args or {}))
        return Decision(final=resp.text)


def _schema(tool: dict) -> dict:
    props, required = {}, []
    for p in tool.get("params", []):
        prop = {"type": p.get("type", "string").upper() if p.get("type") in ("integer", "number", "boolean") else "STRING"}
        if p.get("enum"):
            prop["enum"] = p["enum"]
        props[p["name"]] = prop
        if p.get("required"):
            required.append(p["name"])
    return {"type": "OBJECT", "properties": props, "required": required}


@cache
def _build_planner(backend: str, model: str):
    if backend == "stub":
        return StubPlanner()
    if backend == "gemini":
        return GeminiPlanner(model)
    raise ValueError(f"Unknown agent backend '{backend}'.")


def get_planner(backend: str | None = None):
    """Return the planner for ``backend`` (per-agent override), else the server default."""
    return _build_planner(backend or settings.llm_backend, settings.model)
