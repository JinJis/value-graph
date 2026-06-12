"""In-process task registry: replay + live tail, dedupe, error, list, endpoints."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator

from fastapi.testclient import TestClient

from services.engine.main import app
from services.engine.tasks import CancelSignal, Event, TaskManager
from services.engine.tasks import tasks as task_singleton


def _wait(pred: Callable[[], bool], timeout: float = 2.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met within timeout")


def _drain(events: Iterator[Event]) -> list[Event]:
    return list(events)


def _kinds(events: list[Event]) -> list[object]:
    return [e["event"] for e in events]


def test_replay_after_done() -> None:
    tm = TaskManager()

    def factory() -> Iterator[Event]:
        yield {"event": "chunk", "text": "a"}
        yield {"event": "done"}

    tid = tm.start(theme_id="t", kind="k", label="K", factory=factory)
    _wait(lambda: (i := tm.get(tid)) is not None and i.status == "done")

    events = _drain(tm.subscribe(tid))
    assert _kinds(events)[0] == "task"  # leading marker
    assert {"event": "chunk", "text": "a"} in events
    assert _kinds(events)[-1] == "done"


def test_live_subscriber_gets_replay_then_live() -> None:
    tm = TaskManager()
    gate = threading.Event()

    def factory() -> Iterator[Event]:
        yield {"event": "chunk", "text": "1"}
        gate.wait(2)
        yield {"event": "chunk", "text": "2"}
        yield {"event": "done"}

    tid = tm.start(theme_id="t", kind="k", label="K", factory=factory)
    _wait(lambda: (i := tm.get(tid)) is not None and i.event_count >= 1)  # "1" buffered

    collected: list[Event] = []
    reader = threading.Thread(target=lambda: collected.extend(tm.subscribe(tid)))
    reader.start()
    time.sleep(0.05)  # let the subscriber replay "1" and start tailing
    gate.set()
    reader.join(2)

    chunks = [e.get("text") for e in collected if e["event"] == "chunk"]
    assert chunks == ["1", "2"]  # replayed "1" + live "2"
    assert _kinds(collected)[-1] == "done"


def test_same_kind_running_is_deduped() -> None:
    tm = TaskManager()
    gate = threading.Event()

    def factory() -> Iterator[Event]:
        yield {"event": "chunk"}
        gate.wait(2)

    a = tm.start(theme_id="t", kind="k", label="K", factory=factory)
    _wait(lambda: (i := tm.get(a)) is not None and i.event_count >= 1)
    b = tm.start(theme_id="t", kind="k", label="K", factory=factory)  # running -> reuse
    assert a == b
    gate.set()
    _wait(lambda: (i := tm.get(a)) is not None and i.status == "done")
    # A different kind starts a fresh task.
    c = tm.start(theme_id="t", kind="other", label="O", factory=lambda: iter([]))
    assert c != a


def test_error_status_and_replays_error() -> None:
    tm = TaskManager()

    def factory() -> Iterator[Event]:
        yield {"event": "chunk"}
        raise RuntimeError("boom")

    tid = tm.start(theme_id="t", kind="k", label="K", factory=factory)
    _wait(lambda: (i := tm.get(tid)) is not None and i.status == "error")
    assert "error" in _kinds(_drain(tm.subscribe(tid)))


def test_cancel_stops_the_worker_and_emits_cancelled() -> None:
    tm = TaskManager()
    gate = threading.Event()
    closed = threading.Event()

    def factory() -> Iterator[Event]:
        try:
            while True:
                yield {"event": "chunk"}
                gate.wait(2)  # block until the test lets the next event through
        finally:
            closed.set()  # GeneratorExit from gen.close() runs this

    tid = tm.start(theme_id="t", kind="k", label="K", factory=factory)
    _wait(lambda: (i := tm.get(tid)) is not None and i.event_count >= 1)

    info = tm.cancel(tid)
    assert info is not None
    gate.set()  # release the worker so it reaches the next cancel check

    _wait(lambda: (i := tm.get(tid)) is not None and i.status == "cancelled")
    assert closed.is_set()  # the underlying generator was closed (stream torn down)
    assert "cancelled" in _kinds(_drain(tm.subscribe(tid)))


def test_cancel_unknown_task_returns_none() -> None:
    assert TaskManager().cancel("nope") is None


def test_soft_stop_lets_a_signal_aware_factory_finish_gracefully() -> None:
    tm = TaskManager()
    seen: list[bool] = []

    def factory(sig: CancelSignal) -> Iterator[Event]:
        # A 1-arg factory receives the CancelSignal; it polls .stopping at a safe boundary.
        yield {"event": "chunk", "text": "batch-1"}
        while not sig.stopping:
            time.sleep(0.01)
        seen.append(True)
        yield {"event": "stopped"}  # graceful end, not a hard cancel
        yield {"event": "done"}

    tid = tm.start(theme_id="t", kind="k", label="K", factory=factory)
    _wait(lambda: (i := tm.get(tid)) is not None and i.event_count >= 1)
    info = tm.cancel(tid, soft=True)  # request a graceful stop
    assert info is not None
    _wait(lambda: (i := tm.get(tid)) is not None and i.status == "done")
    kinds = _kinds(_drain(tm.subscribe(tid)))
    assert seen == [True]  # the factory observed the soft-stop signal
    assert "stopped" in kinds and "done" in kinds
    assert "cancelled" not in kinds  # soft stop is graceful, not a hard cancel


def test_cancelled_kind_is_not_reused() -> None:
    tm = TaskManager()
    gate = threading.Event()

    def factory() -> Iterator[Event]:
        yield {"event": "chunk"}
        gate.wait(2)

    a = tm.start(theme_id="t", kind="k", label="K", factory=factory)
    _wait(lambda: (i := tm.get(a)) is not None and i.event_count >= 1)
    tm.cancel(a)  # request stop (status still RUNNING until the worker reacts)
    b = tm.start(theme_id="t", kind="k", label="K", factory=lambda: iter([]))
    assert b != a  # a cancelling task is not reused — a fresh one starts
    gate.set()


def test_list_filters_by_theme() -> None:
    tm = TaskManager()
    a = tm.start(theme_id="t1", kind="k", label="K", factory=lambda: iter([]))
    _wait(lambda: (i := tm.get(a)) is not None and i.status == "done")
    assert any(i.id == a for i in tm.list("t1"))
    assert all(i.theme_id == "other" for i in tm.list("other"))


def _frames(text: str) -> list[dict[str, object]]:
    return [
        json.loads(line[5:].strip())
        for line in text.splitlines()
        if line.startswith("data:")
    ]


def test_tasks_endpoints_list_and_reattach() -> None:
    tid = task_singleton.start(
        theme_id="ep-theme",
        kind="k",
        label="K",
        factory=lambda: iter([{"event": "chunk"}, {"event": "done"}]),
    )
    _wait(lambda: (i := task_singleton.get(tid)) is not None and i.status == "done")
    client = TestClient(app)

    listed = client.get("/tasks?theme_id=ep-theme").json()
    assert any(t["id"] == tid for t in listed)

    resp = client.get(f"/tasks/{tid}/stream")
    assert resp.status_code == 200
    frames = _frames(resp.text)
    assert frames[0]["event"] == "task" and frames[-1]["event"] == "done"

    assert client.get("/tasks/nope/stream").status_code == 404
