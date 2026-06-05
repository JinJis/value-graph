"""Central Gemini router — every LLM call in ValueGraph goes through here.

CLAUDE.md hard rule: Gemini only, model IDs from env, keys server-side & never
logged. The actual SDK call sits behind a :class:`TextGenerator` protocol so the
router can be unit-tested with a fake (no network, no API key), while production
uses :class:`GeminiTextGenerator` (the ``google-genai`` SDK).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Mapping
from enum import StrEnum
from typing import Any, Protocol

logger = logging.getLogger("valuegraph.engine.llm")


class Tier(StrEnum):
    """Routing tiers (CLAUDE.md §3). Map to env-overridable model IDs."""

    DEEP = "DEEP"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    RESEARCH = "RESEARCH"


# Built-in defaults (CLAUDE.md §3). NOT a source of truth — env overrides win;
# verify IDs against current Google docs before changing.
DEFAULT_MODELS: Mapping[Tier, str] = {
    Tier.DEEP: "gemini-3.1-pro-preview",
    Tier.MEDIUM: "gemini-3.5-flash",
    Tier.LOW: "gemini-3.1-flash-lite",
    # RESEARCH is the Gemini Deep Research Agent (preview) — it autonomously
    # plans/searches/reads the live web and returns CITED findings. It is NOT a
    # generate_content model: it is reached via the Interactions API
    # (deep_research_stream below), never router.generate / generate_stream.
    Tier.RESEARCH: "deep-research-preview-04-2026",
}

# A Deep Research *agent* id (Interactions API) is distinguishable from a regular
# generate_content model: every agent id is "deep-research-*". The RESEARCH tier MUST
# be an agent — a regular model in the ``agent`` field is rejected ("refers to a model,
# but was provided in the 'agent' field"). We use this to reject stale config.
_DEEP_RESEARCH_AGENT_MARKER = "deep-research"

ENV_VAR: Mapping[Tier, str] = {
    Tier.DEEP: "MODEL_DEEP",
    Tier.MEDIUM: "MODEL_MEDIUM",
    Tier.LOW: "MODEL_LOW",
    Tier.RESEARCH: "MODEL_RESEARCH",
}


def resolve_tier(tier: Tier | str) -> Tier:
    """Coerce ``tier`` to a :class:`Tier`, raising ``ValueError`` on an unknown one."""
    if isinstance(tier, Tier):
        return tier
    if isinstance(tier, str):
        try:
            return Tier(tier.upper())
        except ValueError as exc:
            raise ValueError(f"Unknown LLM tier: {tier!r}") from exc
    raise ValueError(f"Unknown LLM tier: {tier!r}")


class TextGenerator(Protocol):
    """The single capability the router needs: turn a prompt into text.

    A generator MAY also expose ``generate_text_stream(*, model, prompt) ->
    Iterator[str]`` to stream chunks; it's intentionally NOT part of this Protocol
    so simple fakes stay valid. :meth:`LLMRouter.generate_stream` detects it at
    runtime and falls back to a single :meth:`generate_text` chunk otherwise.
    """

    def generate_text(self, *, model: str, prompt: str) -> str: ...


class GeminiError(RuntimeError):
    """A Gemini SDK/network call failed — carries the model + underlying cause."""


# One streamed piece from the Deep Research agent. ``kind`` is one of:
#   "text"    — part of the final report/output (concatenate to rebuild it)
#   "thought" — an intermediate reasoning summary (progress only)
#   "search"  — a Google Search the agent issued ("text" = the queries)
#   "read"    — a web page the agent fetched via URL context ("text" = the URLs)
ResearchDelta = dict[str, str]


def _gemini_timeout_ms() -> int:
    """Per-call HTTP timeout (ms). Without it a blocked egress hangs forever and the
    upstream proxy resets the socket ("socket hang up") with no usable error."""
    raw = os.environ.get("GEMINI_TIMEOUT_SECONDS", "120")
    try:
        return max(1, int(float(raw))) * 1000
    except ValueError:
        return 120_000


def _deep_research_timeout_seconds() -> float:
    """Per-call timeout (s) for a Deep Research run. These are agentic, multi-step
    tasks (plan→search→read→write) that take MINUTES, not seconds — the standard
    ``GEMINI_TIMEOUT_SECONDS`` is far too short. Default 1h (the agent's own cap)."""
    raw = os.environ.get("DEEP_RESEARCH_TIMEOUT_SECONDS", "3600")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 3600.0


class GeminiTextGenerator:
    """Production :class:`TextGenerator` backed by the ``google-genai`` SDK."""

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key
        self._client: Any = None  # lazily constructed; keeps the SDK import optional

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise RuntimeError("GOOGLE_API_KEY is not set; cannot call Gemini.")
            from google import genai  # lazy: unit tests never need the SDK installed
            from google.genai import types

            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=_gemini_timeout_ms()),
            )
        return self._client

    def generate_text(self, *, model: str, prompt: str) -> str:
        client = self._get_client()
        try:
            response = client.models.generate_content(model=model, contents=prompt)
        except Exception as exc:  # SDK errors, timeouts, network — make them legible
            # Never include the prompt or key; just the model and the cause.
            raise GeminiError(f"Gemini call failed for model {model!r}: {exc}") from exc
        text = response.text
        return text if isinstance(text, str) else ""

    def generate_text_stream(self, *, model: str, prompt: str) -> Iterator[str]:
        client = self._get_client()
        try:
            stream = client.models.generate_content_stream(model=model, contents=prompt)
            for chunk in stream:
                piece = getattr(chunk, "text", None)
                if isinstance(piece, str) and piece:
                    yield piece
        except Exception as exc:
            raise GeminiError(f"Gemini stream failed for model {model!r}: {exc}") from exc

    def deep_research_stream(self, *, agent: str, prompt: str) -> Iterator[ResearchDelta]:
        """Run the Deep Research agent via the Interactions API, streaming progress.

        Deep Research is an agent (plan→search→read→synthesize), not a chat model:
        it is reached through ``client.interactions``, must run in the background
        (``background=True`` ⇒ ``store=True``), and emits intermediate reasoning,
        tool calls (search/url-context) and the final cited text as SSE events. We
        normalise those into :data:`ResearchDelta` dicts; tool calls are surfaced as
        progress so callers can show "searching…/reading…" while the report builds.
        """
        client = self._get_client()
        try:
            stream = client.interactions.create(
                input=prompt,
                agent=agent,
                background=True,
                store=True,
                stream=True,
                agent_config={
                    "type": "deep-research",
                    # surface the agent's reasoning as live progress…
                    "thinking_summaries": "auto",
                    # …but no charts/images: we only want a cited text report + JSON.
                    "visualization": "off",
                },
                timeout=_deep_research_timeout_seconds(),
            )
            for event in stream:
                if getattr(event, "event_type", None) == "error":
                    err = getattr(event, "error", None)
                    msg = getattr(err, "message", None) or "deep research stream error"
                    raise GeminiError(f"Deep Research failed for agent {agent!r}: {msg}")
                if getattr(event, "event_type", None) != "step.delta":
                    continue
                delta = getattr(event, "delta", None)
                dtype = getattr(delta, "type", None)
                if dtype == "text":
                    text = getattr(delta, "text", None)
                    if isinstance(text, str) and text:
                        yield {"kind": "text", "text": text}
                elif dtype == "thought_summary":
                    content = getattr(delta, "content", None)
                    text = getattr(content, "text", None)
                    if isinstance(text, str) and text:
                        yield {"kind": "thought", "text": text}
                elif dtype == "google_search_call":
                    queries = getattr(getattr(delta, "arguments", None), "queries", None) or []
                    if queries:
                        yield {"kind": "search", "text": ", ".join(queries)}
                elif dtype == "url_context_call":
                    urls = getattr(getattr(delta, "arguments", None), "urls", None) or []
                    if urls:
                        yield {"kind": "read", "text": ", ".join(urls)}
        except GeminiError:
            raise
        except Exception as exc:  # SDK errors, timeouts, network
            raise GeminiError(f"Deep Research stream failed for agent {agent!r}: {exc}") from exc

    def __repr__(self) -> str:
        # Never expose the key.
        return f"GeminiTextGenerator(api_key={'***' if self._api_key else None})"


