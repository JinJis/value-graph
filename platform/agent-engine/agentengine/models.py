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


class ArtifactRefreshRequest(BaseModel):
    """Re-run a pinned artifact's tool+args to refresh it (U3-03b)."""

    tool: str
    args: dict | None = None
    title: str | None = None  # pick the matching artifact when a tool yields several


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


class ArtifactPoint(BaseModel):
    x: str               # date / report-period label
    y: float | None = None


class ArtifactSeries(BaseModel):
    label: str
    unit: str | None = None      # 'ratio' | currency | None
    points: list[ArtifactPoint] = []


class Artifact(BaseModel):
    """A typed, connector-backed figure emitted alongside prose (U3). The web renders
    it as an interactive card; gaps are drawn, never hidden."""

    kind: str                    # timeseries | compare | table
    title: str
    series: list[ArtifactSeries] = []
    source: str | None = None
    as_of: str | None = None
    freshness: str | None = None
    ticker: str | None = None
    has_gap: bool = False
    tool: str | None = None      # the tool that produced it (lets a pinned card ↻ refresh)
    args: dict | None = None     # the tool args, so a pinned card can re-fetch (U3-03)


class Step(BaseModel):
    tool: str
    args: dict
    status: int


class RunResult(BaseModel):
    answer: str
    refused: bool = False
    steps: list[Step] = []
    citations: list[Citation] = []
    artifacts: list[Artifact] = []
    usage: dict = {}
