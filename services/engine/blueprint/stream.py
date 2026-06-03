"""Streaming blueprint generation — emits structured progress events.

The DEEP blueprint call takes tens of seconds, which used to look like a failure
(the proxy reset the socket before it finished). This runs the same generation as
``generate.py`` but yields a step-by-step event stream so Studio can show, live:
which tier/model is used, the exact endpoint called, the full prompt, the model's
output as it streams in, parse/validate outcomes, and the saved result.

Events (each a plain dict, serialized as SSE ``data:`` frames by the router):
  - ``model``    {tier, model}                — which Gemini model is routed
  - ``endpoint`` {provider, method}           — where the call goes (server-side)
  - ``prompt``   {text, chars}                — the exact prompt sent
  - ``llm_start``{attempt, attempts}          — generation started (per attempt)
  - ``chunk``    {text, accumulated_chars}    — streamed model output
  - ``parse``    {status, detail?}            — ok | retry (with reason)
  - ``validate`` {companies, relationship_types}
  - ``saved``    {blueprint, coverage, version}
  - ``error``    {detail}
  - ``done``     {}
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from services.engine.blueprint.coverage import summarize
from services.engine.blueprint.generate import BlueprintParseError, parse_blueprint_content
from services.engine.blueprint.models import (
    Blueprint,
    BlueprintContent,
    BlueprintResponse,
)
from services.engine.blueprint.prompt import build_prompt
from services.engine.blueprint.repository import BlueprintRepository
from services.engine.llm.router import LLMRouter, Tier
from services.engine.themes.models import Theme

Event = dict[str, Any]


def generate_blueprint_events(
    theme: Theme,
    source_hints: list[str],
    router: LLMRouter,
    blueprints: BlueprintRepository,
    *,
    tier: Tier = Tier.DEEP,
    attempts: int = 2,
) -> Iterator[Event]:
    """Run blueprint generation, yielding progress events and persisting the result.

    Mirrors :func:`generate.generate_blueprint` (same prompt, same 2-attempt parse
    retry, same persistence) but observable. The final ``saved`` event carries the
    persisted :class:`BlueprintResponse` so the caller can refresh the table.
    """
    model = router.model_for(tier)
    yield {"event": "model", "tier": tier.value, "model": model}
    yield {
        "event": "endpoint",
        "provider": "google-genai",
        "method": "models.generate_content_stream",
    }

    prompt = build_prompt(theme, source_hints)
    yield {"event": "prompt", "text": prompt, "chars": len(prompt)}

    content: BlueprintContent | None = None
    last_error: str | None = None
    for attempt in range(attempts):
        nudge = "" if attempt == 0 else "\n\nReturn ONLY valid JSON, no prose, no fences."
        yield {"event": "llm_start", "attempt": attempt + 1, "attempts": attempts}

        buffer = ""
        try:
            for piece in router.generate_stream(tier, prompt + nudge):
                buffer += piece
                yield {"event": "chunk", "text": piece, "accumulated_chars": len(buffer)}
        except Exception as exc:  # GeminiError, timeout, network
            yield {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
            return

        try:
            content = parse_blueprint_content(buffer)
            yield {"event": "parse", "status": "ok"}
            break
        except BlueprintParseError as exc:
            last_error = str(exc)
            more = attempt + 1 < attempts
            yield {
                "event": "parse",
                "status": "retry" if more else "failed",
                "detail": last_error,
            }

    if content is None:
        yield {"event": "error", "detail": last_error or "blueprint generation failed"}
        return

    yield {
        "event": "validate",
        "companies": len(content.companies),
        "relationship_types": content.relationship_types,
    }

    version = blueprints.next_version(theme.id)
    record = blueprints.save(
        Blueprint(
            theme_id=theme.id,
            version=version,
            generated_by=model,
            companies=content.companies,
            relationship_types=content.relationship_types,
            notes=content.notes,
        )
    )
    response = BlueprintResponse(blueprint=record, coverage=summarize(record))
    yield {
        "event": "saved",
        "version": record.version,
        "blueprint": response.blueprint.model_dump(mode="json"),
        "coverage": response.coverage.model_dump(mode="json"),
    }
    yield {"event": "done"}
