"""In-process registry of long-running streamed jobs (Gemini runs).

Long jobs (blueprint generation, ticket/financials research, CVE build) stream progress
over SSE. They already run detached from the request (a daemon thread to completion), but
the UI used to lose all visibility on navigate-away. The :class:`TaskManager` makes a run
DISCOVERABLE and RE-ATTACHABLE: it buffers every event and fans out to any number of
subscribers, so a client can list running tasks and resume one (replaying what it missed,
then tailing live).

In-process only (tasks live with the daemon threads that produce them). Results still
persist in their stores regardless; this only governs the live view.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel

logger = logging.getLogger("valuegraph.engine.tasks")

Event = dict[str, object]

RUNNING = "running"
DONE = "done"
ERROR = "error"
CANCELLED = "cancelled"

# How many finished tasks to keep around (so a returning admin still sees recent results).
_MAX_FINISHED = 50


class TaskInfo(BaseModel):
    """A run's metadata for the task list (no event payloads)."""

    id: str
    theme_id: str
    kind: str
    label: str
    status: str
    created_at: datetime
    updated_at: datetime
    event_count: int


class _Task:
    def __init__(self, theme_id: str, kind: str, label: str) -> None:
        self.id = str(uuid4())
        self.theme_id = theme_id
        self.kind = kind
        self.label = label
        self.status = RUNNING
        now = datetime.now(UTC)
        self.created_at = now
        self.updated_at = now
        self.events: list[Event] = []
        self._subscribers: set[queue.Queue[Event | None]] = set()
        self._lock = threading.Lock()
        self._cancel = threading.Event()  # set by an admin "stop"; worker checks between events

    def cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def info(self) -> TaskInfo:
        with self._lock:
            return TaskInfo(
                id=self.id,
                theme_id=self.theme_id,
                kind=self.kind,
                label=self.label,
                status=self.status,
                created_at=self.created_at,
                updated_at=self.updated_at,
                event_count=len(self.events),
            )

    def publish(self, event: Event) -> None:
        with self._lock:
            self.events.append(event)
            self.updated_at = datetime.now(UTC)
            for sub in self._subscribers:
                sub.put(event)

    def finish(self, status: str) -> None:
        with self._lock:
            self.status = status
            self.updated_at = datetime.now(UTC)
            for sub in self._subscribers:
                sub.put(None)  # end sentinel

    def subscribe(self) -> Iterator[Event]:
        """Replay buffered events, then tail live until the task finishes."""
        sub: queue.Queue[Event | None] = queue.Queue()
        with self._lock:
            replay = list(self.events)  # snapshot + register atomically (no missed events)
            finished = self.status != RUNNING
            if not finished:
                self._subscribers.add(sub)
        # Leading marker so the client knows which task it is attached to.
        yield {"event": "task", "task_id": self.id, "kind": self.kind, "status": self.status}
        yield from replay
        if finished:
            return
        try:
            while True:
                event = sub.get()
                if event is None:
                    return
                yield event
        finally:
            with self._lock:
                self._subscribers.discard(sub)


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, _Task] = {}
        self._lock = threading.Lock()

    def _running_for(self, theme_id: str, kind: str) -> _Task | None:
        return next(
            (
                t
                for t in self._tasks.values()
                if t.theme_id == theme_id
                and t.kind == kind
                and t.status == RUNNING
                and not t.is_cancelled()  # a cancelling task isn't reusable — start fresh
            ),
            None,
        )

    def _prune(self) -> None:
        finished = [t for t in self._tasks.values() if t.status != RUNNING]
        if len(finished) <= _MAX_FINISHED:
            return
        finished.sort(key=lambda t: t.updated_at)
        for old in finished[: len(finished) - _MAX_FINISHED]:
            self._tasks.pop(old.id, None)

    def start(
        self,
        *,
        theme_id: str,
        kind: str,
        label: str,
        factory: Callable[[], Iterator[Event]],
    ) -> str:
        """Start (or reuse) a run for ``(theme_id, kind)`` and return its task id.

        A run of the same kind already in flight for the theme is reused — no duplicate
        Gemini spend; new subscribers just attach to it.
        """
        with self._lock:
            existing = self._running_for(theme_id, kind)
            if existing is not None:
                logger.info("task.reuse kind=%s theme=%s id=%s", kind, theme_id, existing.id)
                return existing.id
            task = _Task(theme_id, kind, label)
            self._tasks[task.id] = task
            self._prune()

        def worker() -> None:
            logger.info("task.start kind=%s theme=%s id=%s", kind, theme_id, task.id)
            gen = factory()
            try:
                for event in gen:
                    if task.is_cancelled():
                        # Stop the underlying Gemini/Deep-Research stream and bail out.
                        close = getattr(gen, "close", None)
                        if close is not None:
                            try:
                                close()  # raises GeneratorExit inside for cleanup
                            except Exception:  # pragma: no cover - defensive
                                pass
                        task.publish({"event": "cancelled", "detail": "stopped by admin"})
                        task.finish(CANCELLED)
                        logger.info("task.cancelled kind=%s id=%s", kind, task.id)
                        return
                    task.publish(event)
            except Exception as exc:  # never lose the cause
                logger.exception("task.error kind=%s id=%s: %s", kind, task.id, exc)
                task.publish({"event": "error", "detail": f"{type(exc).__name__}: {exc}"})
                task.finish(ERROR)
                return
            task.finish(DONE)
            logger.info("task.done kind=%s id=%s events=%d", kind, task.id, len(task.events))

        threading.Thread(target=worker, name=f"task:{kind}:{task.id}", daemon=True).start()
        return task.id

    def subscribe(self, task_id: str) -> Iterator[Event]:
        task = self._tasks.get(task_id)
        if task is None:
            yield {"event": "error", "detail": "task not found"}
            return
        yield from task.subscribe()

    def get(self, task_id: str) -> TaskInfo | None:
        task = self._tasks.get(task_id)
        return task.info() if task is not None else None

    def cancel(self, task_id: str) -> TaskInfo | None:
        """Request a running task stop. The worker halts at the next event boundary, closing
        the underlying Gemini stream. Returns the task info, or None if unknown."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.status == RUNNING:
            task.cancel()
            logger.info("task.cancel_requested kind=%s id=%s", task.kind, task_id)
        return task.info()

    def list(self, theme_id: str | None = None) -> list[TaskInfo]:
        with self._lock:
            tasks = [
                t for t in self._tasks.values() if theme_id is None or t.theme_id == theme_id
            ]
        return sorted((t.info() for t in tasks), key=lambda i: i.created_at, reverse=True)


# Process-wide singleton.
tasks = TaskManager()
