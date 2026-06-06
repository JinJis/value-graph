"""Run a streaming event-generator detached from the HTTP request.

Long Gemini runs (Deep Research takes minutes) must NOT die when the admin closes the
browser tab or navigates away. The agent work AND its DB persistence happen as a side
effect of iterating the event generator, so we iterate it to completion in a daemon
thread and merely *tail* the events to the current SSE client. If the client
disconnects, the thread keeps running and persisting; reloading shows the result.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterator

logger = logging.getLogger("valuegraph.engine.background")

Event = dict[str, object]


def run_detached(
    factory: Callable[[], Iterator[Event]], *, label: str
) -> Iterator[Event]:
    """Iterate ``factory()`` in a daemon thread and yield its events to the caller.

    The thread runs to completion (so all persistence happens) regardless of whether
    the caller keeps consuming — a disconnected client only stops the tailing, never
    the run. ``label`` is used in logs to identify the run.
    """
    events: queue.Queue[Event | None] = queue.Queue()  # None is the end sentinel

    def worker() -> None:
        produced = 0
        logger.info("run.start label=%s (detached; survives client disconnect)", label)
        try:
            for event in factory():
                produced += 1
                events.put(event)
        except Exception as exc:  # never lose the cause
            logger.exception("run.error label=%s: %s", label, exc)
            events.put({"event": "error", "detail": f"{type(exc).__name__}: {exc}"})
        finally:
            events.put(None)
            logger.info("run.done label=%s events=%d (persisted)", label, produced)

    threading.Thread(target=worker, name=f"detached:{label}", daemon=True).start()

    def tail() -> Iterator[Event]:
        try:
            while True:
                event = events.get()
                if event is None:  # worker finished
                    return
                yield event
        except GeneratorExit:
            # Client detached (tab closed / navigated away). The worker thread keeps
            # running to completion; we just stop tailing.
            logger.info("run.detach label=%s: client gone, run continues server-side", label)
            raise

    return tail()
