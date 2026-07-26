"""LeadColsubsidioEntity — the Colsubsidio lead row keyed by conversation_id.

Replaces the old `LeadEntity` (a 12-column name/phone/email/budget stub) per
`design.md` §6. Enumerated columns hold **canonical slugs** (never verbatim
source labels); the verbatim→slug translation lives in
`app/services/domain_normalizer.py`.

A `LeadEntity` alias is kept pointing at this class so legacy imports
(`app/tools/lead_tools.py`, rewritten in a later phase) continue to resolve.
The old schema's columns are gone — the alias only bridges the import; Phase 5
removes it when the tool surface is rebuilt.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LeadColsubsidioEntity(Base, TimestampMixin):
    """A Colsubsidio lead captured/profiled by the assistant.

    One conversation = one lead (`conversation_id` is UNIQUE). Enumerated
    columns (`tipo_documento`, `estado_civil`, `contrato_laboral`,
    `rango_salarial`, `antiguedad_laboral`, `ahorros_o_cesantias`,
    `tiempo_compra_deseado`, `status`) MUST carry values from
    `app/models/constants.py` (or NULL); the repository enforces the status
    transition guard so terminal statuses (`ready`/`nurture`/`nurture_social`)
    cannot change once set.
    """

    __tablename__ = "leads"

    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_leads_conversation"),
        Index("ix_leads_doc", "tipo_documento", "numero_documento"),
        Index("ix_leads_categoria", "categoria"),
        Index("ix_leads_score_credito", "score_credito"),
        Index("ix_leads_status", "status"),
        Index("ix_leads_status_afiliado", "status", "afiliado_colsubsidio"),
    )

    conversation_id: Mapped[object | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )

    tipo_documento: Mapped[str] = mapped_column(String(8), nullable=False)
    numero_documento: Mapped[str] = mapped_column(String(50), nullable=False)
    afiliado_colsubsidio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    nombre_apellido: Mapped[str | None] = mapped_column(String(200), nullable=True)
    categoria: Mapped[str | None] = mapped_column(String(1), nullable=True)
    otra_caja_compensacion: Mapped[str | None] = mapped_column(String(60), nullable=True)
    estado_civil: Mapped[str | None] = mapped_column(String(20), nullable=True)
    edad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contrato_laboral: Mapped[str | None] = mapped_column(String(24), nullable=True)
    rango_salarial: Mapped[str | None] = mapped_column(String(12), nullable=True)
    total_ingresos_mensuales: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_ingresos_familiares_mensuales: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    antiguedad_laboral: Mapped[str | None] = mapped_column(String(12), nullable=True)
    tiene_vivienda_propia: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ahorros_o_cesantias: Mapped[str | None] = mapped_column(String(12), nullable=True)
    condicion_discapacidad_familiar: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    numero_pac: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tiene_creditos_activos: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    subsidio_vivienda_anterior: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cabeza_de_hogar: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    lugar_eleccion_vivir: Mapped[str | None] = mapped_column(String(60), nullable=True)
    municipio_normalizado: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    tiempo_compra_deseado: Mapped[str | None] = mapped_column(String(12), nullable=True)
    descripcion_vivienda_sueno: Mapped[str | None] = mapped_column(Text, nullable=True)
    vis_recommended: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="profiling")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_credito: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalization_notes: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return (
            f"LeadColsubsidioEntity(id={self.id}, "
            f"doc={self.tipo_documento}:{self.numero_documento!r}, "
            f"status={self.status!r})"
        )


# Backward-compat bridge: `app/tools/lead_tools.py` (rewritten in Phase 5) and
# any other legacy import still do `from app.models.lead_model import LeadEntity`.
# The alias points at the new entity so module import keeps resolving; the old
# schema columns (name/phone/email/budget) are gone, so old call sites are
# inert and will be rebuilt by Phase 5.
LeadEntity = LeadColsubsidioEntity