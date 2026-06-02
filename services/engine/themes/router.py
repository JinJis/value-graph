"""Theme CRUD + Additional-Context upload endpoints (PRD §8.1).

Repository and storage are FastAPI dependencies so tests can inject in-memory /
temp-dir implementations (no database, no real object store).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from graph_schema import SourceType
from services.engine.db.config import DbSettings
from services.engine.storage import Storage, local_storage_from_env
from services.engine.themes.models import (
    SourceCreate,
    SourceOut,
    Theme,
    ThemeCreate,
    to_out,
)
from services.engine.themes.repository import (
    PostgresThemeRepository,
    ThemeRepository,
)

router = APIRouter(tags=["themes"])


def get_repository() -> ThemeRepository:
    return PostgresThemeRepository(DbSettings.from_env())


def get_storage() -> Storage:
    return local_storage_from_env()


RepoDep = Annotated[ThemeRepository, Depends(get_repository)]
StorageDep = Annotated[Storage, Depends(get_storage)]


@router.post("/themes", response_model=Theme, status_code=201)
def create_theme(data: ThemeCreate, repo: RepoDep) -> Theme:
    return repo.create_theme(data)


@router.get("/themes", response_model=list[Theme])
def list_themes(repo: RepoDep) -> list[Theme]:
    return repo.list_themes()


@router.get("/themes/{theme_id}", response_model=Theme)
def get_theme(theme_id: str, repo: RepoDep) -> Theme:
    theme = repo.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    return theme


@router.post("/themes/{theme_id}/sources", response_model=SourceOut, status_code=201)
async def upload_source(
    theme_id: str,
    repo: RepoDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
    type: Annotated[SourceType, Form()] = "report",
    publisher: Annotated[str | None, Form()] = None,
    as_of_date: Annotated[date | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
) -> SourceOut:
    if repo.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")
    data = await file.read()
    filename = file.filename or "upload.bin"
    key = f"{theme_id}/{uuid4()}/{filename}"
    storage.save(key, data)
    record = repo.add_source(
        theme_id,
        SourceCreate(
            type=type,
            publisher=publisher,
            as_of_date=as_of_date,
            language=language,
            storage_key=key,
            original_filename=filename,
            content_type=file.content_type,
        ),
    )
    return to_out(record)


@router.get("/themes/{theme_id}/sources", response_model=list[SourceOut])
def list_sources(theme_id: str, repo: RepoDep) -> list[SourceOut]:
    if repo.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")
    return [to_out(record) for record in repo.list_sources(theme_id)]


@router.get("/sources/{source_id}/content")
def get_source_content(source_id: str, repo: RepoDep, storage: StorageDep) -> Response:
    record = repo.get_source(source_id)
    if record is None or record.storage_key is None:
        raise HTTPException(status_code=404, detail="source content not found")
    data = storage.load(record.storage_key)
    return Response(
        content=data,
        media_type=record.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{record.original_filename or source_id}"'
        },
    )
