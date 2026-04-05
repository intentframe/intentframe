"""Request/response models for the Jarvis API server."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    client: str = Field(
        default="unknown",
        description="Identifies the caller (e.g. 'telegram', 'dashboard', 'cli').",
    )


class ChatResponse(BaseModel):
    response: str
    tokens: int


class StatusResponse(BaseModel):
    ready: bool
    model: str
    session_tokens: int
    heartbeat_enabled: bool
    busy: bool
    current_client: str | None


class SessionResponse(BaseModel):
    messages: list[dict[str, Any]]
    tokens: int
