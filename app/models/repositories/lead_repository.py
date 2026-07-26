"""Lead repository — CRUD + search stub for lead profiling tools."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_model import LeadEntity
from app.models.repositories.base_repository import BaseRepository


class LeadRepository(BaseRepository[LeadEntity]):
    """Persistence for leads."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LeadEntity)

    async def search(self, query: str | None = None, *, limit: int = 20) -> list[LeadEntity]:
        """Naive substring search over name/phone/email. Stub for hackathon."""
        stmt = select(LeadEntity).where(LeadEntity.deleted_at.is_(None))
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(
                or_(
                    LeadEntity.name.ilike(pattern),
                    LeadEntity.phone.ilike(pattern),
                    LeadEntity.email.ilike(pattern),
                )
            )
        stmt = stmt.order_by(LeadEntity.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_conversation(self, conversation_id: uuid.UUID) -> list[LeadEntity]:
        stmt = (
            select(LeadEntity)
            .where(
                LeadEntity.conversation_id == conversation_id,
                LeadEntity.deleted_at.is_(None),
            )
            .order_by(LeadEntity.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())