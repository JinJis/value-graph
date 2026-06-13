"""Control-plane settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Control-plane store (tenants, keys, activations, usage, audit).
    database_url: str = "sqlite:///./controlplane.db"
    # The data plane this gateway fronts.
    datasets_url: str = "http://127.0.0.1:8000"
    redis_url: str = ""
    # Guards the /admin management endpoints (X-Admin-Token header).
    admin_token: str = "dev-admin-token"
    rate_limit_per_minute: int = 120
    http_timeout_seconds: float = 30.0


settings = Settings()

# Cost units charged per request, by the matched connector's cost tier.
COST_UNITS = {"free": 0, "low": 1, "medium": 5, "high": 20}
