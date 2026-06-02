"""Pure migration planning — no database, no I/O beyond reading files.

Kept side-effect-free so the ordering/idempotency logic is unit-testable without a
live database.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    """A single migration file: ``version`` is the filename stem (sorts in order)."""

    version: str
    path: Path
    body: str


def discover(directory: Path, pattern: str) -> list[Migration]:
    """Return migrations in ``directory`` matching ``pattern``, ordered by version."""
    files = sorted(directory.glob(pattern))
    return [
        Migration(version=path.stem, path=path, body=path.read_text(encoding="utf-8"))
        for path in files
    ]


def plan(discovered: list[Migration], applied: set[str]) -> list[Migration]:
    """The migrations not yet applied, in order. Re-running yields ``[]`` (idempotent)."""
    return [migration for migration in discovered if migration.version not in applied]


def split_statements(body: str) -> list[str]:
    """Split a migration file into individual statements (drivers run one at a time).

    Strips line comments (``--`` for SQL, ``//`` for Cypher) and blank lines. v1
    migrations must not contain ``;`` inside a statement body (none do).
    """
    cleaned_lines = [
        line
        for line in body.splitlines()
        if not line.strip().startswith(("--", "//"))
    ]
    cleaned = "\n".join(cleaned_lines)
    return [statement.strip() for statement in cleaned.split(";") if statement.strip()]
