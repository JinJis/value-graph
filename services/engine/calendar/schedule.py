"""[M7-CAL-01] Disclosure cadence + next-filing estimation.

A company files on a cadence (annual 10-K / 사업보고서, quarterly 10-Q / 분기보고서,
EDINET, earnings). We LEARN the cadence from filing history (median gap) and project
the next expected filing forward of today. This drives every figure's
`next_expected_update` and the scheduled CVE re-runs (M7-TRIG/SCHED).
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median

# Common cadences (days). Defaults when history is too thin to learn from.
QUARTERLY = 91
ANNUAL = 365


def infer_cadence(history: list[date]) -> int | None:
    """Median gap (days) between consecutive filings; needs >= 2 dated filings."""
    if len(history) < 2:
        return None
    ordered = sorted(history)
    gaps = [(b - a).days for a, b in zip(ordered, ordered[1:], strict=False) if (b - a).days > 0]
    if not gaps:
        return None
    return int(round(median(gaps)))


def cadence_label(cadence_days: int | None) -> str:
    """A human label for a cadence (used in the calendar's fiscal_calendar field)."""
    if cadence_days is None:
        return "unknown"
    if cadence_days <= 0:
        return "unknown"
    if abs(cadence_days - QUARTERLY) <= 20:
        return "quarterly"
    if abs(cadence_days - ANNUAL) <= 40:
        return "annual"
    return f"~{cadence_days}d"


def next_filing(last: date, cadence_days: int, today: date) -> date | None:
    """Project the next filing strictly after ``today`` from ``last`` + cadence."""
    if cadence_days <= 0:
        return None
    candidate = last + timedelta(days=cadence_days)
    while candidate <= today:
        candidate += timedelta(days=cadence_days)
    return candidate


def estimate_next_filing(
    history: list[date],
    *,
    today: date,
    default_cadence_days: int = QUARTERLY,
) -> tuple[date | None, int | None]:
    """Return (next_filing_estimate, cadence_days) learned from filing history.

    Cadence is the median historical gap (or ``default_cadence_days`` when unknown);
    the estimate is the first projected filing after today. Empty history -> (None, cad).
    """
    if not history:
        return None, infer_cadence(history)
    cadence = infer_cadence(history) or default_cadence_days
    return next_filing(max(history), cadence, today), cadence
