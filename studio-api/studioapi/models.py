"""Studio ORM.

`User` maps a Google-authenticated email to its platform tenant/project/key
(held server-side, never sent to the browser). `Conversation`/`Message` store
chat history. `Agent`/`Prompt` back the agent builder + prompt library.
`Watchlist`/`WatchlistItem` are the user's @groups (U1). `Integration` is the
messenger seam (F3).
"""

from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    """A reusable prompt. ``community`` rows (``user_email is None``) are the
    seeded public catalog; a user imports one to get an editable personal copy
    (``source_id`` records where it came from)."""

    __tablename__ = "prompts"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("prm"))
    user_email: Mapped[str | None] = mapped_column(index=True, nullable=True)  # null = community
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(280), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(48), nullable=True)
    community: Mapped[bool] = mapped_column(Boolean, default=False)
    source_id: Mapped[str | None] = mapped_column(String(48), nullable=True)  # imported-from community id
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# --- U1: watchlists / @groups ---------------------------------------------
class Watchlist(Base):
    """A user's named group of companies (the ``@handle`` that chat + the analyst
    builder tag). ``name`` is unique per user and doubles as the @-handle."""

    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_email", "name", name="uq_watchlist_user_name"),)
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("wl"))
    user_email: Mapped[str] = mapped_column(ForeignKey("users.email"), index=True)
    name: Mapped[str] = mapped_column(String(80))  # the @handle, e.g. "반도체바스켓"
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WatchlistItem(Base):
    """One company in a watchlist. A company may belong to many watchlists, so the
    uniqueness is per (watchlist, market, ticker), not global."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "market", "ticker", name="uq_item_watchlist_market_ticker"),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("wli"))
    watchlist_id: Mapped[str] = mapped_column(ForeignKey("watchlists.id"), index=True)
    market: Mapped[str] = mapped_column(String(8))  # US | KR
    ticker: Mapped[str] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Portfolio(Base):
    """A user's named portfolio (CE-8). Holdings carry real share counts + optional cost basis;
    analytics value them live (current price) and backtest the allocation over PriceBar."""

    __tablename__ = "portfolios"
    __table_args__ = (UniqueConstraint("user_email", "name", name="uq_portfolio_user_name"),)
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("pf"))
    user_email: Mapped[str] = mapped_column(ForeignKey("users.email"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Holding(Base):
    """One position in a portfolio — shares of a ticker, with an optional average cost basis."""

    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("portfolio_id", "market", "ticker", name="uq_holding_pf_market_ticker"),)
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("hld"))
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"), index=True)
    market: Mapped[str] = mapped_column(String(8))  # US | KR
    ticker: Mapped[str] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    shares: Mapped[float] = mapped_column(default=0.0)
    cost_basis: Mapped[float | None] = mapped_column(nullable=True)  # avg cost / share
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Board(Base):
    """A named canvas the user pins assets onto (charts, sources, text). Users can keep
    several; pinning offers a board picker. Notion-like free layout per item."""

    __tablename__ = "boards"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("brd"))
    user_email: Mapped[str] = mapped_column(ForeignKey("users.email"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PinnedArtifact(Base):
    """An asset the user pinned to a Board — a live artifact (chart/table), a source/evidence
    card (``spec.kind == 'source'``), or a text block (``spec.kind == 'text'``). ``spec`` is the
    JSON; chart pins are re-fetchable via tool+args (refresh). ``x/y/w/h`` are the Notion-like
    canvas layout (null until placed)."""

    __tablename__ = "pinned_artifacts"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("pin"))
    user_email: Mapped[str] = mapped_column(ForeignKey("users.email"), index=True)
    # which board this asset lives on (nullable for legacy rows → treated as the default board)
    board_id: Mapped[str | None] = mapped_column(ForeignKey("boards.id"), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    spec: Mapped[str] = mapped_column(Text)  # JSON asset spec
    # free-canvas layout (px); null = not yet placed (web auto-flows it)
    x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Integration(Base):
    __tablename__ = "integrations"
    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: _uid("int"))
    user_email: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(24))  # telegram | slack
    config: Mapped[str] = mapped_column(Text)  # JSON (tokens/channels)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
