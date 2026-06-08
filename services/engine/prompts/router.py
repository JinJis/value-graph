"""Admin API for editing prompt templates.

Lists every registered prompt with its built-in default and current override, and lets the
admin set/reset an override (persisted in Postgres + applied to the live in-process registry,
so the next LLM/Deep Research call uses the edited text). Keys are fixed by the code that
registers them; you can only edit the text of an existing key, never invent new ones.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.engine.db.config import DbSettings
from services.engine.prompts import registry
from services.engine.prompts.repository import (
    PostgresPromptOverrideRepository,
    PromptOverrideRepository,
)

router = APIRouter(tags=["prompts"])


def get_prompt_repository() -> PromptOverrideRepository:
    return PostgresPromptOverrideRepository(DbSettings.from_env())


RepoDep = Annotated[PromptOverrideRepository, Depends(get_prompt_repository)]


class PromptItem(BaseModel):
    key: str
    title: str
    description: str
    default: str
    override: str | None  # the admin-set text, or null when using the default
    effective: str  # what the engine actually uses (override or default)
    is_overridden: bool


class PromptUpdate(BaseModel):
    text: str


def _item(key: str, override: str | None) -> PromptItem:
    spec = registry.spec(key)
    assert spec is not None
    return PromptItem(
        key=spec.key,
        title=spec.title,
        description=spec.description,
        default=spec.default,
        override=override,
        effective=override if override is not None else spec.default,
        is_overridden=override is not None,
    )


@router.get("/prompts", response_model=list[PromptItem])
def list_prompts(repo: RepoDep) -> list[PromptItem]:
    """Every registered prompt with its default + current override."""
    overrides = repo.all()
    return [_item(spec.key, overrides.get(spec.key)) for spec in registry.specs()]


@router.get("/prompts/{key}", response_model=PromptItem)
def get_prompt(key: str, repo: RepoDep) -> PromptItem:
    if not registry.has(key):
        raise HTTPException(status_code=404, detail=f"unknown prompt {key!r}")
    return _item(key, repo.get(key))


@router.put("/prompts/{key}", response_model=PromptItem)
def set_prompt(key: str, update: PromptUpdate, repo: RepoDep) -> PromptItem:
    """Override a prompt's text (persisted + applied to the live registry)."""
    if not registry.has(key):
        raise HTTPException(status_code=404, detail=f"unknown prompt {key!r}")
    if not update.text.strip():
        raise HTTPException(status_code=400, detail="prompt text cannot be empty")
    repo.set(key, update.text)
    registry.apply_override(key, update.text)
    return _item(key, update.text)


@router.delete("/prompts/{key}", response_model=PromptItem)
def reset_prompt(key: str, repo: RepoDep) -> PromptItem:
    """Drop the override and revert to the built-in default."""
    if not registry.has(key):
        raise HTTPException(status_code=404, detail=f"unknown prompt {key!r}")
    repo.delete(key)
    registry.clear_override(key)
    return _item(key, None)


def hydrate_registry(repo: PromptOverrideRepository) -> int:
    """Load persisted overrides into the in-process registry (called at startup)."""
    overrides = repo.all()
    registry.load_overrides(overrides)
    return len(overrides)
