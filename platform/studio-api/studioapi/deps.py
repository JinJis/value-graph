"""Dependencies: trust the first-party web BFF (service token) + resolve the user."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from studioapi.config import settings
from studioapi.models import User
from studioapi.provision import ensure_user


async def require_service(x_service_token: Annotated[str | None, Header(alias="X-Service-Token")] = None) -> None:
    if not x_service_token or x_service_token != settings.service_token:
        raise HTTPException(401, "Invalid service token.")


async def current_user(x_user_email: Annotated[str | None, Header(alias="X-User-Email")] = None) -> User:
    if not x_user_email:
        raise HTTPException(401, "Missing authenticated user.")
    return await ensure_user(x_user_email)


ServiceDep = Depends(require_service)
UserDep = Depends(current_user)
