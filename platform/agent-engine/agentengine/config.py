"""Agent Engine settings (AGENT_* in the shared platform env)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_", env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # Planner backend: stub (deterministic, dev/CI) | gemini (real LLM)
    llm_backend: str = "stub"
    model: str = "gemini-2.0-flash"
    # The control-plane gateway the agent's tools are called through.
    gateway_url: str = "http://127.0.0.1:8010"
    max_steps: int = 4
    http_timeout_seconds: float = 60.0


settings = Settings()
