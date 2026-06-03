"""[M7-CAL-01] Cadence learning + next-filing projection."""

from __future__ import annotations

from datetime import date

from services.engine.calendar.schedule import (
    ANNUAL,
    QUARTERLY,
    cadence_label,
    estimate_next_filing,
    infer_cadence,
    next_filing,
)


def test_infer_cadence_is_median_gap() -> None:
    history = [date(2025, 1, 1), date(2025, 4, 1), date(2025, 7, 1), date(2025, 10, 1)]
    cadence = infer_cadence(history)
    assert cadence is not None and abs(cadence - QUARTERLY) <= 3


def test_infer_cadence_needs_two_filings() -> None:
    assert infer_cadence([]) is None
    assert infer_cadence([date(2025, 1, 1)]) is None


def test_cadence_label() -> None:
    assert cadence_label(QUARTERLY) == "quarterly"
    assert cadence_label(ANNUAL) == "annual"
    assert cadence_label(200) == "~200d"
    assert cadence_label(None) == "unknown"


def test_next_filing_projects_past_today() -> None:
    # last filing 2026-01-15, quarterly; first projection after 2026-06-01.
    nxt = next_filing(date(2026, 1, 15), QUARTERLY, date(2026, 6, 1))
    assert nxt is not None and nxt > date(2026, 6, 1)
    # 2026-01-15 + 91 = 2026-04-16 (<= today) -> + 91 = 2026-07-16.
    assert nxt == date(2026, 7, 16)


def test_estimate_next_filing_learns_and_projects() -> None:
    history = [date(2025, 5, 15), date(2025, 8, 15), date(2025, 11, 15), date(2026, 2, 15)]
    nxt, cadence = estimate_next_filing(history, today=date(2026, 6, 1))
    assert cadence is not None and abs(cadence - QUARTERLY) <= 5
    assert nxt is not None and nxt > date(2026, 6, 1)


def test_estimate_empty_history() -> None:
    nxt, cadence = estimate_next_filing([], today=date(2026, 6, 1))
    assert nxt is None and cadence is None
