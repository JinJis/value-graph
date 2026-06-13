"""Agent Engine request/response models."""

from __future__ import annotations

from pydantic import BaseModel


class AgentSpec(BaseModel):
    """Declarative ('SDK') agent definition a tenant can save and reuse."""

    system: str | None = None
    allowed_tools: list[str] | None = None  # restrict to a subset of activated tools
    max_steps: int | None = None


class RunRequest(BaseModel):
    task: str
    spec: AgentSpec | None = None


class Message(BaseModel):
    role: str  # user | assistant | system
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    spec: AgentSpec | None = None


class CompileRequest(BaseModel):
    description: str


class Citation(BaseModel):
    tool: str
    source: str | None = None
    url: str | None = None


class Step(BaseModel):
    tool: str
    args: dict
    status: int


class RunResult(BaseModel):
    answer: str
    refused: bool = False
    steps: list[Step] = []
    citations: list[Citation] = []
    usage: dict = {}
