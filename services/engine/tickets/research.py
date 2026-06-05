"""Per-ticket Deep Research resolution — streamed, with human-in-the-loop on success.

Runs the Deep Research agent against each selected ticket (sequentially) and yields the
same kind of progress events as ``blueprint/stream.py`` (model/prompt/chunk/…), tagged
with ``ticket_id``. The agent returns a verdict:

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

from collections.abc import Iterable, Iterator
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from services.engine.blueprint.generate import BlueprintParseError, _extract_json
from services.engine.blueprint.models import BlueprintCompany
from services.engine.blueprint.stream import _research_stream
from services.engine.llm.router import LLMRouter, Tier
from services.engine.tickets.models import Ticket
from services.engine.tickets.repository import TicketRepository
from services.engine.tickets.research_prompt import build_ticket_research_prompt
from services.engine.tickets.state import ReasonCode, can_transition, derived_estimate

Event = dict[str, Any]

# The audit-log actor for an agent-driven auto-resolution (the agent made the call).
DEEP_RESEARCH_ACTOR = "deep-research"

Verdict = Literal["found", "not_disclosed", "not_found", "paywalled", "ambiguous"]


class TicketResolution(BaseModel):
    """The agent's structured answer for one ticket (parsed from its report)."""

    verdict: Verdict
    value: str | float | int | None = None
    unit: str | None = None
    as_of_date: str | None = None
    confidence: str | None = None
    source_url: str | None = None
    source_publisher: str | None = None
    notes: str | None = None


# Non-"found" verdicts map deterministically to a resolution status + reason code.
_VERDICT_RESOLUTION: dict[str, tuple[str, ReasonCode]] = {
    "not_found": ("UNRESOLVABLE", ReasonCode.NOT_FOUND),
    "not_disclosed": ("UNRESOLVABLE", ReasonCode.NOT_DISCLOSED),
    "paywalled": ("DEFERRED", ReasonCode.PAYWALLED),
    "ambiguous": ("DEFERRED", ReasonCode.AMBIGUOUS),
}


def _parse_resolution(buffer: str) -> TicketResolution:
    """Pull the trailing JSON object out of the agent's report and validate it."""
    return TicketResolution.model_validate_json(_extract_json(buffer))


def research_tickets_events(
    tickets: Iterable[Ticket],
    company_by_ticker: dict[str, BlueprintCompany],
    router: LLMRouter,
    ticket_repo: TicketRepository,
    *,
    tier: Tier = Tier.RESEARCH,
    attempts: int = 2,
) -> Iterator[Event]:
    """Research each ticket on the Deep Research agent, yielding progress events and
    persisting the outcome (proposal on success, auto-resolution otherwise)."""
    model = router.model_for(tier)
    yield {"event": "model", "tier": tier.value, "model": model}
    yield {
        "event": "endpoint",
        "provider": "google-genai",
        "method": "interactions.create (deep-research)",
    }
    for ticket in tickets:
        yield from _research_one(
            ticket,
            company_by_ticker.get(ticket.target),
            router,
            ticket_repo,
            tier=tier,
            attempts=attempts,
        )
    yield {"event": "done"}


def _research_one(
    ticket: Ticket,
    company: BlueprintCompany | None,
    router: LLMRouter,
    ticket_repo: TicketRepository,
    *,
    tier: Tier,
    attempts: int,
) -> Iterator[Event]:
    tid = ticket.id
    yield {
        "event": "ticket_start",
        "ticket_id": tid,
        "target": ticket.target,
        "metric": ticket.metric,
    }

    prompt = build_ticket_research_prompt(ticket, company)
    yield {"event": "prompt", "ticket_id": tid, "text": prompt, "chars": len(prompt)}

    resolution: TicketResolution | None = None
    last_error: str | None = None
    for attempt in range(attempts):
        nudge = "" if attempt == 0 else "\n\nEnd your reply with ONLY the fenced ```json block."
        yield {"event": "llm_start", "ticket_id": tid, "attempt": attempt + 1, "attempts": attempts}

        buffer = ""
        try:
            for ev in _research_stream(router, tier, prompt + nudge):
                if ev.get("event") == "chunk":
                    buffer += str(ev.get("text", ""))
                yield {**ev, "ticket_id": tid}
        except Exception as exc:  # GeminiError, timeout, network
            yield {"event": "error", "ticket_id": tid, "detail": f"{type(exc).__name__}: {exc}"}
            yield {"event": "ticket_done", "ticket_id": tid, "outcome": "error"}
            return

        try:
            resolution = _parse_resolution(buffer)
            yield {"event": "parse", "ticket_id": tid, "status": "ok"}
            break
        except (ValidationError, BlueprintParseError) as exc:
            last_error = str(exc)
            more = attempt + 1 < attempts
            yield {
                "event": "parse",
                "ticket_id": tid,
                "status": "retry" if more else "failed",
                "detail": last_error,
            }

    if resolution is None:
        yield {"event": "error", "ticket_id": tid, "detail": last_error or "ticket research failed"}
        yield {"event": "ticket_done", "ticket_id": tid, "outcome": "error"}
        return

    yield from _apply_resolution(ticket, resolution, ticket_repo)


def _apply_resolution(
    ticket: Ticket, resolution: TicketResolution, ticket_repo: TicketRepository
) -> Iterator[Event]:
    tid = ticket.id

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
            yield {"event": "proposed", "ticket_id": tid, **proposal}
            yield {"event": "ticket_done", "ticket_id": tid, "outcome": "proposed"}
            return
        # "found" but no usable source/value: a number cannot enter without a Source —
        # downgrade to a deferral the admin can revisit.
        status, reason = "DEFERRED", ReasonCode.AMBIGUOUS
        note: str | None = "agent reported a value without a usable source URL"
    else:
        status, reason = _VERDICT_RESOLUTION[resolution.verdict]
        note = resolution.notes

    if not can_transition(ticket.status, status):
        yield {
            "event": "skipped",
            "ticket_id": tid,
            "detail": f"cannot transition {ticket.status} -> {status}",
        }
        yield {"event": "ticket_done", "ticket_id": tid, "outcome": "skipped"}
        return

    estimate = derived_estimate(reason)
    ticket_repo.set_resolution(tid, status, reason.value, current_estimate=estimate)
    ticket_repo.record_event(tid, ticket.status, status, DEEP_RESEARCH_ACTOR, reason.value)
    yield {
        "event": "auto_resolved",
        "ticket_id": tid,
        "status": status,
        "reason_code": reason.value,
        "notes": note,
    }
    yield {"event": "ticket_done", "ticket_id": tid, "outcome": "auto_resolved"}
