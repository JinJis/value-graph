"""Agent Engine request/response models."""

from __future__ import annotations

from pydantic import BaseModel


class AgentSpec(BaseModel):
    """Declarative ('SDK') agent definition a tenant can save and reuse."""

    system: str | None = None
    # restrict to a subset of activated tools. Entries may be full tool names
    # (``yahoo__prices``) or connector ids (``yahoo`` → all of its tools).
    allowed_tools: list[str] | None = None
    max_steps: int | None = None
    backend: str | None = None  # planner override: 'stub' | 'gemini' (default = server setting)


class RunRequest(BaseModel):
    task: str
    spec: AgentSpec | None = None


class Message(BaseModel):
    role: str  # user | assistant | system
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    spec: AgentSpec | None = None


class CompileRequest(BaseModel):
    description: str


class Citation(BaseModel):
    tool: str
    source: str | None = None          # institution / publisher (e.g. 'SEC EDGAR', 'Reuters')
    url: str | None = None
    # --- PH-4/U2: enough to render a type-aware source-preview card ----------
    # ('kind', not 'type' — the SSE event envelope already uses 'type' as its
    # discriminator, so a field named 'type' would collide when flattened.)
    index: int | None = None           # 1-based [n] anchor, assigned after de-dup
    kind: str | None = None            # filing | news | metric | data
    doc_type: str | None = None        # e.g. '10-K', 'news' (from RAG provenance)
    as_of: str | None = None           # ISO date the cited fact is as of
    freshness: str | None = None       # fresh | aging | stale (computed from as_of)
    snippet: str | None = None         # cited span / headline — the preview body
    ticker: str | None = None
    page: str | None = None            # filing section / accession ref


class Step(BaseModel):
    tool: str
    args: dict
    status: int


class RunResult(BaseModel):
    answer: str
    refused: bool = False
    steps: list[Step] = []
    citations: list[Citation] = []
    usage: dict = {}
