"""Agent Engine settings (AGENT_* in the shared platform env)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_", env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # Model tiering — quality where it's READ, economy where it's MECHANICAL. Override via env.
    # Planner backend: stub (deterministic, dev/CI) | gemini (real LLM)
    llm_backend: str = "stub"
    model: str = "gemini-flash-latest"  # tool-routing / planning model (frequent → flash)
    # A light/cheap model for the first-pass intake: guardrail + budget + plan (+ needs_data).
    budget_model: str = "gemini-flash-lite-latest"
    # The RESPONSE/synthesis model — composes the user-facing final answer (and the A2A combiner
    # + conceptual answers), MIXING sourced facts (cited [n]) with analyst context. This is what
    # the user actually reads, so it runs on the DEEP tier (pro) for quality. One call per turn.
    synthesis_model: str = "gemini-pro-latest"
    # The verify/refine + per-source confidence pass that GROUNDS the synthesis. Defaults to the
    # flash tier (cheap); bump to a pro/reasoning model when you want stricter grounding.
    reasoning_model: str = "gemini-flash-latest"
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
