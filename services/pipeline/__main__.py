"""Stub entrypoint for the ValueGraph Pipeline service.

Boots to a stub so the monorepo scaffolding ([M0-REPO-01]) is verifiably runnable:
`python -m services.pipeline`. Real feed ingestion / triggers / scheduler arrive in M6/M7.
"""

from __future__ import annotations


def banner() -> str:
    """Return the pipeline stub-boot banner."""
    return "ValueGraph Pipeline — stub boot OK ([M0-REPO-01]); ingestion/scheduler land in M6/M7."


def main() -> None:
    """Print the stub-boot banner and exit cleanly."""
    print(banner())


if __name__ == "__main__":
    main()
