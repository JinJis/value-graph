"""[M7-TRIG-03] New-filing trigger: detect a fresh filing for a tracked company and
enqueue a scoped re-ingest + CVE job.

A filing is "new" when it post-dates the company's last known filing in the disclosure
calendar. On detection we (1) refresh the calendar (new last + recomputed next estimate)
and (2) enqueue a CVE job scoped to that company's edges. The scheduler runs it and the
upgraded data re-enters Staging — the admin still re-publishes (no auto-publish).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from services.engine.calendar.repository import CalendarRepository, upsert_from_history
from services.pipeline.triggers.jobs import JobQueue
from services.pipeline.triggers.models import CveJob, CveJobCreate


def is_new_filing(last_known: date | None, filing_date: date) -> bool:
    """A filing is new iff it post-dates the last known filing (or none is known)."""
    return last_known is None or filing_date > last_known


def affected_edge_keys(edges: list[dict[str, Any]], company: str) -> list[str]:
    """Edges touching ``company`` (as supplier or customer) — the CVE re-run scope."""
    keys = [
        f"{e['supplier']}->{e['customer']}"
        for e in edges
        if e.get("supplier") == company or e.get("customer") == company
    ]
    return sorted(set(keys))


def on_new_filing(
    *,
    theme_id: str,
    company: str,
    filing_date: date,
    history: list[date],
    calendar_repo: CalendarRepository,
    job_queue: JobQueue,
    today: date,
    edges: list[dict[str, Any]] | None = None,
    source: str | None = None,
) -> CveJob | None:
    """Idempotent: returns the enqueued job, or None if the filing isn't newer.

    ``history`` is the company's prior filing dates; ``edges`` (optional, the current
    published/staging edges) scopes the job to the affected relationships.
    """
    entry = calendar_repo.get(company)
    last_known = entry.last_filing_date if entry else (max(history) if history else None)
    if not is_new_filing(last_known, filing_date):
        return None

    # 1) Refresh the disclosure calendar with the new filing.
    new_history = sorted({*history, filing_date})
    upsert_from_history(
        calendar_repo, company, new_history, today=today, source=source or "filing-trigger"
    )

    # 2) Enqueue a CVE job scoped to the company (and its affected edges, if known).
    return job_queue.enqueue(
        CveJobCreate(
            theme_id=theme_id,
            company=company,
            trigger="new_evidence",
            reason=f"new filing {filing_date.isoformat()}",
            affected_edges=affected_edge_keys(edges or [], company),
        )
    )
