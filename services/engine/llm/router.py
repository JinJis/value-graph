"""Central Gemini router — every LLM call in ValueGraph goes through here.

CLAUDE.md hard rule: Gemini only, model IDs from env, keys server-side & never
logged. The actual SDK call sits behind a :class:`TextGenerator` protocol so the
router can be unit-tested with a fake (no network, no API key), while production
uses :class:`GeminiTextGenerator` (the ``google-genai`` SDK).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
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
    # The real Deep Research Agent is wired in M1-DISC-04; until then RESEARCH
    # routes to the DEEP model so the path is exercisable.
    Tier.RESEARCH: "gemini-3.1-pro-preview",
}

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
    """The single capability the router needs: turn a prompt into text."""

    def generate_text(self, *, model: str, prompt: str) -> str: ...


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

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate_text(self, *, model: str, prompt: str) -> str:
        client = self._get_client()
        response = client.models.generate_content(model=model, contents=prompt)
        text = response.text
        return text if isinstance(text, str) else ""

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

    def __repr__(self) -> str:
        return f"LLMRouter(models={self._models!r}, generator={self._generator!r})"
