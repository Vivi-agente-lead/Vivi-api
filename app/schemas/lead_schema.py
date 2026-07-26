"""Lead DTOs for the read-only dashboard listing."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LeadResponse(BaseModel):
    id: UUID
    conversation_id: UUID | None = None
    name: str
    phone: str | None = None
    email: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    preferred_locations: list[Any] | None = None
    property_type: str | None = None
    status: str
    notes: str | None = None
    score: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class LeadListResponse(BaseModel):
    items: list[LeadResponse] = Field(default_factory=list)
    total: int = 0