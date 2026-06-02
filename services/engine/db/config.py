"""Database connection settings, read from env (see .env.example)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql://valuegraph:valuegraph@localhost:5432/valuegraph"
DEFAULT_NEO4J_URI = "bolt://localhost:7687"
DEFAULT_NEO4J_USER = "neo4j"
DEFAULT_NEO4J_PASSWORD = "valuegraph"


@dataclass(frozen=True, repr=False)
class DbSettings:
    database_url: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DbSettings:
        source: Mapping[str, str] = os.environ if env is None else env
        return cls(
            database_url=source.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            neo4j_uri=source.get("NEO4J_URI", DEFAULT_NEO4J_URI),
            neo4j_user=source.get("NEO4J_USER", DEFAULT_NEO4J_USER),
            neo4j_password=source.get("NEO4J_PASSWORD", DEFAULT_NEO4J_PASSWORD),
        )

    def __repr__(self) -> str:
        # Never expose credentials (database_url embeds the password).
        return (
            f"DbSettings(database_url='***', neo4j_uri={self.neo4j_uri!r}, "
            f"neo4j_user={self.neo4j_user!r}, neo4j_password='***')"
        )
