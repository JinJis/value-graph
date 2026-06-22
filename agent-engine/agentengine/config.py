"""Agent Engine settings (AGENT_* in the shared platform env)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_", env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # Planner backend: stub (deterministic, dev/CI) | gemini (real LLM)
    llm_backend: str = "stub"
    model: str = "gemini-flash-latest"  # an evergreen alias (2.0/1.5 ids get retired)
    # A light/cheap model that assesses a query's complexity → the step budget (PH-15).
    budget_model: str = "gemini-flash-lite-latest"
    # The control-plane gateway the agent's tools are called through.
    gateway_url: str = "http://127.0.0.1:8010"
    max_steps: int = 8         # base tool-step budget (raised for multi-source tasks, up to the cap)
    max_steps_cap: int = 14    # hard ceiling for the dynamic budget
    http_timeout_seconds: float = 60.0
    # Guardrail: the refuse/allow decision is a JUDGMENT made by the LLM intake
    # (`agent.analyze_task`), not keyword matching (invariant #9). The model scores how
    # confidently the request *asks for* a forecast/advice/target; refuse only at/above this.
    guardrail_threshold: float = 0.6


settings = Settings()
