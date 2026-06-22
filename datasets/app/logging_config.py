"""Logging setup for the datasets service.

Without this, `app.*` module loggers have no handler/level, so INFO never reaches
`docker logs` and the many best-effort `except` blocks swallow failures silently. This
configures the `app` logger to emit at LOG_LEVEL (default INFO) to stdout with a clear
timestamp · level · module · message format, so the pipeline (ingest, evidence, …) is
observable.
"""

from __future__ import annotations

import logging
import sys

from app.config import settings

_FMT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    if not any(getattr(h, "_vg", False) for h in app_logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FMT, "%H:%M:%S"))
        handler._vg = True  # type: ignore[attr-defined]  # mark so we don't double-add
        app_logger.addHandler(handler)
    app_logger.propagate = False  # avoid duplicate lines via the root/uvicorn handler
