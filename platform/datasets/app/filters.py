"""report_period filtering shared by the financial-statement endpoints.

``ReportPeriodFilters`` is a FastAPI dependency exposing the spec's
report_period / _gte / _lte / _gt / _lt query params; ``apply`` filters a list of
statement models (whose ``report_period`` is a date) by those bounds.
"""

from __future__ import annotations

from datetime import date

from fastapi import Query

# When any report_period filter is set we fetch a wider window from the provider
# before filtering, so the user's `limit` applies to the *filtered* result.
WIDE_FETCH = 40


class ReportPeriodFilters:
    def __init__(
        self,
        report_period: date | None = Query(None, description="Exact report period (YYYY-MM-DD)."),
        report_period_gte: date | None = Query(None),
        report_period_lte: date | None = Query(None),
        report_period_gt: date | None = Query(None),
        report_period_lt: date | None = Query(None),
    ) -> None:
        self.eq = report_period
        self.gte = report_period_gte
        self.lte = report_period_lte
        self.gt = report_period_gt
        self.lt = report_period_lt

    @property
    def active(self) -> bool:
        return any(v is not None for v in (self.eq, self.gte, self.lte, self.gt, self.lt))

    def _keep(self, rp) -> bool:
        if rp is None:
            return False
        d = rp if isinstance(rp, date) else _parse(rp)
        if d is None:
            return False
        if self.eq and d != self.eq:
            return False
        if self.gte and d < self.gte:
            return False
        if self.lte and d > self.lte:
            return False
        if self.gt and d <= self.gt:
            return False
        if self.lt and d >= self.lt:
            return False
        return True

    def apply(self, rows: list, limit: int) -> list:
        if self.active:
            rows = [r for r in rows if self._keep(getattr(r, "report_period", None))]
        return rows[:limit]

    def fetch_limit(self, limit: int) -> int:
        return max(limit, WIDE_FETCH) if self.active else limit


def _parse(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
