"""Shared tenant-scoped ownership checks (RF-11).

Every CRUD router repeated the same guard: load a row by primary key, then 404 unless it belongs to
the calling user. These two helpers centralize that so the check (and its semantics) live in one place.
"""

from __future__ import annotations

from fastapi import HTTPException


def check_owned(entity, email: str, detail: str, *, allow_global: bool = False):
    """Return ``entity`` iff it exists and belongs to ``email``; otherwise raise 404.

    With ``allow_global=True`` a global/template row (``user_email is None``) is also visible to
    everyone — the read-path semantics for shared templates."""
    if entity is None or (entity.user_email != email and not (allow_global and entity.user_email is None)):
        raise HTTPException(status_code=404, detail=detail)
    return entity


def get_owned(db, model, ident, email: str, detail: str, *, allow_global: bool = False):
    """Load ``model`` by primary key and ownership-check it — the common load + guard + 404 pattern."""
    return check_owned(db.get(model, ident), email, detail, allow_global=allow_global)
