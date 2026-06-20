"""MCP server settings.

Configured per tenant in the MCP client (env block): point at the control-plane
gateway and supply that tenant's API key. ``MCP_`` prefix keeps these distinct
from the shared platform env.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MCP_", env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # The control-plane gateway this MCP server calls (entitlements + metering happen there).
    gateway_url: str = "http://127.0.0.1:8010"
    # The tenant's API key (MCP_API_KEY).
    api_key: str = ""
    http_timeout_seconds: float = 30.0


settings = Settings()
