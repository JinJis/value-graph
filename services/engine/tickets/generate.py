"""Gap -> ticket generator (PRD §8.3): every required-but-unsourced data point in an
approved blueprint becomes exactly one OPEN ticket.

Idempotent and duplicate-free: one ticket per (theme, target, metric) — re-running
skips data points already ticketed (enforced by the repository's ON CONFLICT). The
``metric`` is the raw data point (the stable dedup key); each ticket's ``reason`` is a
detailed, researchable brief (cheap-model enriched, with a deterministic fallback) so the
Deep Research agent knows exactly what to find, why, and where.
"""

from __future__ import annotations

from services.engine.blueprint.models import Blueprint
from services.engine.llm.router import LLMRouter
from services.engine.themes.models import Theme
from services.engine.tickets.enrich import (
    EnrichItem,
    enrich_descriptions,
    fallback_description,
)
from services.engine.tickets.models import GenerateResult, TicketCreate
from services.engine.tickets.repository import TicketRepository


def generate_tickets(
    theme_id: str,
    blueprint: Blueprint,
    repo: TicketRepository,
    *,
    theme: Theme | None = None,
    router: LLMRouter | None = None,
) -> GenerateResult:
    """Create one OPEN ticket per required data point. When ``theme`` and ``router`` are given,
    a cheap model writes a detailed research brief per ticket; otherwise a richer deterministic
    description is used. ``metric`` (the dedup key) is always the raw data point."""
    items: list[EnrichItem] = []
    for company in blueprint.companies:
        for metric in company.required_data_points:
            items.append((f"P{len(items) + 1}", company, metric))

    enriched = (
        enrich_descriptions(theme, items, router)
        if theme is not None and router is not None
        else {}
    )

    created = 0
    skipped = 0
    for ref, company, metric in items:
        reason = enriched.get(ref) or fallback_description(theme, company, metric)
        ticket = repo.create_open_ticket(
            theme_id,
            TicketCreate(target=company.ticker, metric=metric, reason=reason),
        )
        if ticket is None:
            skipped += 1
        else:
            created += 1
            repo.record_event(ticket.id, None, "OPEN", "system")
    return GenerateResult(created=created, skipped=skipped)
