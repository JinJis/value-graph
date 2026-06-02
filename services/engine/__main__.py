"""Stub entrypoint for the ValueGraph Engine service.

The real FastAPI app arrives in [M0-API-05]. For now this boots to a stub so the
monorepo scaffolding ([M0-REPO-01]) is verifiably runnable: `python -m services.engine`.
"""

from __future__ import annotations


def banner() -> str:
    """Return the engine stub-boot banner."""
    return "ValueGraph Engine — stub boot OK ([M0-REPO-01]); FastAPI app lands in [M0-API-05]."


def main() -> None:
    """Print the stub-boot banner and exit cleanly."""
    print(banner())


if __name__ == "__main__":
    main()
