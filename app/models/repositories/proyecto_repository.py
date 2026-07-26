"""Proyecto repository — filtered catalogue lookup ordered by (proyecto, modelo)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.proyecto_model import ProyectoColsubsidioEntity
from app.models.repositories.base_repository import BaseRepository
from app.services.domain_normalizer import MUNICIPIO_CATALOGO_REPAIR


class ProyectoColsubsidioRepository(BaseRepository[ProyectoColsubsidioEntity]):
    """Lookup over the 44-row Colsubsidio project catalogue."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ProyectoColsubsidioEntity)

    async def find_filtered(
        self,
        *,
        municipio: str | None = None,
        tipo: str | None = None,
        limit: int = 5,
    ) -> list[ProyectoColsubsidioEntity]:
        """Return up to ``limit`` projects ordered by (proyecto, modelo).

        ``municipio`` is the NORMALIZED catalogue municipio (e.g. ``'Bogota'``),
        never the raw lead-facing option. The corrupt stored value
        ``municipio='VIS'`` (VIBO ONCE B2) is repaired to ``'Bogota'`` at lookup
        time: querying ``municipio='Bogota'`` matches rows whose stored
        ``municipio`` is either ``'Bogota'`` or ``'VIS'``. The stored row keeps
        ``'VIS'`` verbatim.
        """
        stmt = select(ProyectoColsubsidioEntity).where(
            ProyectoColsubsidioEntity.deleted_at.is_(None)
        )
        if municipio is not None:
            # Raw catalogue values that repair to the queried municipio. For
            # 'Bogota' this is {'Bogota', 'VIS'}; for everything else it is
            # {municipio} (the repair map only contains 'VIS' -> 'Bogota').
            raw_candidates = {municipio}
            for raw, repaired in MUNICIPIO_CATALOGO_REPAIR.items():
                if repaired == municipio:
                    raw_candidates.add(raw)
            stmt = stmt.where(ProyectoColsubsidioEntity.municipio.in_(raw_candidates))
        if tipo is not None:
            stmt = stmt.where(ProyectoColsubsidioEntity.tipo == tipo)
        stmt = stmt.order_by(
            ProyectoColsubsidioEntity.proyecto,
            ProyectoColsubsidioEntity.modelo,
        ).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())