"""Studio ORM.

`User` maps a Google-authenticated email to its platform tenant/project/key
(held server-side, never sent to the browser). `Conversation`/`Message` store
chat history. `Agent`/`Prompt`/`Integration` are seams for later phases (F1–F3).
"""

from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from studioapi.db import Base


def _uid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class User(Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(256), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(48))
    project_id: Mapped[str] = mapped_column(String(48))
    api_key: Mapped[str] = mapped_column(String(80))  # the tenant platform key (server-side only)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("cnv"))
    user_email: Mapped[str] = mapped_column(ForeignKey("users.email"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    agent_id: Mapped[str | None] = mapped_column(String(48), nullable=True)  # which agent drove this chat
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# --- F1: configurable agents ----------------------------------------------
class Agent(Base):
    """A configurable agent. ``user_email is None`` marks a provided template
    (a starting point any user can pick or clone). ``data_sources`` is a JSON
    list of connector ids (or full tool names) the agent may use."""

    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("agt"))
    user_email: Mapped[str | None] = mapped_column(index=True, nullable=True)  # null = provided template
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(280), nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="stub")  # stub | gemini
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_sources: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of connector ids
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Prompt(Base):
    __tablename__ = "prompts"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("prm"))
    user_email: Mapped[str | None] = mapped_column(nullable=True)  # null = community
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    community: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Integration(Base):
    __tablename__ = "integrations"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("int"))
    user_email: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(24))  # telegram | slack
    config: Mapped[str] = mapped_column(Text)  # JSON (tokens/channels)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
