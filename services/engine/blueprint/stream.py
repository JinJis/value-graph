"""Streaming blueprint generation — emits structured progress events.

The DEEP blueprint call takes tens of seconds, which used to look like a failure
(the proxy reset the socket before it finished). This runs the same generation as
``generate.py`` but yields a step-by-step event stream so Studio can show, live:
which tier/model is used, the exact endpoint called, the full prompt, the model's
output as it streams in, parse/validate outcomes, and the saved result.

Events (each a plain dict, serialized as SSE ``data:`` frames by the router):
  - ``model``    {tier, model}                — which Gemini model/agent is routed
  - ``endpoint`` {provider, method}           — where the call goes (server-side)
  - ``prompt``   {text, chars}                — the exact prompt sent
  - ``llm_start``{attempt, attempts}          — generation started (per attempt)
  - ``thought``  {text}                       — Deep Research reasoning summary
  - ``research`` {action, detail}             — a search/url-fetch the agent ran
  - ``chunk``    {text, accumulated_chars}    — streamed (report) output
  - ``parse``    {status, detail?}            — ok | retry (with reason)
  - ``sources``  {created}                    — Source rows created from citations
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
    create_citation_sources,
    parse_blueprint_content,
    parse_research_blueprint_content,
    parse_with_structuring,
    to_blueprint_company,
)
from services.engine.blueprint.models import (
    Blueprint,
    BlueprintCompany,
    BlueprintRecord,
    BlueprintResponse,
    DiscoveryContent,
    RoundMeta,
)
from services.engine.blueprint.prompt import (
    DEFAULT_TARGET_COMPANIES,
    build_discovery_prompt,
    build_refine_prompt,
    build_research_generate_prompt,
    discovery_instructions,
    refine_instructions,
    research_generate_instructions,
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


def _research_stream(router: LLMRouter, tier: Tier, prompt: str) -> Iterator[Event]:
    """Run the Deep Research agent, mapping its deltas to progress events. Report
    text becomes ``chunk`` events (concatenate them to rebuild the output); reasoning
    and tool calls become ``thought``/``research`` events. Callers accumulate the
    output by summing the ``text`` of ``chunk`` events only."""
    total = 0
    for delta in router.deep_research_stream(tier, prompt):
        kind = delta.get("kind")
        text = delta.get("text", "")
        if kind == "text":
            total += len(text)
            yield {"event": "chunk", "text": text, "accumulated_chars": total}
        elif kind == "thought":
            yield {"event": "thought", "text": text}
        elif kind == "search":
            yield {"event": "research", "action": "search", "detail": text}
        elif kind == "read":
            yield {"event": "research", "action": "read", "detail": text}


def generate_blueprint_events(
    theme: Theme,
    source_hints: list[str],
    router: LLMRouter,
    blueprints: BlueprintRepository,
    theme_repo: ThemeRepository,
    *,
    tier: Tier = Tier.RESEARCH,
    attempts: int = 2,
    target_count: int = DEFAULT_TARGET_COMPANIES,
) -> Iterator[Event]:
    """Run first-pass blueprint generation on the Deep Research agent, yielding
    progress events and persisting the result.

    Mirrors :func:`generate.generate_blueprint`: streams the agent's cited report
    (with live thought/search progress), parses the trailing JSON, records a Source
    per citation, and persists. The final ``saved`` event carries the persisted
    :class:`BlueprintResponse` so the caller can refresh the table.
    """
    model = router.model_for(tier)
    yield from _header_events(tier, model, method="interactions.create (deep-research)")

    prompt = build_research_generate_prompt(theme, source_hints, target_count=target_count)
    yield {"event": "prompt", "text": prompt, "chars": len(prompt)}

    content = None
    last_error: str | None = None
    for attempt in range(attempts):
        nudge = "" if attempt == 0 else "\n\nEnd your reply with ONLY the fenced ```json block."
        yield {"event": "llm_start", "attempt": attempt + 1, "attempts": attempts}

        buffer = ""
        try:
            for ev in _research_stream(router, tier, prompt + nudge):
                if ev["event"] == "chunk":
                    buffer += str(ev["text"])
                yield ev
        except Exception as exc:  # GeminiError, timeout, network
            yield {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
            return

        try:
            content = yield from parse_with_structuring(
                buffer,
                parse_research_blueprint_content,
                shape=research_generate_instructions(),
                router=router,
            )
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

    sources_created = create_citation_sources(theme.id, content.companies, theme_repo)
    yield {"event": "sources", "created": sources_created}

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
            companies=[to_blueprint_company(c) for c in content.companies],
            relationship_types=content.relationship_types,
            notes=content.notes,
            target_count=target_count,
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


def _header_events(
    tier: Tier, model: str, *, method: str = "models.generate_content_stream"
) -> Iterator[Event]:
    yield {"event": "model", "tier": tier.value, "model": model}
    yield {"event": "endpoint", "provider": "google-genai", "method": method}


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
            content = yield from parse_with_structuring(
                buffer,
                parse_blueprint_content,
                shape=refine_instructions(),
                router=router,
            )
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
                target_count=base.target_count,
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
    """Stream the RESEARCH discovery pass on the Deep Research agent. Mirrors
    :func:`discover.discover_companies`: find additional constituents (web-cited),
    create one Source per citation, merge into the plan."""
    model = router.model_for(tier)
    yield from _header_events(tier, model, method="interactions.create (deep-research)")

    known = sorted({normalize_ticker(c.ticker) for c in base.companies})
    prompt = build_discovery_prompt(theme, known)
    yield {"event": "prompt", "text": prompt, "chars": len(prompt)}
    yield {"event": "llm_start", "attempt": 1, "attempts": 1}

    buffer = ""
    try:
        for ev in _research_stream(router, tier, prompt):
            if ev["event"] == "chunk":
                buffer += str(ev["text"])
            yield ev
    except Exception as exc:
        yield {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
        return

    try:
        content = yield from parse_with_structuring(
            buffer,
            lambda t: DiscoveryContent.model_validate_json(_extract_json(t)),
            shape=discovery_instructions(),
            router=router,
        )
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
            target_count=base.target_count,
        ),
        round_meta=meta,
    )
    yield from _final_events(record)
