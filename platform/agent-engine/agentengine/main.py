"""Agent Engine API — run agents over a tenant's activated connectors + RAG.

The tenant API key is supplied per request (X-API-KEY) and used for every tool
call through the gateway, so entitlement + metering apply to agent activity too.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Header

from agentengine.agent import run_agent
from agentengine.config import settings
from agentengine.models import AgentSpec, CompileRequest, RunRequest

app = FastAPI(
    title="Platform Agent Engine", version="0.1.0",
    description="Run agents over activated connectors + RAG, via the gateway, with provenance + guardrails.",
)


@app.get("/health", tags=["Meta"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/agent/info", tags=["Agent"], summary="Active planner + config")
async def info() -> dict:
    return {"llm_backend": settings.llm_backend, "model": settings.model, "gateway_url": settings.gateway_url}


@app.post("/agent/run", tags=["Agent"], summary="Run an agent task (NL) over activated tools")
async def run(body: RunRequest, x_api_key: Annotated[str | None, Header(alias="X-API-KEY")] = None) -> dict:
    result = await run_agent(body.task, x_api_key, body.spec)
    return result.model_dump()


@app.post("/agent/compile", tags=["Agent"], summary="Natural-language → reusable AgentSpec")
async def compile_spec(body: CompileRequest) -> dict:
    # Stub compiler: wrap the description as a system prompt. A Gemini-backed
    # compiler can infer allowed_tools/steps later.
    return AgentSpec(system=body.description.strip()).model_dump()
