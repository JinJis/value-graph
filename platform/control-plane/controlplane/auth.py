"""API-key generation, hashing, and resolution.

Keys look like ``vgk_<prefix>_<secret>``. Only the SHA-256 of the full key is
stored; the plaintext is shown to the tenant exactly once at creation.
"""

from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select

from controlplane.models import ApiKey

_PREFIX = "vgk"


def _hash(full_key: str) -> str:
    return hashlib.sha256(full_key.encode()).hexdigest()


def generate_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, key_hash). Persist prefix + key_hash, show full once."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(24)
    full = f"{_PREFIX}_{prefix}_{secret}"
    return full, prefix, _hash(full)


def resolve_key(db, full_key: str | None) -> ApiKey | None:
    if not full_key or not full_key.startswith(f"{_PREFIX}_"):
        return None
    parts = full_key.split("_")
    if len(parts) < 3:
        return None
    prefix = parts[1]
    row = db.execute(select(ApiKey).where(ApiKey.prefix == prefix)).scalar_one_or_none()
    if row is None or not row.active:
        return None
    if not secrets.compare_digest(row.key_hash, _hash(full_key)):
        return None
    return row
