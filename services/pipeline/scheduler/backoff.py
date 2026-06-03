"""[M7-SCHED-04] Exponential backoff for job retries."""

from __future__ import annotations


def backoff_delay(
    attempt: int, *, base_s: int = 60, factor: float = 2.0, max_s: int = 3600
) -> int:
    """Seconds to wait before retry ``attempt`` (1-based): base * factor^(attempt-1), capped."""
    if attempt <= 1:
        return base_s
    return int(min(base_s * (factor ** (attempt - 1)), max_s))
