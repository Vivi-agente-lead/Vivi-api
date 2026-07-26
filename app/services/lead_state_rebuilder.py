"""Rebuild `lead_profile` from the `leads` row after a checkpointer loss.

`design.md` §2. The working copy lives in the checkpointer, but the auditable
artifact is the DB row. With `LLM_CHECKPOINTER=memory` a process restart drops
every thread, and without this the conversation would silently restart at
`autorizacion_datos` and re-ask a lead everything they already answered.

The rebuild is **lossy by design**: only columns the `leads` table actually
carries come back. The two derived bookkeeping predicates (`tiene_pareja`,
`es_empleado`) are recomputed from the restored slugs rather than stored, and
`afiliado_record` is re-fetched, so a restored profile routes exactly like a
live one. `autorizacion_datos` is inferred from the row's existence: the row
is only created after consent was granted.

v2 migration (``docs/v2-impact-analysis.md``): removes `antiguedad_laboral`,
`total_ingresos_familiares_mensuales`, `condicion_discapacidad_familiar` and
`cabeza_de_hogar` (columns dropped from the model, so the derivation for the
last one is gone too); adds `gastos_mensuales`, `interes_afiliacion` and
`preferencia_vis`. `rango_salarial` is re-derived from
`total_ingresos_mensuales` when not already stored, mirroring
`app.graph.nodes.capacity.recoger_capacidad`'s finalize step.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.nodes._validators import (
    derive_es_empleado,
    derive_rango_salarial,
    derive_tiene_pareja,
)
from app.models.repositories.afiliado_repository import AfiliadoColsubsidioRepository
from app.models.repositories.lead_repository import LeadRepository
from app.tools.lead_tools import compute_edad

logger = logging.getLogger(__name__)

__all__ = ["rebuild_lead_profile", "RESTORED_COLUMNS"]

# Columns mirrored straight back into the working copy.
RESTORED_COLUMNS: tuple[str, ...] = (
    "tipo_documento",
    "numero_documento",
    "afiliado_colsubsidio",
    "nombre_apellido",
    "categoria",
    "otra_caja_compensacion",
    "estado_civil",
    "edad",
    "contrato_laboral",
    "rango_salarial",
    "total_ingresos_mensuales",
    "gastos_mensuales",
    "tiene_vivienda_propia",
    "ahorros_o_cesantias",
    "numero_pac",
    "tiene_creditos_activos",
    "subsidio_vivienda_anterior",
    "interes_afiliacion",
    "preferencia_vis",
    "lugar_eleccion_vivir",
    "municipio_normalizado",
    "tiempo_compra_deseado",
    "descripcion_vivienda_sueno",
    "vis_recommended",
    "status",
    "score",
    "score_credito",
    "score_rating",
    "classification_reasoning",
    "normalization_notes",
)


async def rebuild_lead_profile(
    session: AsyncSession, conversation_id: uuid.UUID
) -> dict[str, Any]:
    """Reconstruct the graph working copy for a conversation.

    `design.md` §2 writes this as `rebuild_lead_profile(conv_id)`; the session is
    an explicit parameter because the function has no other way to reach the
    database — `AgentService` owns the request-scoped session.

    Returns an empty dict when no `leads` row exists, which is the normal case
    for a brand-new conversation.
    """
    repo = LeadRepository(session)
    lead = await repo.find_by_conversation_id(conversation_id)
    if lead is None:
        return {}

    profile: dict[str, Any] = {}
    for column in RESTORED_COLUMNS:
        value = getattr(lead, column, None)
        if value is not None:
            profile[column] = value

    # The row only exists because consent was granted before it was created.
    profile["autorizacion_datos"] = True

    profile["tiene_pareja"] = derive_tiene_pareja(profile.get("estado_civil"))
    profile["es_empleado"] = derive_es_empleado(profile.get("contrato_laboral"))
    if profile.get("rango_salarial") is None:
        derived = derive_rango_salarial(profile.get("total_ingresos_mensuales"))
        if derived is not None:
            profile["rango_salarial"] = derived

    if lead.afiliado_colsubsidio and lead.tipo_documento and lead.numero_documento:
        await _restore_afiliado(session, lead, profile)

    logger.info(
        "lead_profile.rebuilt",
        extra={"conversation_id": str(conversation_id), "fields": len(profile)},
    )
    return profile


async def _restore_afiliado(
    session: AsyncSession, lead: Any, profile: dict[str, Any]
) -> None:
    """Re-fetch the affiliate record so the branch predicates behave identically."""
    repo = AfiliadoColsubsidioRepository(session)
    row = await repo.find_by_doc(lead.tipo_documento, lead.numero_documento)
    if row is None:
        return
    profile["afiliado_record"] = {
        "categoria_afiliado": row.categoria_afiliado,
        "score_credito": row.score_credito,
        "ha_recibido_subsidio": row.ha_recibido_subsidio,
        "nombre_apellido": row.nombre_apellido,
        "fecha_nacimiento": row.fecha_nacimiento,
        "estado_civil": row.estado_civil,
        "salario_base_cotizacion": row.salario_base_cotizacion,
    }
    profile["ha_recibido_subsidio"] = row.ha_recibido_subsidio
    profile.setdefault("fecha_nacimiento", row.fecha_nacimiento)
    # Recompute rather than trust the stored `edad`: the column was written on a
    # previous day and a birthday may have passed since.
    derived = compute_edad(row.fecha_nacimiento)
    if derived is not None:
        profile["edad"] = derived
