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

from pydantic import ValidationError

from services.engine.blueprint.coverage import summarize
from services.engine.blueprint.dedupe import (
    dedupe_companies,
    merge_companies,
    normalize_ticker,
    union_list,
)
from services.engine.blueprint.generate import (
    BlueprintParseError,
    _extract_json,
    parse_blueprint_content,
)
from services.engine.blueprint.models import (
    Blueprint,
    BlueprintCompany,
    BlueprintContent,
    BlueprintRecord,
    BlueprintResponse,
    DiscoveryContent,
    RoundMeta,
)
from services.engine.blueprint.prompt import (
    build_discovery_prompt,
    build_prompt,
    build_refine_prompt,
)
from services.engine.blueprint.refine import DELTA_THRESHOLD, ROUND_CAP
from services.engine.blueprint.repository import BlueprintRepository
from services.engine.llm.router import LLMRouter, Tier
from services.engine.themes.models import SourceCreate, Theme
from services.engine.themes.repository import ThemeRepository

Event = dict[str, Any]


def _stream_chunks(router: LLMRouter, tier: Tier, prompt: str) -> Iterator[Event]:
    """Yield ``chunk`` events as the model streams; the concatenated ``text`` of all
    chunks is the full output. Raises on the underlying Gemini/stream error."""
    total = 0
    for piece in router.generate_stream(tier, prompt):
        total += len(piece)
        yield {"event": "chunk", "text": piece, "accumulated_chars": total}


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


def _header_events(tier: Tier, model: str) -> Iterator[Event]:
    yield {"event": "model", "tier": tier.value, "model": model}
    yield {
        "event": "endpoint",
        "provider": "google-genai",
        "method": "models.generate_content_stream",
    }


def _final_events(record: BlueprintRecord) -> Iterator[Event]:
    response = BlueprintResponse(blueprint=record, coverage=summarize(record))
    yield {
        "event": "saved",
        "version": record.version,
        "blueprint": response.blueprint.model_dump(mode="json"),
        "coverage": response.coverage.model_dump(mode="json"),
    }
    yield {"event": "done"}


def refine_blueprint_events(
    theme: Theme,
    base: BlueprintRecord,
    router: LLMRouter,
    repo: BlueprintRepository,
    *,
    round_cap: int = ROUND_CAP,
    threshold: int = DELTA_THRESHOLD,
    tier: Tier = Tier.DEEP,
) -> Iterator[Event]:
    """Stream iterative refinement. Mirrors :func:`refine.refine_blueprint`: one DEEP
    call per round, merge+dedupe, persist a versioned round, stop at convergence/cap."""
    model = router.model_for(tier)
    yield from _header_events(tier, model)

    current = base
    companies = dedupe_companies(base.companies)
    ran = False
    while current.version < round_cap:
        ran = True
        round_no = current.version + 1
        yield {"event": "round", "round": round_no, "cap": round_cap}

        prompt = build_refine_prompt(theme, current)
        yield {"event": "prompt", "text": prompt, "chars": len(prompt)}
        yield {"event": "llm_start", "attempt": 1, "attempts": 1}

        buffer = ""
        try:
            for ev in _stream_chunks(router, tier, prompt):
                buffer += str(ev["text"])
                yield ev
        except Exception as exc:
            yield {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
            return

        try:
            content = parse_blueprint_content(buffer)
            yield {"event": "parse", "status": "ok"}
        except BlueprintParseError as exc:
            yield {"event": "parse", "status": "failed", "detail": str(exc)}
            yield {"event": "error", "detail": str(exc)}
            return

        merged = merge_companies(companies, content.companies)
        delta = merged.added + merged.updated
        converged = delta < threshold
        yield {
            "event": "merged",
            "added": merged.added,
            "updated": merged.updated,
            "delta": delta,
            "converged": converged,
        }

        version = repo.next_version(theme.id)
        meta = RoundMeta(
            round=version,
            added=merged.added,
            updated=merged.updated,
            delta=delta,
            converged=converged,
            generated_by=model,
        )
        current = repo.save(
            Blueprint(
                theme_id=theme.id,
                version=version,
                generated_by=model,
                companies=merged.companies,
                relationship_types=union_list(
                    current.relationship_types, content.relationship_types
                ),
                notes=content.notes or current.notes,
            ),
            round_meta=meta,
        )
        companies = merged.companies
        yield {"event": "saved", "version": current.version}
        if converged:
            break

    if not ran:
        yield {"event": "note", "text": f"already at round cap ({round_cap}); nothing to refine"}
    yield from _final_events(current)


def discover_companies_events(
    theme: Theme,
    base: BlueprintRecord,
    router: LLMRouter,
    blueprint_repo: BlueprintRepository,
    theme_repo: ThemeRepository,
    *,
    tier: Tier = Tier.RESEARCH,
) -> Iterator[Event]:
    """Stream the RESEARCH discovery pass. Mirrors :func:`discover.discover_companies`:
    find additional constituents, create one Source per citation, merge into the plan."""
    model = router.model_for(tier)
    yield from _header_events(tier, model)

    known = sorted({normalize_ticker(c.ticker) for c in base.companies})
    prompt = build_discovery_prompt(theme, known)
    yield {"event": "prompt", "text": prompt, "chars": len(prompt)}
    yield {"event": "llm_start", "attempt": 1, "attempts": 1}

    buffer = ""
    try:
        for ev in _stream_chunks(router, tier, prompt):
            buffer += str(ev["text"])
            yield ev
    except Exception as exc:
        yield {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
        return

    try:
        content = DiscoveryContent.model_validate_json(_extract_json(buffer))
        yield {"event": "parse", "status": "ok"}
    except (ValidationError, BlueprintParseError) as exc:
        yield {"event": "parse", "status": "failed", "detail": str(exc)}
        yield {"event": "error", "detail": str(exc)}
        return

    # One Source per distinct citation URL (each discovered company carries a Source).
    sources_created = 0
    seen_urls: set[str] = set()
    for company in content.companies:
        if company.source_url in seen_urls:
            continue
        seen_urls.add(company.source_url)
        theme_repo.add_source(
            theme.id,
            SourceCreate(
                type="report", url=company.source_url, publisher=company.source_publisher
            ),
        )
        sources_created += 1
    yield {"event": "sources", "created": sources_created}

    incoming = [
        BlueprintCompany(**company.model_dump(exclude={"source_publisher"}))
        for company in content.companies
    ]
    merged = merge_companies(dedupe_companies(base.companies), incoming)
    yield {
        "event": "validate",
        "discovered": len(content.companies),
        "added": merged.added,
        "updated": merged.updated,
        "companies": len(merged.companies),
    }

    version = blueprint_repo.next_version(theme.id)
    meta = RoundMeta(
        round=version,
        added=merged.added,
        updated=merged.updated,
        delta=merged.added + merged.updated,
        converged=False,
        generated_by=model,
    )
    record = blueprint_repo.save(
        Blueprint(
            theme_id=theme.id,
            version=version,
            generated_by=model,
            companies=merged.companies,
            relationship_types=base.relationship_types,
            notes=base.notes,
        ),
        round_meta=meta,
    )
    yield from _final_events(record)
