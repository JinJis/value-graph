"""Batched per-ticket Deep Research resolution — one run, streamed, human-in-the-loop.

Resolves ALL selected tickets in a single Deep Research run (the agent shares theme +
value-chain context across them) and yields the same kind of progress events as
``blueprint/stream.py`` (model/prompt/chunk/…). The agent returns one result per ticket,
keyed by a stable ``ref``; each result carries a verdict:

- ``found``         → the figure + a cited source URL is persisted as a *proposal* on the
  ticket (status stays OPEN); the admin reviews and accepts it (attaching the cited URL
  as evidence → SUBMITTED) or rejects it. A "found" verdict WITHOUT a usable source/value
  is downgraded (no number enters without a Source).
- ``not_found`` / ``not_disclosed`` → ``UNRESOLVABLE`` (not-disclosed also feeds the CVE
  10% upper-bound constraint).
- ``paywalled`` / ``ambiguous`` → ``DEFERRED``.

Auto-resolutions are guarded by the ticket state machine and recorded in the audit log
with actor ``deep-research``; a disallowed transition yields a ``skipped`` event instead.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from services.engine.blueprint.generate import BlueprintParseError, _extract_json
from services.engine.blueprint.models import BlueprintRecord
from services.engine.blueprint.stream import _research_stream
from services.engine.llm.router import LLMRouter, Tier
from services.engine.themes.models import Theme
from services.engine.tickets.cluster import DEFAULT_MAX_CLUSTER_SIZE, cluster_tickets
from services.engine.tickets.models import Ticket
from services.engine.tickets.repository import TicketRepository
from services.engine.tickets.research_prompt import (
    ResearchItem,
    build_ticket_research_batch_prompt,
)
from services.engine.tickets.state import ReasonCode, can_transition, derived_estimate

logger = logging.getLogger("valuegraph.engine.tickets.research")

Event = dict[str, Any]

# The audit-log actor for an agent-driven auto-resolution (the agent made the call).
DEEP_RESEARCH_ACTOR = "deep-research"

Verdict = Literal["found", "not_disclosed", "not_found", "paywalled", "ambiguous"]


class TicketResolution(BaseModel):
    """The agent's structured answer for one ticket (keyed back by ``ref``)."""

    ref: str
    verdict: Verdict
    value: str | float | int | None = None
    unit: str | None = None
    as_of_date: str | None = None
    confidence: str | None = None
    source_url: str | None = None
    source_publisher: str | None = None
    notes: str | None = None


class TicketResolutionBatch(BaseModel):
    """The agent's full output: one resolution per ticket."""

    results: list[TicketResolution]


# Non-"found" verdicts map deterministically to a resolution status + reason code.
_VERDICT_RESOLUTION: dict[str, tuple[str, ReasonCode]] = {
    "not_found": ("UNRESOLVABLE", ReasonCode.NOT_FOUND),
    "not_disclosed": ("UNRESOLVABLE", ReasonCode.NOT_DISCLOSED),
    "paywalled": ("DEFERRED", ReasonCode.PAYWALLED),
    "ambiguous": ("DEFERRED", ReasonCode.AMBIGUOUS),
}


def _parse_batch(buffer: str) -> TicketResolutionBatch:
    """Pull the trailing JSON object out of the agent's report and validate it."""
    return TicketResolutionBatch.model_validate_json(_extract_json(buffer))


# When Deep Research returns a prose report with no JSON block, a cheap formatter model
# extracts the structured result from the report (the report HAS the answers; it just
# didn't format them). This avoids re-running the expensive agent.
_STRUCTURE_INSTRUCTIONS = """\
ROLE: You are a strict JSON formatter.
GOAL: Convert the RESEARCH REPORT below into the exact JSON the engine needs. Extract only
what the report actually states — do NOT invent values or URLs.

For EACH ref in REFS, output one result with a verdict:
- "found"         — the report gives the figure AND a real source URL for it.
- "not_disclosed" — the report says the company does not disclose it.
- "not_found"     — the report couldn't find it in any public source.
- "paywalled"     — the figure is behind a paywall.
- "ambiguous"     — the report is unclear / didn't resolve it.

OUTPUT FORMAT — return ONLY this JSON (no prose, no fences), one entry per ref, echoing it:
{"results": [{"ref": "<ref>", "verdict": "<one of the five>", "value": <figure or null>,
"unit": <string or null>, "as_of_date": "YYYY-MM-DD or null",
"confidence": "high"|"medium"|"low"|null, "source_url": <url or null>,
"source_publisher": <string or null>, "notes": <short string or null>}]}
"""


