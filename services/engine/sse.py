"""Server-Sent Events helper — wrap a progress-event iterator as a streaming response.

Shared by the streaming endpoints (blueprint generation, ticket research). Any error
raised mid-stream is delivered as a final ``error`` event, never a dropped socket, so the
client always sees a clean end-of-stream with a legible cause.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator

from fastapi.responses import StreamingResponse

from services.engine.tasks import Event, tasks


def task_sse(
    *, theme_id: str, kind: str, label: str, factory: Callable[[], Iterator[Event]]
) -> StreamingResponse:
    """Register a long run as a re-attachable task and stream it. The run survives the
    client leaving (it's discoverable via ``GET /tasks`` and resumable via the task
    stream); a run of the same ``(theme_id, kind)`` already in flight is reused."""
    task_id = tasks.start(theme_id=theme_id, kind=kind, label=label, factory=factory)
    return sse_response(tasks.subscribe(task_id))


def sse_response(events: Iterator[dict[str, object]]) -> StreamingResponse:
    """Wrap a progress-event iterator as a Server-Sent Events response.

    Each event dict is serialized as one ``data:`` frame. An exception raised while
    iterating is converted to a final ``{"event": "error", "detail": ...}`` frame.
    """

    def frames() -> Iterator[bytes]:
        try:
            for event in events:
                yield f"data: {json.dumps(event)}\n\n".encode()
        except Exception as exc:  # never crash the stream silently
            err = {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
            yield f"data: {json.dumps(err)}\n\n".encode()

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable proxy buffering so events arrive incrementally (nginx/Next).
            "X-Accel-Buffering": "no",
        },
    )
