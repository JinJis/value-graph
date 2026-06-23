"""Logging + request tracing for the control-plane service.

A single LOG_LEVEL (read straight from the environment, so it works regardless of the
pydantic ``env_prefix``) drives verbosity for the app logger, uvicorn, and the request
middleware. Set ``LOG_LEVEL=DEBUG`` for full traces (file:line + funcName, raw model
payloads, per-retry backoff). Without this, ``controlplane.*`` loggers have no level/handler
so INFO/DEBUG never reach ``docker logs`` and best-effort except-blocks go silent.
"""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid

from controlplane.config import settings

_PKG = "controlplane"
_BASE_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DEBUG_FMT = "%(asctime)s %(levelname)-7s %(name)s [%(filename)s:%(lineno)d %(funcName)s]: %(message)s"

logger = logging.getLogger(_PKG)


def _resolve_level() -> int:
    raw = os.environ.get("LOG_LEVEL") or getattr(settings, "log_level", "INFO")
    return getattr(logging, str(raw).upper(), logging.INFO)


def setup_logging() -> None:
    """Install one stdout handler on the root logger at LOG_LEVEL; app + uvicorn follow it."""
    level = _resolve_level()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_DEBUG_FMT if level <= logging.DEBUG else _BASE_FMT, "%H:%M:%S"))
    handler._vg = True  # type: ignore[attr-defined]  # mark so we install exactly once

    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not getattr(h, "_vg", False)]
    root.addHandler(handler)
    root.setLevel(level)

    # app + uvicorn loggers share the root handler at the same level (no duplicate lines).
    for name in (_PKG, "uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []          # use the root handler only (no duplicate lines)
        lg.setLevel(level)
        lg.propagate = True
    # the plain access line is replaced by our richer request middleware → quiet it.
    acc = logging.getLogger("uvicorn.access")
    acc.handlers = []
    acc.setLevel(logging.WARNING)
    acc.propagate = True
    # asyncio DEBUG is selector spam — floor it at INFO even under a global DEBUG.
    logging.getLogger("asyncio").setLevel(max(level, logging.INFO))
    logger.info("logging configured: level=%s service=%s", logging.getLevelName(level), _PKG)


def install_request_logging(app) -> None:
    """Trace every HTTP request: a → line on entry, a ← line with status + duration on exit, a
    short request id to correlate the two, and a full traceback on any unhandled error. At DEBUG
    the entry line also carries the query string."""

    @app.middleware("http")
    async def _trace(request, call_next):  # noqa: ANN001
        rid = uuid.uuid4().hex[:8]
        path = request.url.path
        qs = f"?{request.url.query}" if (request.url.query and logger.isEnabledFor(logging.DEBUG)) else ""
        logger.info("→ %s %s%s rid=%s", request.method, path, qs, rid)
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
        except Exception:
            dt = (time.perf_counter() - t0) * 1000
            logger.exception("✗ %s %s rid=%s after %.1fms — unhandled", request.method, path, rid, dt)
            raise
        dt = (time.perf_counter() - t0) * 1000
        lvl = logging.WARNING if resp.status_code >= 400 else logging.INFO
        logger.log(lvl, "← %s %s %d %.1fms rid=%s", request.method, path, resp.status_code, dt, rid)
        resp.headers["X-Request-ID"] = rid
        return resp
