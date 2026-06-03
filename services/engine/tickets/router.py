"""Ticket generation + listing endpoints (PRD §8.3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from services.engine.blueprint.repository import BlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository
from services.engine.db.config import DbSettings
from services.engine.themes.repository import ThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository
from services.engine.tickets.generate import generate_tickets
from services.engine.tickets.models import (
    GenerateResult,
    ResolveRequest,
    Ticket,
    TicketEvent,
)
from services.engine.tickets.repository import PostgresTicketRepository, TicketRepository
from services.engine.tickets.state import derived_estimate, validate_transition

router = APIRouter(tags=["tickets"])


def get_ticket_repository() -> TicketRepository:
    return PostgresTicketRepository(DbSettings.from_env())


ThemeRepoDep = Annotated[ThemeRepository, Depends(get_theme_repository)]
BlueprintRepoDep = Annotated[BlueprintRepository, Depends(get_blueprint_repository)]
TicketRepoDep = Annotated[TicketRepository, Depends(get_ticket_repository)]


@router.post("/themes/{theme_id}/tickets/generate", response_model=GenerateResult)
def generate_theme_tickets(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    tickets: TicketRepoDep,
) -> GenerateResult:
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    if theme.status != "approved":
        raise HTTPException(
            status_code=409, detail="approve the blueprint before generating tickets"
        )
    blueprint = blueprints.get_latest(theme_id)
    if blueprint is None:
        raise HTTPException(status_code=409, detail="no blueprint to generate tickets from")
    return generate_tickets(theme_id, blueprint, tickets)


@router.get("/themes/{theme_id}/tickets", response_model=list[Ticket])
def list_theme_tickets(
    theme_id: str,
    themes: ThemeRepoDep,
    tickets: TicketRepoDep,
    status: Annotated[str | None, Query()] = None,
) -> list[Ticket]:
    if themes.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")
    return tickets.list_tickets(theme_id, status)


@router.post("/tickets/{ticket_id}/resolve", response_model=Ticket)
def resolve_ticket(ticket_id: str, req: ResolveRequest, tickets: TicketRepoDep) -> Ticket:
    """Mark a ticket UNRESOLVABLE/DEFERRED with a reason. A "not-disclosed" mark records
    the CVE 10% upper bound; the resolution persists across future ticket generation."""
    ticket = tickets.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    validate_transition(ticket.status, req.status)  # -> 409 on an invalid transition
    estimate = derived_estimate(req.reason_code)
    updated = tickets.set_resolution(
        ticket_id, req.status, req.reason_code.value, current_estimate=estimate
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    tickets.record_event(ticket_id, ticket.status, req.status, req.actor, req.reason_code.value)
    return updated


@router.get("/tickets/{ticket_id}/events", response_model=list[TicketEvent])
def list_ticket_events(ticket_id: str, tickets: TicketRepoDep) -> list[TicketEvent]:
    if tickets.get_ticket(ticket_id) is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return tickets.list_events(ticket_id)
