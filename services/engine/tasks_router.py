"""Task endpoints — list running/recent runs and re-attach to one's live stream."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from services.engine.sse import sse_response
from services.engine.tasks import TaskInfo, tasks

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=list[TaskInfo])
def list_tasks(theme_id: Annotated[str | None, Query()] = None) -> list[TaskInfo]:
    """Running + recent runs (optionally filtered by theme) — what the UI shows as activity."""
    return tasks.list(theme_id)


@router.get("/tasks/{task_id}/stream")
def stream_task(task_id: str) -> StreamingResponse:
    """Re-attach to a run: replay what you missed, then tail live to completion."""
    if tasks.get(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    return sse_response(tasks.subscribe(task_id))
