"""Shared test fixtures: a canned, valid blueprint payload (>=30 companies, 5 countries)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from services.engine.themes.models import Theme

_COUNTRIES = ["KR", "US", "JP", "CN", "TW"]


def sample_content(n_companies: int = 32) -> dict[str, Any]:
    companies = [
        {
            "ticker": f"T{i}",
            "name": f"Company {i}",
            "country": _COUNTRIES[i % len(_COUNTRIES)],
            "exchange": "EXCH",
            "role": "supplier",
            "products": ["widget"],
            "required_data_points": ["revenue by customer"],
        }
        for i in range(n_companies)
    ]
    return {"companies": companies, "relationship_types": ["SUPPLIES"], "notes": "sample"}


def sample_json(n_companies: int = 32) -> str:
    return json.dumps(sample_content(n_companies))


def sample_theme(theme_id: str = "theme-1") -> Theme:
    now = datetime.now(UTC)
    return Theme(
        id=theme_id,
        name="AI Data Centers",
        version=1,
        status="draft",
        description="GPUs, HBM, fabs, packaging",
        seed_tickers=["NVDA"],
        published_at=None,
        created_at=now,
        updated_at=now,
    )


class FakeGenerator:
    """TextGenerator that replays canned responses (last one repeats)."""

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses) or [""]
        self.calls = 0

    def generate_text(self, *, model: str, prompt: str) -> str:
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response
