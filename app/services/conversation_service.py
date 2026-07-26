"""ConversationService — CRUD persistence for conversations.

Lean collaborator extracted from the reference god class. Owns validating
ownership-equivalent checks (single-tenant: just existence + soft-delete),
soft-delete, and listing.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.conversation_model import ConversationEntity
from app.models.repositories.conversation_repository import ConversationRepository
from app.schemas.conversation_schema import (
    ConversationCreate,
    ConversationUpdate,
)


class ConversationService:
    """Persistence collaborator for conversations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ConversationRepository(session)

    async def create(self, payload: ConversationCreate) -> ConversationEntity:
        entity = ConversationEntity(
            title=payload.title or "Nueva conversación",
        )
        await self.repo.add(entity)
        await self.repo.commit()
        return entity

    async def get_or_404(self, conversation_id: uuid.UUID) -> ConversationEntity:
        return await self.repo.get_or_404(conversation_id)

    async def list(self, *, limit: int = 50, cursor_id: uuid.UUID | None = None) -> list[ConversationEntity]:
        return await self.repo.list(limit=limit, cursor_id=cursor_id)

    async def update(
        self,
        conversation_id: uuid.UUID,
        payload: ConversationUpdate,
    ) -> ConversationEntity:
        entity = await self.repo.get_or_404(conversation_id)
        if payload.title is not None:
            entity.title = payload.title
        await self.repo.commit()
        return entity

    async def soft_delete(self, conversation_id: uuid.UUID) -> bool:
        deleted = await self.repo.soft_delete(conversation_id)
        if not deleted:
            raise NotFoundError(f"Conversation {conversation_id} not found")
        await self.repo.commit()
        return True

    async def get_or_create_by_wa_id(
        self,
        wa_id: str,
        *,
        title: str | None = None,
    ) -> ConversationEntity:
        """Idempotent get-or-create of a conversation keyed by WhatsApp phone id."""
        existing = await self.repo.find_by_wa_id(wa_id)
        if existing is not None:
            return existing
        entity = ConversationEntity(wa_id=wa_id, title=title or "WhatsApp")
        await self.repo.add(entity)
        await self.repo.commit()
        return entity

    async def increment_message_counter(
        self,
        conversation_id: uuid.UUID,
        tokens_added: int = 0,
    ) -> None:
        await self.repo.increment_message_counter(conversation_id, tokens_added=tokens_added)