class LLMRouter:
    """Routes a (tier, prompt) to the right Gemini model and returns text."""

    def __init__(self, generator: TextGenerator, models: Mapping[Tier, str]) -> None:
        self._generator = generator
        self._models: dict[Tier, str] = dict(models)

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        generator: TextGenerator | None = None,
    ) -> LLMRouter:
        """Build a router with model IDs read from ``env`` (default ``os.environ``).

        ``generator`` is injectable for testing; production defaults to
        :class:`GeminiTextGenerator` using ``GOOGLE_API_KEY``.
        """
        source: Mapping[str, str] = os.environ if env is None else env
        models = {tier: source.get(ENV_VAR[tier], DEFAULT_MODELS[tier]) for tier in Tier}
        # Guard against a stale MODEL_RESEARCH pointing at a regular model (the old
        # default was a generate_content model). The RESEARCH tier is the Deep Research
        # agent; a non-agent id would be sent to the Interactions ``agent`` field and
        # rejected, so coerce it back to the agent default with a loud warning.
        research = models[Tier.RESEARCH]
        if _DEEP_RESEARCH_AGENT_MARKER not in research:
            logger.warning(
                "MODEL_RESEARCH=%r is not a Deep Research agent; the RESEARCH tier uses "
                "the Interactions API and needs a 'deep-research-*' agent. Falling back "
                "to %s. Unset/fix MODEL_RESEARCH to silence this.",
                research,
                DEFAULT_MODELS[Tier.RESEARCH],
            )
            models[Tier.RESEARCH] = DEFAULT_MODELS[Tier.RESEARCH]
        gen = generator
        if gen is None:
            gen = GeminiTextGenerator(source.get("GOOGLE_API_KEY"))
        return cls(gen, models)

    def model_for(self, tier: Tier | str) -> str:
        """Return the configured model ID for ``tier`` (raises on a bad tier)."""
        return self._models[resolve_tier(tier)]

    def generate(self, tier: Tier | str, prompt: str) -> str:
        """Generate text for ``prompt`` on the model bound to ``tier``."""
        resolved = resolve_tier(tier)
        model = self._models[resolved]
        # Log routing only — never the API key, never the prompt contents.
        logger.info("llm.generate tier=%s model=%s", resolved.value, model)
        return self._generator.generate_text(model=model, prompt=prompt)

    def generate_stream(self, tier: Tier | str, prompt: str) -> Iterator[str]:
        """Stream text chunks for ``prompt`` on the model bound to ``tier``.

        Falls back to a single chunk if the underlying generator can't stream, so
        callers always get the same text either way.
        """
        resolved = resolve_tier(tier)
        model = self._models[resolved]
        logger.info("llm.generate_stream tier=%s model=%s", resolved.value, model)
        stream = getattr(self._generator, "generate_text_stream", None)
        if stream is None:
            yield self._generator.generate_text(model=model, prompt=prompt)
            return
        yield from stream(model=model, prompt=prompt)

    def deep_research_stream(
        self, tier: Tier | str, prompt: str
    ) -> Iterator[ResearchDelta]:
        """Stream Deep Research deltas for ``prompt`` on the agent bound to ``tier``.

        ``tier`` is normally :attr:`Tier.RESEARCH` (the Deep Research agent). Falls
        back to a single ``text`` delta from :meth:`generate_text` when the generator
        can't do Deep Research (e.g. unit-test fakes), so callers get the same shape.
        """
        resolved = resolve_tier(tier)
        agent = self._models[resolved]
        logger.info("llm.deep_research tier=%s agent=%s", resolved.value, agent)
        fn = getattr(self._generator, "deep_research_stream", None)
        if fn is None:
            text = self._generator.generate_text(model=agent, prompt=prompt)
            yield {"kind": "text", "text": text}
            return
        yield from fn(agent=agent, prompt=prompt)

    def __repr__(self) -> str:
        return f"LLMRouter(models={self._models!r}, generator={self._generator!r})"