def _structure_batch(
    report: str, refs: list[str], router: LLMRouter, *, tier: Tier
) -> TicketResolutionBatch:
    """Coerce a prose Deep Research report into the required JSON via a cheap model."""
    prompt = (
        f"{_STRUCTURE_INSTRUCTIONS}\n"
        f"REFS (return EXACTLY one result per ref): {', '.join(refs)}\n\n"
        f"RESEARCH REPORT:\n{report}"
    )
    return TicketResolutionBatch.model_validate_json(_extract_json(router.generate(tier, prompt)))


def _research_batch(
    theme: Theme,
    ticket_list: list[Ticket],
    blueprint: BlueprintRecord | None,
    router: LLMRouter,
    ticket_repo: TicketRepository,
    *,
    tier: Tier,
    attempts: int,
    structure_tier: Tier = Tier.MEDIUM,
) -> Iterator[Event]:
    """Resolve ONE batch (cluster) of tickets in a single Deep Research call.

    Emits prompt/llm_start/chunk/parse and per-ticket proposed/auto_resolved/skipped;
    the caller frames model/endpoint/batch_start/done."""
    if not ticket_list:
        return
    company_by_ticker = (
        {c.ticker: c for c in blueprint.companies} if blueprint is not None else {}
    )
    relationship_types = blueprint.relationship_types if blueprint is not None else []
    notes = blueprint.notes if blueprint is not None else None

    refs = [f"T{i + 1}" for i in range(len(ticket_list))]
    items: list[ResearchItem] = [
        (ref, ticket, company_by_ticker.get(ticket.target))
        for ref, ticket in zip(refs, ticket_list, strict=True)
    ]
    prompt = build_ticket_research_batch_prompt(
        theme, items, relationship_types=relationship_types, notes=notes
    )
    yield {"event": "prompt", "text": prompt, "chars": len(prompt)}
    logger.info(
        "research.batch theme=%s tickets=%d chars=%d", theme.id, len(ticket_list), len(prompt)
    )

    batch: TicketResolutionBatch | None = None
    last_error: str | None = None
    for attempt in range(attempts):
        nudge = (
            ""
            if attempt == 0
            else "\n\nEnd your reply with ONLY the fenced ```json block containing every ref."
        )
        yield {"event": "llm_start", "attempt": attempt + 1, "attempts": attempts}

        buffer = ""
        try:
            for ev in _research_stream(router, tier, prompt + nudge):
                if ev.get("event") == "chunk":
                    buffer += str(ev.get("text", ""))
                yield ev
        except Exception as exc:  # GeminiError, timeout, network
            logger.warning("research.stream_error theme=%s: %s", theme.id, exc)
            yield {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
            return

        report = buffer.strip()
        if not report:
            # The agent produced reasoning/tool-calls but no final report text.
            last_error = "Deep Research returned no report text"
            more = attempt + 1 < attempts
            yield {
                "event": "parse",
                "status": "retry" if more else "failed",
                "detail": last_error,
            }
            continue

        # 1) The report may already end with the requested JSON block.
        try:
            batch = _parse_batch(report)
            yield {"event": "parse", "status": "ok"}
            break
        except (ValueError, ValidationError, BlueprintParseError):
            pass

        # 2) Deep Research often returns prose without JSON — extract it with a cheap model
        #    (no need to re-run the expensive agent).
        yield {
            "event": "parse",
            "status": "structuring",
            "detail": (
                f"no JSON in the report; extracting it with {router.model_for(structure_tier)}"
            ),
        }
        try:
            batch = _structure_batch(report, refs, router, tier=structure_tier)
            yield {"event": "parse", "status": "ok"}
            break
        except (ValueError, ValidationError, BlueprintParseError) as exc:
            last_error = str(exc)
            more = attempt + 1 < attempts
            yield {
                "event": "parse",
                "status": "retry" if more else "failed",
                "detail": last_error,
            }

    if batch is None:
        logger.warning("research.failed theme=%s: %s", theme.id, last_error)
        yield {"event": "error", "detail": last_error or "ticket research failed"}
        return

    by_ref = {r.ref: r for r in batch.results}
    for ref, ticket in zip(refs, ticket_list, strict=True):
        result = by_ref.get(ref)
        if result is None:
            yield {
                "event": "skipped",
                "ticket_id": ticket.id,
                "target": ticket.target,
                "metric": ticket.metric,
                "detail": "no result returned for this ticket",
            }
            continue
        yield from _apply_resolution(ticket, result, ticket_repo)


def _header_events(tier: Tier, model: str, ticket_list: list[Ticket]) -> Iterator[Event]:
    yield {"event": "model", "tier": tier.value, "model": model}
    yield {
        "event": "endpoint",
        "provider": "google-genai",
        "method": "interactions.create (deep-research)",
    }
    yield {
        "event": "batch_start",
        "count": len(ticket_list),
        "tickets": [
            {"ticket_id": t.id, "target": t.target, "metric": t.metric} for t in ticket_list
        ],
    }


def research_tickets_events(
    theme: Theme,
    tickets: Iterable[Ticket],
    blueprint: BlueprintRecord | None,
    router: LLMRouter,
    ticket_repo: TicketRepository,
    *,
    tier: Tier = Tier.RESEARCH,
    attempts: int = 2,
) -> Iterator[Event]:
    """Research all selected tickets in ONE Deep Research call (no clustering)."""
    ticket_list = list(tickets)
    yield from _header_events(tier, router.model_for(tier), ticket_list)
    yield from _research_batch(
        theme, ticket_list, blueprint, router, ticket_repo, tier=tier, attempts=attempts
    )
    yield {"event": "done"}


def research_ticket_clusters_events(
    theme: Theme,
    tickets: Iterable[Ticket],
    blueprint: BlueprintRecord | None,
    router: LLMRouter,
    ticket_repo: TicketRepository,
    *,
    tier: Tier = Tier.RESEARCH,
    cluster_tier: Tier = Tier.LOW,
    attempts: int = 2,
    max_cluster_size: int = DEFAULT_MAX_CLUSTER_SIZE,
) -> Iterator[Event]:
    """Cluster similar tickets with a cheap model, then run ONE Deep Research call per
    cluster (focused + bounded) instead of one mega-prompt over everything."""
    ticket_list = list(tickets)
    yield from _header_events(tier, router.model_for(tier), ticket_list)
    if not ticket_list:
        yield {"event": "done"}
        return

    yield {
        "event": "clustering",
        "tier": cluster_tier.value,
        "model": router.model_for(cluster_tier),
    }
    clusters = cluster_tickets(ticket_list, router, tier=cluster_tier, max_size=max_cluster_size)
    sizes = [len(c) for c in clusters]
    logger.info("research.clusters theme=%s clusters=%d sizes=%s", theme.id, len(clusters), sizes)
    yield {"event": "clusters", "count": len(clusters), "sizes": sizes}

    for index, cluster in enumerate(clusters):
        yield {
            "event": "cluster_start",
            "index": index + 1,
            "total": len(clusters),
            "size": len(cluster),
            "tickets": [
                {"ticket_id": t.id, "target": t.target, "metric": t.metric} for t in cluster
            ],
        }
        yield from _research_batch(
            theme, cluster, blueprint, router, ticket_repo, tier=tier, attempts=attempts
        )
    logger.info(
        "research.done theme=%s tickets=%d clusters=%d", theme.id, len(ticket_list), len(clusters)
    )
    yield {"event": "done"}


def _apply_resolution(
    ticket: Ticket, resolution: TicketResolution, ticket_repo: TicketRepository
) -> Iterator[Event]:
    tid = ticket.id
    tag = {"ticket_id": tid, "target": ticket.target, "metric": ticket.metric}

    if resolution.verdict == "found":
        url = (resolution.source_url or "").strip()
        has_value = resolution.value is not None and str(resolution.value).strip() != ""
        if url and has_value:
            proposal = {
                "value": resolution.value,
                "unit": resolution.unit,
                "as_of_date": resolution.as_of_date,
                "confidence": resolution.confidence,
                "source_url": url,
                "source_publisher": resolution.source_publisher,
                "notes": resolution.notes,
                "by": DEEP_RESEARCH_ACTOR,
            }
            ticket_repo.set_research_proposal(tid, proposal)
            logger.info(
                "research.proposed ticket=%s target=%s value=%r source=%s",
                tid,
                ticket.target,
                resolution.value,
                url,
            )
            yield {"event": "proposed", **tag, **proposal}
            return
        # "found" but no usable source/value: a number cannot enter without a Source —
        # downgrade to a deferral the admin can revisit.
        status, reason = "DEFERRED", ReasonCode.AMBIGUOUS
        note: str | None = "agent reported a value without a usable source URL"
    else:
        status, reason = _VERDICT_RESOLUTION[resolution.verdict]
        note = resolution.notes

    if not can_transition(ticket.status, status):
        logger.info(
            "research.skipped ticket=%s target=%s reason=cannot-transition %s->%s",
            tid,
            ticket.target,
            ticket.status,
            status,
        )
        yield {
            **tag,
            "event": "skipped",
            "detail": f"cannot transition {ticket.status} -> {status}",
        }
        return

    estimate = derived_estimate(reason)
    ticket_repo.set_resolution(tid, status, reason.value, current_estimate=estimate)
    ticket_repo.record_event(tid, ticket.status, status, DEEP_RESEARCH_ACTOR, reason.value)
    logger.info(
        "research.auto_resolved ticket=%s target=%s verdict=%s status=%s reason=%s",
        tid,
        ticket.target,
        resolution.verdict,
        status,
        reason.value,
    )
    yield {
        **tag,
        "event": "auto_resolved",
        "status": status,
        "reason_code": reason.value,
        "notes": note,
    }
