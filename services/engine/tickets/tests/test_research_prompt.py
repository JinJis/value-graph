"""The ticket research prompt carries the ticket + company context and the JSON contract."""

from __future__ import annotations

from datetime import UTC, datetime

from services.engine.blueprint.models import BlueprintCompany
from services.engine.tickets.models import Ticket
from services.engine.tickets.research_prompt import build_ticket_research_prompt


def _ticket(**over: object) -> Ticket:
    now = datetime.now(UTC)
    base: dict[str, object] = {
        "id": "t1",
        "theme_id": "theme-1",
        "target": "NVDA",
        "metric": "revenue by customer",
        "reason": "required data point for NVIDIA (NVDA)",
        "status": "OPEN",
        "reason_code": None,
        "current_estimate": None,
        "created_at": now,
        "updated_at": now,
    }
    base.update(over)
    return Ticket(**base)  # type: ignore[arg-type]


def test_prompt_contains_ticker_metric_and_json_contract() -> None:
    prompt = build_ticket_research_prompt(_ticket())
    assert "NVDA" in prompt
    assert "revenue by customer" in prompt
    # The verdict/output contract the parser depends on.
    assert "verdict" in prompt
    assert "source_url" in prompt
    assert "found" in prompt and "not_disclosed" in prompt


def test_prompt_enriched_with_company_context() -> None:
    company = BlueprintCompany(
        ticker="NVDA",
        name="NVIDIA",
        country="US",
        role="GPU / accelerator designer",
        products=["data-center GPUs"],
    )
    prompt = build_ticket_research_prompt(_ticket(), company)
    assert "NVIDIA" in prompt
    assert "GPU / accelerator designer" in prompt
    assert "data-center GPUs" in prompt


def test_prompt_includes_current_estimate_when_present() -> None:
    prompt = build_ticket_research_prompt(
        _ticket(current_estimate={"upper_bound_pct": 10.0, "basis": "10% rule"})
    )
    assert "upper_bound_pct" in prompt
