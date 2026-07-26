"""Lead repository — Colsubsidio lead persistence.

Replaces the old name/phone/email `search` stub with the Colsubsidio contract:
`find_by_conversation_id` and `upsert_by_conversation_id` (field-merge +
terminal-status guard). The status guard lives HERE so every writer
(`save_lead`, `classify_lead`, the `scoring` node) inherits it rather than
re-implementing it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.constants import STATUS_DOMAIN, TERMINAL_STATUSES
from app.models.lead_model import LeadColsubsidioEntity
from app.models.repositories.base_repository import BaseRepository


class LeadStatusTransitionError(Exception):
    """Raised when an upsert tries to change a terminal lead status.

    A terminal status (`calificado`/`nutrible`/`no_calificado`) may not
    transition back to `profiling` or to another terminal status. The numeric
    score is still computed/reported; only the status column is locked.
    """

    def __init__(self, conversation_id: uuid.UUID, current: str, attempted: str) -> None:
        super().__init__(
            f"Lead {conversation_id} is in terminal status {current!r}; "
            f"cannot transition to {attempted!r}"
        )
        self.conversation_id = conversation_id
        self.current = current
        self.attempted = attempted


# Keys `upsert_by_conversation_id` ignores as plain columns: they are either
# the natural key (`conversation_id`/`id`) or handled specially (`status`,
# `normalization_notes`).
_PROTECTED_KEYS: frozenset[str] = frozenset(
    {"conversation_id", "id", "status", "normalization_notes", "created_at", "updated_at", "deleted_at"}
)


class LeadRepository(BaseRepository[LeadColsubsidioEntity]):
    """Persistence for Colsubsidio leads."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LeadColsubsidioEntity)

    async def find_by_conversation_id(
        self, conversation_id: uuid.UUID
    ) -> LeadColsubsidioEntity | None:
        """Return the lead row for a conversation, or None."""
        stmt = select(LeadColsubsidioEntity).where(
            LeadColsubsidioEntity.conversation_id == conversation_id,
            LeadColsubsidioEntity.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_by_conversation_id(
        self,
        conversation_id: uuid.UUID,
        fields: dict[str, Any],
    ) -> LeadColsubsidioEntity:
        """Upsert a lead row keyed by conversation_id with field-merge semantics.

        Semantics (matches `save_lead` / `classify_lead` contract):
          * Only keys present in ``fields`` are written; absent keys preserve
            the existing row's values. A key whose value is ``None`` sets the
            column to NULL (callers normalize unrecognized values to None).
          * ``status`` is handled with the terminal-status guard: a row already
            at a terminal status (`calificado`/`nutrible`/`no_calificado`) may
            not change. An out-of-domain status raises ValueError.
          * ``normalization_notes`` is merged (existing list extended with new
            notes, order preserved, duplicates dropped) rather than replaced.
          * ``conversation_id`` / ``id`` / timestamps are ignored if present.

        The caller normalizes enumerated fields to their canonical slugs (via
        ``app.services.domain_normalizer``) BEFORE calling this. Flushes but
        does NOT commit — pair with ``await session.commit()`` at the call site.
        """
        status_in = fields.get("status")
        notes_in = fields.get("normalization_notes")
        column_fields = {
            k: v for k, v in fields.items() if k not in _PROTECTED_KEYS
        }

        existing = await self.find_by_conversation_id(conversation_id)

        if existing is None:
            self._validate_status(status_in)
            kwargs = dict(column_fields)
            if status_in is not None:
                kwargs["status"] = status_in
            if notes_in:
                kwargs["normalization_notes"] = list(notes_in)
            entity = LeadColsubsidioEntity(conversation_id=conversation_id, **kwargs)
            self.session.add(entity)
            await self.session.flush()
            return entity

        # Merge onto an existing row.
        if status_in is not None and status_in != existing.status:
            if existing.status in TERMINAL_STATUSES:
                raise LeadStatusTransitionError(
                    conversation_id, existing.status, str(status_in)
                )
            self._validate_status(status_in)
            existing.status = status_in

        for key, value in column_fields.items():
            if hasattr(existing, key):
                setattr(existing, key, value)

        if notes_in:
            merged: list[str] = list(existing.normalization_notes or [])
            for note in notes_in:
                if note not in merged:
                    merged.append(note)
            existing.normalization_notes = merged

        await self.session.flush()
        return existing

    @staticmethod
    def _validate_status(status: str | None) -> None:
        if status is not None and status not in STATUS_DOMAIN:
            raise ValueError(
                f"status {status!r} is not in the lead status domain {sorted(STATUS_DOMAIN)}"
            )