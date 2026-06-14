"""Studio API app: provisioning, conversations, and the chat BFF (SSE)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from studioapi.agents import connectors_router
from studioapi.agents import router as agents_router
from studioapi.agents import seed_templates
from studioapi.chat import stream_and_persist
from studioapi.db import SessionLocal, init_db
from studioapi.deps import current_user, require_service
from studioapi.models import Conversation, Message, User
from studioapi.prompts import router as prompts_router
from studioapi.prompts import seed_community_prompts
from studioapi.search import router as search_router
from studioapi.watchlists import router as watchlists_router


logger = logging.getLogger(__name__)


async def _rag_ingestion_loop():
    from studioapi.config import settings

    # Wait a few seconds to let other containers boot up first
    await asyncio.sleep(15)
    while True:
        try:
            logger.info("Running periodic RAG ingestion pipeline...")
            from studioapi.rag_pipeline import run_rag_ingestion_pipeline
            summary = await run_rag_ingestion_pipeline()
            logger.info(f"Periodic RAG ingestion finished: {summary}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in periodic RAG ingestion loop: {e}")
        await asyncio.sleep(settings.rag_ingestion_interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_templates()
    seed_community_prompts()
    task = asyncio.create_task(_rag_ingestion_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Studio API", version="0.1.0", lifespan=lifespan)


class ChatIn(BaseModel):
    messages: list[dict]
    conversation_id: str | None = None
    agent_id: str | None = None


@app.get("/health", tags=["Meta"])
async def health() -> dict:
    return {"status": "ok"}


@app.post("/users/ensure", tags=["Users"], dependencies=[Depends(require_service)])
async def users_ensure(user: User = Depends(current_user)) -> dict:
    return {"email": user.email, "tenant_id": user.tenant_id, "project_id": user.project_id}


@app.get("/conversations", tags=["Conversations"], dependencies=[Depends(require_service)])
async def list_conversations(user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        rows = db.execute(
            select(Conversation).where(Conversation.user_email == user.email).order_by(Conversation.created_at.desc())
        ).scalars().all()
        return {"conversations": [{"id": c.id, "title": c.title, "agent_id": c.agent_id} for c in rows]}


@app.get("/conversations/{conversation_id}/messages", tags=["Conversations"], dependencies=[Depends(require_service)])
async def conversation_messages(conversation_id: str, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        rows = db.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
        ).scalars().all()
        return {"messages": [
            {"role": m.role, "content": m.content, "citations": json.loads(m.citations) if m.citations else []}
            for m in rows
        ]}


@app.post("/chat/stream", tags=["Chat"], dependencies=[Depends(require_service)])
async def chat_stream(body: ChatIn, user: User = Depends(current_user)) -> StreamingResponse:
    return StreamingResponse(
        stream_and_persist(user, body.conversation_id, body.messages, body.agent_id),
        media_type="text/event-stream",
    )


@app.post("/ops/rag/ingest", tags=["Ops"], dependencies=[Depends(require_service)])
async def trigger_rag_ingestion() -> dict:
    from studioapi.rag_pipeline import run_rag_ingestion_pipeline
    summary = await run_rag_ingestion_pipeline()
    return {"status": "ok", "summary": summary}


app.include_router(agents_router)
app.include_router(connectors_router)
app.include_router(prompts_router)
app.include_router(watchlists_router)
app.include_router(search_router)
