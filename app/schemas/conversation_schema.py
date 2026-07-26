"""Conversation DTOs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    message_count: int
    last_message_at: datetime | None
    total_tokens_used: int
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ConversationDetailResponse(ConversationResponse):
    """Detail with a slice of the latest messages."""

    messages: list["MessageRef"] = Field(default_factory=list)


class MessageRef(BaseModel):
    """Minimal message reference used inside ConversationDetailResponse."""

    id: UUID
    role: str
    content: str | None = None
    tool_name: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


ConversationDetailResponse.model_rebuild()