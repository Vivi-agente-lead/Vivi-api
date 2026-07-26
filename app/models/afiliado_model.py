"""AfiliadoColsubsidioEntity — a Colsubsidio affiliate row.

Fabricated seed rows live in `scripts/seed_colsubsidio.py` (the source workbook
has zero afiliado data rows). `fecha_nacimiento` is a real `Date` so edad is
derived server-side, never from LLM-supplied string parsing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AfiliadoColsubsidioEntity(Base, TimestampMixin):
    """A Colsubsidio affiliate, looked up by (tipo_documento, numero_documento)."""

    __tablename__ = "afiliados_colsubsidio"

    __table_args__ = (
        UniqueConstraint("tipo_documento", "numero_documento", name="uq_afiliado_doc"),
        Index("ix_afiliado_numero", "numero_documento"),
        Index("ix_afiliado_categoria", "categoria_afiliado"),
        Index("ix_afiliado_score", "score_credito"),
    )

    tipo_documento: Mapped[str] = mapped_column(String(8), nullable=False)
    numero_documento: Mapped[str] = mapped_column(String(50), nullable=False)
    nombre_apellido: Mapped[str] = mapped_column(String(200), nullable=False)
    fecha_nacimiento: Mapped[date] = mapped_column(Date, nullable=False)
    estado_civil: Mapped[str | None] = mapped_column(String(20), nullable=True)
    salario_base_cotizacion: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    # `categoria` is the salary categoria label; `categoria_afiliado` (A/B/C) is
    # the scorer's Bucket-2 input. They are distinct columns.
    categoria: Mapped[str | None] = mapped_column(String(20), nullable=True)
    categoria_afiliado: Mapped[str] = mapped_column(String(1), nullable=False)
    score_credito: Mapped[int] = mapped_column(Integer, nullable=False)  # 150-950
    ha_recibido_subsidio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_seed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return (
            f"AfiliadoColsubsidioEntity(numero={self.numero_documento!r}, "
            f"categoria={self.categoria_afiliado!r}, score={self.score_credito})"
        )