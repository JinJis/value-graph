"""Spec-compatible error envelope and exception helpers.

Every error response is ``{"error": ..., "message": ...}`` (the spec's
``ErrorResponse``). Endpoints that are part of the published surface but not yet
backed by a real provider raise ``not_implemented()`` → HTTP 501, so the gap is
honest and visible rather than disguised as empty data.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Shared OpenAPI tag that groups every not-yet-implemented endpoint in /docs so
# they are visually obvious (they all return HTTP 501).
NOT_IMPLEMENTED_TAG = "🚧 Not Implemented (501)"


class APIError(Exception):
    def __init__(self, status_code: int, error: str, message: str) -> None:
        self.status_code = status_code
        self.error = error
        self.message = message
        super().__init__(message)


def bad_request(message: str) -> APIError:
    return APIError(400, "Bad Request", message)


def unauthorized(message: str = "Missing or invalid API key.") -> APIError:
    return APIError(401, "Unauthorized", message)


def payment_required(message: str = "Active subscription required.") -> APIError:
    return APIError(402, "Payment Required", message)


def not_found(message: str) -> APIError:
    return APIError(404, "Not Found", message)


def service_unavailable(message: str) -> APIError:
    return APIError(503, "Service Unavailable", message)


def not_implemented(message: str) -> APIError:
    return APIError(501, "Not Implemented", message)


def upstream_error(provider: str, detail: str) -> APIError:
    """An upstream data source failed. Surfaced as 503 so it is distinguishable
    from a client error or a genuine 404."""
    return APIError(503, "Upstream Error", f"{provider}: {detail}")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _handle_api_error(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error, "message": exc.message},
        )

    @app.exception_handler(ValueError)
    async def _handle_value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "Bad Request", "message": str(exc)},
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Map FastAPI's 422 to the spec's 400 ErrorResponse envelope.
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "query")
        msg = first.get("msg", "Invalid request.")
        return JSONResponse(
            status_code=400,
            content={"error": "Bad Request", "message": f"{loc}: {msg}" if loc else msg},
        )
