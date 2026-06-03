"""S4: Reconciliation — cluster estimates per edge, propagate constraints, and
DETECT CONFLICTS (flag + ticket, never average). Every output carries an interval,
never a bare point (PRD §6.2 S4).

- Agreeing estimates -> reconciled to a representative point (median, not mean) with
  a [min, max] interval.
- Disagreeing independent estimates -> a `conflict` (point=None, interval=the
  disagreement range) and a ticket — never papered over by averaging.
- Conservation: Σ shares per node > 100% is flagged and down-scaled.
- 10% rule: an undisclosed-bounded value above its upper bound becomes a conflict.
"""

from __future__ import annotations

from statistics import median

from pydantic import BaseModel, Field

from services.engine.tickets.models import TicketCreate
from services.engine.tickets.repository import TicketRepository

CONFLICT_TOL = 0.15  # relative spread above this -> conflict
SINGLE_BAND = 0.10  # single-source interval is value +/- this fraction


class Estimate(BaseModel):
    value: float
    source_id: str
    weight: float = 1.0


class Interval(BaseModel):
    low: float
    high: float


class Reconciled(BaseModel):
    point: float | None  # None on conflict (no trustworthy single value)
    interval: Interval
    status: str  # "reconciled" | "conflict"
    n_sources: int
    sources: list[str] = Field(default_factory=list)
    reason: str | None = None


def reconcile(
    estimates: list[Estimate],
    *,
    conflict_tol: float = CONFLICT_TOL,
    single_band: float = SINGLE_BAND,
) -> Reconciled:
    if not estimates:
        raise ValueError("reconcile() requires at least one estimate")

    values = [e.value for e in estimates]
    sources = [e.source_id for e in estimates]

    if len(estimates) == 1:
        value = values[0]
        band = abs(value) * single_band
        return Reconciled(
            point=value,
            interval=Interval(low=value - band, high=value + band),
            status="reconciled",
            n_sources=1,
            sources=sources,
        )

    low, high = min(values), max(values)
    center = median(values)
    spread = (high - low) / abs(center) if center else (high - low)

    if spread > conflict_tol:
        return Reconciled(
            point=None,  # never average a conflict
            interval=Interval(low=low, high=high),
            status="conflict",
            n_sources=len(estimates),
            sources=sources,
            reason=f"independent estimates disagree (spread {spread:.0%})",
        )

    return Reconciled(
        point=center,
        interval=Interval(low=low, high=high),
        status="reconciled",
        n_sources=len(estimates),
        sources=sources,
    )


class ConservationResult(BaseModel):
    total: float
    ok: bool
    flagged: bool
    scale: float
    scaled: list[float]


def check_conservation(shares: list[float], *, capacity: float = 100.0) -> ConservationResult:
    """Σ of a node's shares must be <= capacity (+ undisclosed remainder)."""
    total = sum(shares)
    if total <= capacity:
        return ConservationResult(
            total=total, ok=True, flagged=False, scale=1.0, scaled=list(shares)
        )
    scale = capacity / total
    return ConservationResult(
        total=total,
        ok=False,
        flagged=True,
        scale=scale,
        scaled=[s * scale for s in shares],
    )


def apply_upper_bound(reconciled: Reconciled, upper_bound: float) -> Reconciled:
    """Cap a reconciled value at a confirmed-undisclosed upper bound (the 10% rule).

    If the reconciled point exceeds the bound it contradicts the confirmed-undisclosed
    mark -> conflict.
    """
    interval = Interval(
        low=min(reconciled.interval.low, upper_bound),
        high=min(reconciled.interval.high, upper_bound),
    )
    if reconciled.point is not None and reconciled.point > upper_bound:
        return reconciled.model_copy(
            update={
                "point": None,
                "interval": interval,
                "status": "conflict",
                "reason": f"exceeds {upper_bound}% upper bound (confirmed-undisclosed)",
            }
        )
    return reconciled.model_copy(update={"interval": interval})


def reconcile_and_ticket(
    estimates: list[Estimate],
    *,
    edge_target: str,
    metric: str,
    theme_id: str | None = None,
    ticket_repo: TicketRepository | None = None,
    conflict_tol: float = CONFLICT_TOL,
    single_band: float = SINGLE_BAND,
) -> Reconciled:
    """Reconcile and, on conflict, open a ticket (never average the disagreement)."""
    result = reconcile(estimates, conflict_tol=conflict_tol, single_band=single_band)
    if result.status == "conflict" and ticket_repo is not None and theme_id is not None:
        ticket_repo.create_open_ticket(
            theme_id,
            TicketCreate(
                target=edge_target,
                metric=f"conflict:{metric}",
                reason=result.reason or "conflicting estimates",
                current_estimate={
                    "interval": result.interval.model_dump(),
                    "sources": result.sources,
                },
            ),
        )
    return result
