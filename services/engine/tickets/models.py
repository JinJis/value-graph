"""Ticket models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TicketCreate(BaseModel):
    """A required-but-unsourced data point to request."""

    target: str  # company ticker (or, later, an edge id)
    metric: str
    reason: str | None = None
    current_estimate: dict[str, Any] | None = None


class Ticket(BaseModel):
    id: str
    theme_id: str
    target: str
    metric: str
    reason: str | None
    status: str
    reason_code: str | None
    current_estimate: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class GenerateResult(BaseModel):
    created: int
    skipped: int
