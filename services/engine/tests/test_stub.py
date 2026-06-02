"""Scaffolding smoke test ([M0-REPO-01]) — the engine stub boots cleanly."""

from __future__ import annotations

from services.engine.__main__ import banner, main


def test_engine_banner_mentions_stub_boot() -> None:
    assert "stub boot OK" in banner()


def test_engine_main_runs_without_error() -> None:
    main()
