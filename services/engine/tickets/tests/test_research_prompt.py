"""The batched research prompt carries theme + ticket + company context and the contract."""

from __future__ import annotations

from datetime import UTC, datetime

from services.engine.blueprint.models import BlueprintCompany
from services.engine.themes.models import Theme, ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.tickets.models import Ticket
from services.engine.tickets.research_prompt import build_ticket_research_batch_prompt


def _theme() -> Theme:
    return InMemoryThemeRepository().create_theme(
        ThemeCreate(name="AI Data Centers", description="GPU supply chain", seed_tickers=["NVDA"])
    )


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


def test_prompt_carries_theme_ticket_and_json_contract() -> None:
    prompt = build_ticket_research_batch_prompt(
        _theme(), [("T1", _ticket(), None)], relationship_types=["SUPPLIES"]
    )
    # Theme context.
    assert "AI Data Centers" in prompt
    assert "GPU supply chain" in prompt
    assert "SUPPLIES" in prompt
    # Ticket context + the ref the parser keys on.
    assert "[T1]" in prompt
    assert "NVDA" in prompt
    assert "revenue by customer" in prompt
    # Output contract.
    assert '"ref"' in prompt and "verdict" in prompt and "source_url" in prompt
    assert "found" in prompt and "not_disclosed" in prompt


def test_prompt_enriched_with_company_context() -> None:
    company = BlueprintCompany(
        ticker="NVDA",
        name="NVIDIA",
        country="US",
        role="GPU / accelerator designer",
        products=["data-center GPUs"],
    )
    prompt = build_ticket_research_batch_prompt(_theme(), [("T1", _ticket(), company)])
    assert "NVIDIA" in prompt
    assert "GPU / accelerator designer" in prompt
    assert "data-center GPUs" in prompt


def test_prompt_lists_every_ticket() -> None:
    items = [
        ("T1", _ticket(target="NVDA", metric="revenue by customer"), None),
        ("T2", _ticket(target="TSM", metric="wafer shipments"), None),
    ]
    prompt = build_ticket_research_batch_prompt(_theme(), items)
    assert "[T1]" in prompt and "[T2]" in prompt
    assert "TSM" in prompt and "wafer shipments" in prompt
