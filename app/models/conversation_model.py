"""ConversationEntity — a single conversation thread between user and agent."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ConversationEntity(Base, TimestampMixin):
    """A conversation; its `id` doubles as LangGraph `thread_id`."""

    __tablename__ = "conversations"

    __table_args__ = (
        Index("ix_conversations_last_message_at", "last_message_at"),
        Index("ix_conversations_wa_id", "wa_id"),
    )

    # WhatsApp phone id of the lead. UNIQUE → one phone resumes one thread.
    wa_id: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Nueva conversación")
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    messages = relationship(
        "MessageEntity",
        back_populates="conversation",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="MessageEntity.created_at",
    )

    def __repr__(self) -> str:
        return f"ConversationEntity(id={self.id}, title={self.title!r})"