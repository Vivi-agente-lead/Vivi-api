"""Message DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant", "tool", "system"]
    content: str | None = None
    tool_calls: dict[str, Any] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    tokens_prompt: int = 0
    tokens_completion: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentTurnResponse(BaseModel):
    """Response for the synchronous send-message endpoint."""

    user_message: MessageResponse
    assistant_message: MessageResponse
    tool_messages: list[MessageResponse] = Field(default_factory=list)