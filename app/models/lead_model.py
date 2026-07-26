"""LeadEntity — a real-estate lead profiled by the agent."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LeadEntity(Base, TimestampMixin):
    """A lead captured/profiling by the assistant.

    `conversation_id` is nullable: a lead may be saved mid-conversation or
    later from the dashboard.
    """

    __tablename__ = "leads"

    __table_args__ = (
        Index("ix_leads_status", "status"),
        Index("ix_leads_conversation", "conversation_id"),
    )

    conversation_id: Mapped[str | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)

    budget_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_max: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ["Palermo", "Belgrano", ...]
    preferred_locations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    property_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="new")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"LeadEntity(id={self.id}, name={self.name!r}, status={self.status!r})"