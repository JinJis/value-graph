"""[M0-DB-06] Pure migration planning — ordering and idempotency, no database."""

from __future__ import annotations

from pathlib import Path

from services.engine.db.planning import Migration, discover, plan, split_statements


def _write(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body, encoding="utf-8")


def test_discover_orders_by_version(tmp_path: Path) -> None:
    _write(tmp_path, "0002_second.sql", "SELECT 2;")
    _write(tmp_path, "0001_first.sql", "SELECT 1;")
    _write(tmp_path, "ignore.txt", "nope")
    discovered = discover(tmp_path, "*.sql")
    assert [m.version for m in discovered] == ["0001_first", "0002_second"]
    assert discovered[0].body == "SELECT 1;"


def test_plan_skips_applied_and_is_idempotent(tmp_path: Path) -> None:
    _write(tmp_path, "0001_a.sql", "SELECT 1;")
    _write(tmp_path, "0002_b.sql", "SELECT 2;")
    discovered = discover(tmp_path, "*.sql")

    # Nothing applied yet -> both pending, in order.
    assert [m.version for m in plan(discovered, set())] == ["0001_a", "0002_b"]
    # One applied -> only the other pending.
    assert [m.version for m in plan(discovered, {"0001_a"})] == ["0002_b"]
    # All applied -> empty (a re-run is a no-op).
    assert plan(discovered, {"0001_a", "0002_b"}) == []


def test_split_statements_strips_comments_and_blanks() -> None:
    body = (
        "-- a comment\n"
        "CREATE TABLE t (id int);\n"
        "\n"
        "// cypher-style comment\n"
        "CREATE INDEX ix ON t (id);\n"
    )
    statements = split_statements(body)
    assert statements == ["CREATE TABLE t (id int)", "CREATE INDEX ix ON t (id)"]


def test_migration_is_frozen() -> None:
    migration = Migration(version="0001", path=Path("x.sql"), body="SELECT 1;")
    assert migration.version == "0001"
