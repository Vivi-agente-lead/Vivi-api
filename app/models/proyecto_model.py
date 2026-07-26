"""ProyectoColsubsidioEntity — the 44-row Colsubsidio project catalogue.

Seeded verbatim by `scripts/seed_colsubsidio.py` from the workbook `Proyectos`
sheet. **`modelo` is `NOT NULL DEFAULT ''`** so the two blank-modelo rows
(`ABETO`, `LA ARBOLEDA`) match the `(proyecto, modelo)` unique key: a nullable
`modelo` would make `ON CONFLICT (proyecto, modelo) DO NOTHING` skip them on the
idempotent re-seed (Postgres treats NULLs as non-conflicting).

Source quirks preserved verbatim: the `VIBO ONCE` `B2` row whose `tipo` and
`municipio` both equal `'VIS'`, the `VERSALLES` `E` row where
`area_privada_m2` (60,6) exceeds `area_construida_m2` (56,29), and the sparse
`ABETO`/`LA ARBOLEDA` rows.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ProyectoColsubsidioEntity(Base, TimestampMixin):
    """A Colsubsidio housing project model row from the catalogue sheet."""

    __tablename__ = "proyectos_colsubsidio"

    __table_args__ = (
        UniqueConstraint("proyecto", "modelo", name="uq_proyecto_modelo"),
        Index("ix_proyecto_municipio_tipo", "municipio", "tipo"),
    )

    proyecto: Mapped[str] = mapped_column(String(100), nullable=False)
    tipo: Mapped[str | None] = mapped_column(String(10), nullable=True)  # VIS | NO VIS | 'VIS' quirk
    municipio: Mapped[str | None] = mapped_column(String(60), nullable=True)  # sometimes 'VIS'
    ubicacion: Mapped[str | None] = mapped_column(String(120), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NOT NULL DEFAULT '': see module docstring — the natural key must match the
    # two blank-modelo rows.
    modelo: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    area_construida_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    area_privada_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    cantidad_habitaciones: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cantidad_banos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valor_vis_smmlv: Mapped[str | None] = mapped_column(String(20), nullable=True)  # '150 SMMLV'

    def __repr__(self) -> str:
        return (
            f"ProyectoColsubsidioEntity(proyecto={self.proyecto!r}, "
            f"modelo={self.modelo!r}, municipio={self.municipio!r})"
        )