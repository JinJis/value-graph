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


class KpiRequest(BaseModel):
    """PH-DATA-5 / PH-9: extract a company's reported KPIs from its filing-text corpus,
    each KPI cited to (and highlighted in) the source filing passage."""

    ticker: str
    market: str | None = None      # US | KR (inferred from the ticker when omitted)
    top_k: int | None = None       # filing passages to consider (default in kpi.py)
    spec: AgentSpec | None = None  # planner-backend override (stub|gemini)


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
    snippet: str | None = None         # cited span / headline / computation — the preview body
    ticker: str | None = None
    page: str | None = None            # filing section / accession ref
    # the specific figures this citation actually contributed — rendered as an
    # extracted-data table in the preview (header row first, cited row marked).
    table: list[list[str]] | None = None
    # PH-PROV2: a datasets `/evidence?…` endpoint URL — the frontend fetches a highlighted
    # screenshot of the exact filing line this figure came from, lazily on viewer-open.
    # Just the link (deterministic, no render) so the answer stream is never blocked.
    evidence_image_url: str | None = None
    # evidence flag: True iff this source actually backed the answer (cited [n] or
    # backs an artifact). The Live Context shows only evidence; consulted-but-unused
    # sources stay in the answer's 도구·출처 list.
    used: bool = False


class ArtifactPoint(BaseModel):
    x: str               # date / report-period label
    y: float | None = None


class ArtifactSeries(BaseModel):
    label: str
    unit: str | None = None      # 'ratio' | currency | None
    points: list[ArtifactPoint] = []


class ArtifactCandle(BaseModel):
    """One OHLCV bar for a candlestick artifact (PH-VIZ-1) — real prices, not synthesized."""

    time: str                    # 'YYYY-MM-DD'
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None


class ArtifactMarker(BaseModel):
    """PH-VIZ-2: a sourced event on the chart's time axis (earnings / dividend / split /
    filing). Clicking it opens the source in the evidence viewer — the chart IS evidence."""

    time: str                    # 'YYYY-MM-DD' (renderer snaps to the nearest bar)
    label: str
    kind: str = "event"          # earnings | dividend | split | filing
    position: str = "aboveBar"   # aboveBar | belowBar
    color: str | None = None
    source: str | None = None
    url: str | None = None
    snippet: str | None = None


class ArtifactPriceLine(BaseModel):
    """PH-VIZ-2: a horizontal reference line (e.g. 52-week high/low) — descriptive, drawn
    from the price data itself."""

    price: float
    label: str
    color: str | None = None


class Artifact(BaseModel):
    """A typed, connector-backed figure emitted alongside prose (U3). The web renders
    it as an interactive card (TradingView Lightweight Charts); gaps are drawn, never hidden."""

    kind: str                    # timeseries | candlestick | compare | table | kpi
    title: str
    series: list[ArtifactSeries] = []
    # for kind=candlestick (prices): real OHLCV bars rendered as candles + a volume pane.
    candles: list[ArtifactCandle] = []
    # PH-VIZ-2: sourced event markers + descriptive reference lines on a price chart.
    markers: list[ArtifactMarker] = []
    pricelines: list[ArtifactPriceLine] = []
    # for kind in {table, kpi}: a header-first matrix (e.g. [["지표","값","기간"], …]).
    # each data row is sourced via the matching Citation → /evidence (PH-DATA-5).
    table: list[list[str]] | None = None
    source: str | None = None
    as_of: str | None = None
    freshness: str | None = None
    ticker: str | None = None
    has_gap: bool = False
    url: str | None = None       # canonical link to the filing/source the figures came from
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
