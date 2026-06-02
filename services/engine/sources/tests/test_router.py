"""[M2-PROC-03] Ticket evidence upload via injected fakes (no DB, temp storage)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.engine.main import app
from services.engine.storage.local import LocalStorage
from services.engine.themes.models import Theme, ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository
from services.engine.themes.router import get_storage
from services.engine.tickets.models import Ticket, TicketCreate
from services.engine.tickets.repository import InMemoryTicketRepository
from services.engine.tickets.router import get_ticket_repository

Ctx = tuple[TestClient, InMemoryThemeRepository, InMemoryTicketRepository]


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[Ctx]:
    themes = InMemoryThemeRepository()
    tickets = InMemoryTicketRepository()
    storage = LocalStorage(tmp_path)
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_ticket_repository] = lambda: tickets
    app.dependency_overrides[get_storage] = lambda: storage
    yield TestClient(app), themes, tickets
    app.dependency_overrides.clear()


def _ticket(
    themes: InMemoryThemeRepository, tickets: InMemoryTicketRepository
) -> tuple[Theme, Ticket]:
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    ticket = tickets.create_open_ticket(
        theme.id, TicketCreate(target="NVDA", metric="revenue")
    )
    assert ticket is not None
    return theme, ticket


def test_upload_file_evidence(ctx: Ctx) -> None:
    client, themes, tickets = ctx
    _, ticket = _ticket(themes, tickets)

    files = {"file": ("filing.pdf", b"%PDF evidence bytes", "application/pdf")}
    data = {"type": "filing", "publisher": "DART", "as_of_date": "2026-03-31"}
    resp = client.post(f"/tickets/{ticket.id}/evidence", files=files, data=data)
    assert resp.status_code == 201, resp.text
    source = resp.json()
    assert source["ticket_id"] == ticket.id  # Source linked to the ticket
    assert source["type"] == "filing"
    assert source["as_of_date"] == "2026-03-31"  # as-of date captured
    assert "storage_key" not in source

    submitted = tickets.get_ticket(ticket.id)
    assert submitted is not None and submitted.status == "SUBMITTED"  # status transition

    content = client.get(source["content_url"])  # file re-openable
    assert content.status_code == 200 and content.content == b"%PDF evidence bytes"

    listed = client.get(f"/tickets/{ticket.id}/sources")
    assert listed.status_code == 200 and len(listed.json()) == 1


def test_upload_url_evidence(ctx: Ctx) -> None:
    client, themes, tickets = ctx
    _, ticket = _ticket(themes, tickets)

    resp = client.post(
        f"/tickets/{ticket.id}/evidence",
        data={"url": "https://dart.fss.or.kr/x", "type": "report"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["url"] == "https://dart.fss.or.kr/x"
    submitted = tickets.get_ticket(ticket.id)
    assert submitted is not None and submitted.status == "SUBMITTED"


def test_evidence_requires_file_or_url(ctx: Ctx) -> None:
    client, themes, tickets = ctx
    _, ticket = _ticket(themes, tickets)
    assert client.post(f"/tickets/{ticket.id}/evidence", data={"type": "report"}).status_code == 400


def test_evidence_missing_ticket_404(ctx: Ctx) -> None:
    client, _, _ = ctx
    files = {"file": ("x.txt", b"x", "text/plain")}
    resp = client.post("/tickets/00000000-0000-0000-0000-000000000000/evidence", files=files)
    assert resp.status_code == 404


def test_list_sources_missing_ticket_404(ctx: Ctx) -> None:
    client, _, _ = ctx
    assert client.get("/tickets/00000000-0000-0000-0000-000000000000/sources").status_code == 404
