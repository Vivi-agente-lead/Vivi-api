"""Afiliado repository — lookup by (tipo_documento, numero_documento)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.afiliado_model import AfiliadoColsubsidioEntity
from app.models.repositories.base_repository import BaseRepository


class AfiliadoColsubsidioRepository(BaseRepository[AfiliadoColsubsidioEntity]):
    """Persistence/lookup for Colsubsidio affiliates.

    `find_by_doc(tipo_documento, numero_documento)` queries the composite-key
    pair exactly; it accepts any document slug the caller passes (the source
    domain is CC/CE/PA/PEP/PPT for leads; the affiliate table also tolerates
    NIT/CD where Colsubsidio records them). The repository does NOT restrict
    the slug set — the tool layer validates it.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AfiliadoColsubsidioEntity)

    async def find_by_doc(
        self, tipo_documento: str, numero_documento: str
    ) -> AfiliadoColsubsidioEntity | None:
        """Return the afiliado for a (tipo_documento, numero_documento) pair, or None."""
        stmt = select(AfiliadoColsubsidioEntity).where(
            AfiliadoColsubsidioEntity.tipo_documento == tipo_documento,
            AfiliadoColsubsidioEntity.numero_documento == numero_documento,
            AfiliadoColsubsidioEntity.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()