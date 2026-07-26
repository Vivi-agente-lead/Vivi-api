"""Message repository — list by conversation (cursor) + last-N history."""

from __future__ import annotations

import uuid

from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message_model import MessageEntity
from app.models.repositories.base_repository import BaseRepository


class MessageRepository(BaseRepository[MessageEntity]):
    """Persistence for messages."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MessageEntity)

    async def list_by_conversation(
        self,
        conversation_id: uuid.UUID,
        *,
        limit: int = 100,
        before_id: uuid.UUID | None = None,
        order: str = "asc",
    ) -> list[MessageEntity]:
        """Cursor-paginated message listing for a conversation."""
        filters = [
            MessageEntity.conversation_id == conversation_id,
            MessageEntity.deleted_at.is_(None),
        ]
        if before_id is not None:
            sub = select(MessageEntity.created_at).where(MessageEntity.id == before_id).scalar_subquery()
            filters.append(MessageEntity.created_at < sub)

        order_func = desc if order == "desc" else asc
        stmt = (
            select(MessageEntity)
            .where(*filters)
            .order_by(order_func(MessageEntity.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def recent_history(
        self,
        conversation_id: uuid.UUID,
        *,
        limit: int,
    ) -> list[MessageEntity]:
        """Last N messages in chronological order (oldest first)."""
        recent = await self.list_by_conversation(
            conversation_id, limit=limit, order="desc"
        )
        return list(reversed(recent))

    async def find_by_external_id(self, external_id: str) -> MessageEntity | None:
        stmt = select(MessageEntity).where(MessageEntity.external_id == external_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()