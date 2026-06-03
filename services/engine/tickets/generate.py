"""Gap -> ticket generator (PRD §8.3): every required-but-unsourced data point in an
approved blueprint becomes exactly one OPEN ticket.

Idempotent and duplicate-free: one ticket per (theme, target, metric) — re-running
skips data points already ticketed (enforced by the repository's ON CONFLICT).
"""

from __future__ import annotations

from services.engine.blueprint.models import Blueprint
from services.engine.tickets.models import GenerateResult, TicketCreate
from services.engine.tickets.repository import TicketRepository


def generate_tickets(
    theme_id: str, blueprint: Blueprint, repo: TicketRepository
) -> GenerateResult:
    created = 0
    skipped = 0
    for company in blueprint.companies:
        for metric in company.required_data_points:
            ticket = repo.create_open_ticket(
                theme_id,
                TicketCreate(
                    target=company.ticker,
                    metric=metric,
                    reason=f"required data point for {company.name} ({company.ticker})",
                ),
            )
            if ticket is None:
                skipped += 1
            else:
                created += 1
                repo.record_event(ticket.id, None, "OPEN", "system")
    return GenerateResult(created=created, skipped=skipped)
