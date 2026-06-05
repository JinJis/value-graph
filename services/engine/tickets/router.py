"""Ticket generation + listing endpoints (PRD §8.3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.engine.blueprint.models import BlueprintCompany
from services.engine.blueprint.repository import BlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository, get_router
from services.engine.db.config import DbSettings
from services.engine.llm.router import LLMRouter
from services.engine.sse import sse_response
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
from services.engine.tickets.research import research_tickets_events
from services.engine.tickets.state import derived_estimate, validate_transition

router = APIRouter(tags=["tickets"])


def get_ticket_repository() -> TicketRepository:
    return PostgresTicketRepository(DbSettings.from_env())


ThemeRepoDep = Annotated[ThemeRepository, Depends(get_theme_repository)]
BlueprintRepoDep = Annotated[BlueprintRepository, Depends(get_blueprint_repository)]
TicketRepoDep = Annotated[TicketRepository, Depends(get_ticket_repository)]
RouterDep = Annotated[LLMRouter, Depends(get_router)]


class ResearchRequest(BaseModel):
    """Which tickets to resolve with Deep Research (run sequentially)."""

    ticket_ids: list[str]


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


@router.post("/themes/{theme_id}/tickets/research/stream")
def stream_research_tickets(
    theme_id: str,
    req: ResearchRequest,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    tickets: TicketRepoDep,
    llm: RouterDep,
) -> StreamingResponse:
    """Resolve the selected tickets with the Deep Research agent as a live SSE stream.

    Each ticket runs sequentially: the agent searches/reads the live web and either
    proposes a cited answer (persisted for admin review) or the ticket auto-resolves to
    UNRESOLVABLE/DEFERRED. Streams the prompt + report per ticket (like blueprint generate).
    """
    if themes.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")
    blueprint = blueprints.get_latest(theme_id)
    company_by_ticker: dict[str, BlueprintCompany] = (
        {c.ticker: c for c in blueprint.companies} if blueprint is not None else {}
    )
    selected = [
        t
        for ticket_id in req.ticket_ids
        if (t := tickets.get_ticket(ticket_id)) is not None and t.theme_id == theme_id
    ]
    return sse_response(research_tickets_events(selected, company_by_ticker, llm, tickets))


@router.post("/tickets/{ticket_id}/research/dismiss", response_model=Ticket)
def dismiss_ticket_proposal(ticket_id: str, tickets: TicketRepoDep) -> Ticket:
    """Reject a Deep Research proposal — clears it, leaving the ticket's status unchanged."""
    if tickets.get_ticket(ticket_id) is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    updated = tickets.set_research_proposal(ticket_id, None)
    if updated is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return updated


@router.get("/tickets/{ticket_id}/events", response_model=list[TicketEvent])
def list_ticket_events(ticket_id: str, tickets: TicketRepoDep) -> list[TicketEvent]:
    if tickets.get_ticket(ticket_id) is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return tickets.list_events(ticket_id)
