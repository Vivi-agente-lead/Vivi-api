"""Generic async CRUD repository with soft-delete + cursor pagination."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base, TimestampMixin

ModelT = TypeVar("ModelT", bound=Base)
MixinT = TypeVar("MixinT", bound=TimestampMixin)


class BaseRepository(Generic[ModelT]):
    """Generic CRUD + soft-delete + listing for any entity backed by TimestampMixin."""

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    async def get(self, id_: uuid.UUID) -> ModelT | None:
        result = await self.session.execute(
            select(self.model).where(self.model.id == id_, self.model.deleted_at.is_(None))
        )
        return result.scalars().first()

    async def list(
        self,
        *,
        limit: int = 50,
        cursor_id: uuid.UUID | None = None,
        order_by: Any | None = None,
    ) -> list[ModelT]:
        stmt = select(self.model).where(self.model.deleted_at.is_(None))
        if order_by is not None:
            stmt = stmt.order_by(desc(order_by))
        else:
            stmt = stmt.order_by(desc(self.model.created_at))
        if cursor_id is not None:
            cursor_row = await self.session.execute(
                select(self.model.created_at).where(self.model.id == cursor_id)
            )
            cursor_at = cursor_row.scalar_one_or_none()
            if cursor_at is not None:
                stmt = stmt.where(self.model.created_at < cursor_at)
        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def soft_delete(self, id_: uuid.UUID) -> bool:
        entity = await self.get(id_)
        if entity is None:
            return False
        entity.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()
        return True

    async def commit(self) -> None:
        await self.session.commit()