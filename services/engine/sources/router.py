"""Ticket processing — evidence upload (file or URL) -> Source, ticket -> SUBMITTED."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from graph_schema import SourceType
from services.engine.financials.repository import (
    BUCKET_FIELDS,
    FinancialsRepository,
    set_bucket,
)
from services.engine.financials.router import get_financials_repository
from services.engine.storage import Storage
from services.engine.themes.models import SourceCreate, SourceOut, to_out
from services.engine.themes.repository import ThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository
from services.engine.themes.router import get_storage
from services.engine.tickets.models import Ticket
from services.engine.tickets.repository import TicketRepository
from services.engine.tickets.router import get_ticket_repository
from services.engine.tickets.state import validate_transition

router = APIRouter(tags=["sources"])

ThemeRepoDep = Annotated[ThemeRepository, Depends(get_theme_repository)]
TicketRepoDep = Annotated[TicketRepository, Depends(get_ticket_repository)]
StorageDep = Annotated[Storage, Depends(get_storage)]
FinancialsRepoDep = Annotated[FinancialsRepository, Depends(get_financials_repository)]


def _coerce_number(value: object) -> float | None:
    """Best-effort parse of a proposal value into a number (strips $, commas, spaces).
    Percent values are rejected — financials buckets are absolute amounts, not shares."""
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = value.strip().replace(",", "").replace("$", "").strip()
    if not cleaned or cleaned.endswith("%"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _write_back_financials(ticket: Ticket, financials: FinancialsRepository) -> None:
    """If a ``financials:<bucket>`` ticket carries a Deep Research proposal, fill that
    bucket in the financials store (so accepting a financial ticket isn't manual)."""
    if not ticket.metric.startswith("financials:") or not ticket.research_proposal:
        return
    field = ticket.metric.split(":", 1)[1]
    if field not in BUCKET_FIELDS:
        return
    value = _coerce_number(ticket.research_proposal.get("value"))
    if value is None:
        return
    source = ticket.research_proposal.get("source_url")
    set_bucket(financials, ticket.target, field, value, source=str(source) if source else None)


@router.post("/tickets/{ticket_id}/evidence", response_model=SourceOut, status_code=201)
async def upload_ticket_evidence(
    ticket_id: str,
    themes: ThemeRepoDep,
    tickets: TicketRepoDep,
    storage: StorageDep,
    financials: FinancialsRepoDep,
    file: Annotated[UploadFile | None, File()] = None,
    url: Annotated[str | None, Form()] = None,
    type: Annotated[SourceType, Form()] = "report",
    publisher: Annotated[str | None, Form()] = None,
    as_of_date: Annotated[date | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
    actor: Annotated[str, Form()] = "admin",
) -> SourceOut:
    ticket = tickets.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    if file is None and not url:
        raise HTTPException(status_code=400, detail="provide a file or a url")
    validate_transition(ticket.status, "SUBMITTED")  # -> 409 on an invalid transition

    storage_key: str | None = None
    filename: str | None = None
    content_type: str | None = None
    if file is not None:
        data = await file.read()
        filename = file.filename or "evidence.bin"
        storage_key = f"{ticket.theme_id}/{ticket_id}/{uuid4()}/{filename}"
        storage.save(storage_key, data)
        content_type = file.content_type

    record = themes.add_source(
        ticket.theme_id,
        SourceCreate(
            type=type,
            url=url,
            publisher=publisher,
            as_of_date=as_of_date,
            language=language,
            storage_key=storage_key,
            original_filename=filename,
            content_type=content_type,
        ),
        ticket_id=ticket_id,
    )
    tickets.set_status(ticket_id, "SUBMITTED")
    tickets.record_event(ticket_id, ticket.status, "SUBMITTED", actor, None)
    # A financials:<bucket> proposal fills the financials store on accept (no manual entry).
    _write_back_financials(ticket, financials)
    # Accepting a Deep Research proposal (or any manual upload) clears the pending
    # proposal — the cited source is now real evidence on the ticket.
    tickets.set_research_proposal(ticket_id, None)
    return to_out(record)


@router.get("/tickets/{ticket_id}/sources", response_model=list[SourceOut])
def list_ticket_sources(
    ticket_id: str, themes: ThemeRepoDep, tickets: TicketRepoDep
) -> list[SourceOut]:
    if tickets.get_ticket(ticket_id) is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return [to_out(record) for record in themes.list_sources_for_ticket(ticket_id)]
