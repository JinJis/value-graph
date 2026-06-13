"""FastAPI dependencies: API-key auth and market resolution."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Query

from app.config import settings
from app.errors import unauthorized
from app.symbols import Market


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-KEY")] = None,
) -> None:
    """Enforce the X-API-KEY header.

    Disabled entirely when ``AUTH_DISABLED=true``. When no accepted keys are
    configured, any non-empty key is accepted (convenient for local/dev use);
    set ``DATASETS_API_KEYS`` to lock the service down.
    """
    if settings.auth_disabled:
        return
    accepted = settings.accepted_api_keys
    if not x_api_key:
        raise unauthorized()
    if accepted and x_api_key not in accepted:
        raise unauthorized()


MarketParam = Annotated[
    Market,
    Query(description="Market to query: US (default) or KR (KOSPI/KOSDAQ)."),
]

ApiKeyDep = Depends(require_api_key)
