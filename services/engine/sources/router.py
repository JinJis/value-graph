"""Ticket processing — evidence upload (file or URL) -> Source, ticket -> SUBMITTED."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from graph_schema import SourceType
from services.engine.storage import Storage
from services.engine.themes.models import SourceCreate, SourceOut, to_out
from services.engine.themes.repository import ThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository
from services.engine.themes.router import get_storage
from services.engine.tickets.repository import TicketRepository
from services.engine.tickets.router import get_ticket_repository
from services.engine.tickets.state import validate_transition

router = APIRouter(tags=["sources"])

ThemeRepoDep = Annotated[ThemeRepository, Depends(get_theme_repository)]
TicketRepoDep = Annotated[TicketRepository, Depends(get_ticket_repository)]
StorageDep = Annotated[Storage, Depends(get_storage)]


@router.post("/tickets/{ticket_id}/evidence", response_model=SourceOut, status_code=201)
async def upload_ticket_evidence(
    ticket_id: str,
    themes: ThemeRepoDep,
    tickets: TicketRepoDep,
    storage: StorageDep,
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
    return to_out(record)


@router.get("/tickets/{ticket_id}/sources", response_model=list[SourceOut])
def list_ticket_sources(
    ticket_id: str, themes: ThemeRepoDep, tickets: TicketRepoDep
) -> list[SourceOut]:
    if tickets.get_ticket(ticket_id) is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return [to_out(record) for record in themes.list_sources_for_ticket(ticket_id)]
