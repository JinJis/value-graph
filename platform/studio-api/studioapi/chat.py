"""Chat: persist the turn, proxy the agent-engine SSE stream, persist the answer.

Re-emits the agent-engine SSE events to the browser unchanged while accumulating
the assistant's text + citations to persist the conversation.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from studioapi.config import settings
from studioapi.db import SessionLocal
from studioapi.models import Conversation, Message, User


def _title(messages: list[dict]) -> str:
    for m in messages:
        if m.get("role") == "user":
            return (m.get("content") or "New chat")[:80]
    return "New chat"


async def stream_and_persist(user: User, conversation_id: str | None, messages: list[dict]) -> AsyncIterator[str]:
    # ensure conversation + persist the latest user message
    with SessionLocal() as db:
        if conversation_id and db.get(Conversation, conversation_id):
            conv_id = conversation_id
        else:
            conv = Conversation(user_email=user.email, title=_title(messages))
            db.add(conv)
            db.commit()
            conv_id = conv.id
        last = messages[-1] if messages else {"role": "user", "content": ""}
        db.add(Message(conversation_id=conv_id, role=last.get("role", "user"), content=last.get("content", "")))
        db.commit()

    text_parts: list[str] = []
    citations: list[dict] = []
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST", f"{settings.agent_engine_url}/agent/chat",
            json={"messages": messages}, headers={"X-API-KEY": user.api_key},
        ) as resp:
            async for line in resp.aiter_lines():
                yield line + "\n"  # re-emit SSE framing (blank lines separate events)
                if line.startswith("data:"):
                    try:
                        ev = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if ev.get("type") == "token":
                        text_parts.append(ev.get("text", ""))
                    elif ev.get("type") == "done":
                        citations = ev.get("citations") or citations

    with SessionLocal() as db:
        db.add(Message(
            conversation_id=conv_id, role="assistant",
            content="".join(text_parts), citations=json.dumps(citations, ensure_ascii=False),
        ))
        db.commit()
    yield f"data: {json.dumps({'type': 'conversation', 'id': conv_id})}\n\n"
