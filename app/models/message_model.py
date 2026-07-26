"""MessageEntity — a single message in a conversation (user/assistant/tool/system)."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class MessageEntity(Base, TimestampMixin):
    """Persisted chat message. Roles: user | assistant | tool | system."""

    __tablename__ = "messages"

    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    # Meta message id (idempotency: Meta retries the webhook if we don't 200).
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)

    conversation_id: Mapped[str] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tool metadata: { calls: [{id, name, args}], result_preview, ... }
    tool_calls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Free-form observability metadata.
    message_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    tokens_prompt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_completion: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    conversation = relationship(
        "ConversationEntity",
        back_populates="messages",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"MessageEntity(id={self.id}, role={self.role!r})"