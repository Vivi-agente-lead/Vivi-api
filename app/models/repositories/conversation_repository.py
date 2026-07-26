"""Conversation repository — CRUD + message counter increment."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.conversation_model import ConversationEntity
from app.models.repositories.base_repository import BaseRepository


class ConversationRepository(BaseRepository[ConversationEntity]):
    """Persistence for conversations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ConversationEntity)

    async def get_or_404(self, conversation_id: uuid.UUID) -> ConversationEntity:
        entity = await self.get(conversation_id)
        if entity is None:
            raise NotFoundError(f"Conversation {conversation_id} not found")
        return entity

    async def find_by_wa_id(self, wa_id: str) -> ConversationEntity | None:
        """Return the conversation for a WhatsApp phone id, or None."""
        stmt = select(ConversationEntity).where(
            ConversationEntity.wa_id == wa_id,
            ConversationEntity.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def increment_message_counter(
        self,
        conversation_id: uuid.UUID,
        tokens_added: int = 0,
    ) -> None:
        """Atomic bump of message_count, total_tokens_used, last_message_at."""
        stmt = (
            update(ConversationEntity)
            .where(ConversationEntity.id == conversation_id)
            .values(
                message_count=ConversationEntity.message_count + 1,
                total_tokens_used=ConversationEntity.total_tokens_used + tokens_added,
                last_message_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()