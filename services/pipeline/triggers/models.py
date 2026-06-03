"""[M7-TRIG-03] CVE job models — a unit of scoped re-ingest + CVE work."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# Job lifecycle (mirrors the jobs.status convention).
PENDING = "PENDING"
RUNNING = "RUNNING"
DONE = "DONE"
FAILED = "FAILED"


class CveJobCreate(BaseModel):
    theme_id: str
    company: str  # the tracked company whose new filing triggered this
    trigger: str = "new_evidence"  # one of pipeline TRIGGERS
    reason: str | None = None
    affected_edges: list[str] = Field(default_factory=list)  # "supplier->customer" scope


class CveJob(BaseModel):
    id: str
    theme_id: str
    company: str
    trigger: str
    reason: str | None
    affected_edges: list[str]
    status: str
    created_at: datetime
    updated_at: datetime

    def payload(self) -> dict[str, Any]:
        return {
            "company": self.company,
            "trigger": self.trigger,
            "reason": self.reason,
            "affected_edges": self.affected_edges,
        }
