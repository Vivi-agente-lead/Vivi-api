"""The five lead-profiling tools exposed to the Vivi agent runtime.

Surface (``design.md`` §5, spec delta ``agent-tools``):

* :func:`lookup_afiliado` — composite-key affiliate lookup with derived `edad`
  and `score_rating`.
* :func:`save_lead` — merge-upsert of the ``leads`` row keyed by
  ``conversation_id``; normalizes every enumerated field to its canonical slug.
* :func:`get_lead` — the current ``leads`` row, or ``null``.
* :func:`get_projects` — up to five catalogue rows for a **normalized**
  municipio, ordered by ``(proyecto, modelo)``.
* :func:`classify_lead` — runs the pure scorer and persists the verdict.

Invariances this module MUST keep:

1. **No ``langgraph`` import.** The tool layer is a stateless service layer; the
   graph depends on it, never the other way round.
2. **``conversation_id`` comes from the :class:`~app.services.tool_context.ToolContext`**,
   never from LLM arguments — an LLM-supplied ``conversation_id`` is accepted by
   the schema and then discarded, so a hallucinated id cannot forge a
   cross-conversation write.
3. **``save_lead`` never promotes ``status``.** There is no ``status`` parameter;
   only :func:`classify_lead` writes that column, and the terminal-status guard
   lives in ``LeadRepository.upsert_by_conversation_id``.
4. **Enumerated values are canonical slugs on the wire to the repository.** A
   value that matches no verbatim source label and no canonical slug is written
   as NULL and appended to ``normalization_notes`` for the audit trail.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.models.afiliado_model import AfiliadoColsubsidioEntity
from app.models.lead_model import LeadColsubsidioEntity
from app.models.proyecto_model import ProyectoColsubsidioEntity
from app.models.repositories.afiliado_repository import AfiliadoColsubsidioRepository
from app.models.repositories.lead_repository import (
    LeadRepository,
    LeadStatusTransitionError,
)
from app.models.repositories.proyecto_repository import ProyectoColsubsidioRepository
from app.services import lead_scorer
from app.services.credit_bands import band_from_score_credito
from app.services.domain_normalizer import normalize, normalize_municipio
from app.services.tool_context import get_tool_context
from app.tools.base import json_dumps, safe_tool

logger = logging.getLogger(__name__)

__all__ = [
    "compute_edad",
    "normalize_lead_fields",
    "lookup_afiliado",
    "save_lead",
    "get_lead",
    "get_projects",
    "classify_lead",
]

# Enumerated lead fields routed through `domain_normalizer.normalize` before the
# write. `municipio_normalizado` is handled separately (its own table).
_ENUMERATED_FIELDS: tuple[str, ...] = (
    "tipo_documento",
    "estado_civil",
    "contrato_laboral",
    "rango_salarial",
    "antiguedad_laboral",
    "ahorros_o_cesantias",
    "tiempo_compra_deseado",
)

# Money columns are `Numeric(14, 2)`; the LLM sends plain numbers.
_DECIMAL_FIELDS: tuple[str, ...] = (
    "total_ingresos_mensuales",
    "total_ingresos_familiares_mensuales",
)

# Columns copied verbatim from a `leads` row into the tool response / the
# scorer input. Kept explicit so a schema change is a deliberate edit here.
_LEAD_COLUMNS: tuple[str, ...] = (
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
    "total_ingresos_familiares_mensuales",
    "antiguedad_laboral",
    "tiene_vivienda_propia",
    "ahorros_o_cesantias",
    "condicion_discapacidad_familiar",
    "numero_pac",
    "tiene_creditos_activos",
    "subsidio_vivienda_anterior",
    "cabeza_de_hogar",
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

_PROJECT_COLUMNS: tuple[str, ...] = (
    "proyecto",
    "tipo",
    "municipio",
    "ubicacion",
    "direccion",
    "descripcion",
    "modelo",
    "area_construida_m2",
    "area_privada_m2",
    "cantidad_habitaciones",
    "cantidad_banos",
    "valor_vis_smmlv",
)

_PROJECT_RESULT_LIMIT: int = 5


# ── Pure helpers ────────────────────────────────────────────────────────────
def compute_edad(fecha_nacimiento: date | None, today: date | None = None) -> int | None:
    """Full years between ``fecha_nacimiento`` and ``today``.

    Server-side derivation: the age gates must never depend on an LLM-supplied
    number. Returns ``None`` when there is no birth date — an unknown age is not
    an adult, and the routers treat ``None`` as a terminal gate.
    """
    if fecha_nacimiento is None:
        return None
    today = today or date.today()
    years = today.year - fecha_nacimiento.year
    if (today.month, today.day) < (fecha_nacimiento.month, fecha_nacimiento.day):
        years -= 1
    return years


def normalize_lead_fields(
    fields: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Map every enumerated value in ``fields`` to its canonical slug.

    Returns ``(normalized_fields, notes)``. A value that matches no verbatim
    source label and no canonical slug becomes ``None`` (the column is written
    NULL) and produces a note naming the field and the rejected raw value, so
    the audit trail keeps what the lead actually said.

    ``municipio_normalizado`` is derived from ``lugar_eleccion_vivir`` when the
    caller supplies the raw option only: ``get_projects`` MUST be queried with
    the catalogue vocabulary, never with the accented lead-facing option.
    """
    out = dict(fields)
    notes: list[str] = []

    for field in _ENUMERATED_FIELDS:
        if field not in out:
            continue
        raw = out[field]
        if raw is None:
            continue
        slug = normalize(field, str(raw))
        if slug is None:
            notes.append(f"Valor no reconocido para {field}: {raw!r}")
        out[field] = slug

    if "municipio_normalizado" in out and out["municipio_normalizado"] is not None:
        raw = out["municipio_normalizado"]
        slug = normalize_municipio(str(raw))
        if slug is None:
            notes.append(f"Valor no reconocido para municipio_normalizado: {raw!r}")
        out["municipio_normalizado"] = slug
    elif out.get("lugar_eleccion_vivir") is not None:
        raw = out["lugar_eleccion_vivir"]
        slug = normalize_municipio(str(raw))
        if slug is None:
            notes.append(f"Valor no reconocido para lugar_eleccion_vivir: {raw!r}")
        out["municipio_normalizado"] = slug

    for field in _DECIMAL_FIELDS:
        if out.get(field) is None:
            continue
        try:
            out[field] = Decimal(str(out[field]))
        except (InvalidOperation, ValueError):
            notes.append(f"Valor no numerico para {field}: {out[field]!r}")
            out[field] = None

    return out, notes


def _lead_to_dict(lead: LeadColsubsidioEntity) -> dict[str, Any]:
    """Render a ``leads`` row as a plain dict matching the schema."""
    payload: dict[str, Any] = {
        "id": lead.id,
        "conversation_id": lead.conversation_id,
    }
    for column in _LEAD_COLUMNS:
        payload[column] = getattr(lead, column, None)
    return payload


def _afiliado_to_dict(afiliado: AfiliadoColsubsidioEntity) -> dict[str, Any]:
    """Render an afiliado row plus the two server-derived fields."""
    _, rating = band_from_score_credito(afiliado.score_credito)
    return {
        "id": afiliado.id,
        "tipo_documento": afiliado.tipo_documento,
        "numero_documento": afiliado.numero_documento,
        "nombre_apellido": afiliado.nombre_apellido,
        "fecha_nacimiento": afiliado.fecha_nacimiento,
        "edad": compute_edad(afiliado.fecha_nacimiento),
        "estado_civil": afiliado.estado_civil,
        "salario_base_cotizacion": afiliado.salario_base_cotizacion,
        "categoria": afiliado.categoria,
        "categoria_afiliado": afiliado.categoria_afiliado,
        "score_credito": afiliado.score_credito,
        "score_rating": rating,
        "ha_recibido_subsidio": afiliado.ha_recibido_subsidio,
    }


def _proyecto_to_dict(proyecto: ProyectoColsubsidioEntity) -> dict[str, Any]:
    """Render a catalogue row verbatim — including the corrupt `'VIS'` municipio."""
    return {column: getattr(proyecto, column, None) for column in _PROJECT_COLUMNS}


def _missing_conversation() -> str:
    """The JSON error returned when the runtime has no conversation bound."""
    return json_dumps(
        {
            "error": True,
            "code": "missing_conversation",
            "message": "No hay una conversación activa asociada a esta herramienta.",
        }
    )


# ── Tools ───────────────────────────────────────────────────────────────────
@tool
@safe_tool
async def lookup_afiliado(
    tipo_documento: str,
    numero_documento: str,
    *,
    config: RunnableConfig,
) -> str:
    """Look up a Colsubsidio affiliate by document type and number.

    Args:
        tipo_documento: one of `CC` (cédula de ciudadanía), `CE` (cédula de
            extranjería), `PA` (pasaporte), `PEP` (permiso especial de
            permanencia) or `PPT` (permiso por protección temporal). The
            verbatim Spanish label is also accepted.
        numero_documento: the document number, digits only.

    Returns:
        JSON `{"afiliado": null}` when there is no match, otherwise
        `{"afiliado": {...}}` carrying the stored row plus the derived `edad`
        and the `score_rating` band of `score_credito`.
    """
    ctx = get_tool_context(config)
    slug = normalize("tipo_documento", tipo_documento)
    if slug is None:
        # `TI` and anything else outside the five source types never reaches the
        # database: the source domain has no tarjeta de identidad.
        return json_dumps(
            {
                "error": True,
                "code": "invalid_tipo_documento",
                "message": (
                    f"Tipo de documento no válido: {tipo_documento!r}. "
                    "Usa CC, CE, PA, PEP o PPT."
                ),
            }
        )

    numero = (numero_documento or "").strip()
    repo = AfiliadoColsubsidioRepository(ctx.session)
    afiliado = await repo.find_by_doc(slug, numero)
    if afiliado is None:
        logger.info("lookup_afiliado.miss", extra={"tipo_documento": slug})
        return json_dumps({"afiliado": None})

    logger.info("lookup_afiliado.hit", extra={"tipo_documento": slug})
    return json_dumps({"afiliado": _afiliado_to_dict(afiliado)})


@tool
@safe_tool
async def save_lead(
    *,
    config: RunnableConfig,
    tipo_documento: str | None = None,
    numero_documento: str | None = None,
    afiliado_colsubsidio: bool | None = None,
    nombre_apellido: str | None = None,
    categoria: str | None = None,
    otra_caja_compensacion: str | None = None,
    estado_civil: str | None = None,
    edad: int | None = None,
    contrato_laboral: str | None = None,
    rango_salarial: str | None = None,
    total_ingresos_mensuales: float | None = None,
    total_ingresos_familiares_mensuales: float | None = None,
    antiguedad_laboral: str | None = None,
    tiene_vivienda_propia: bool | None = None,
    ahorros_o_cesantias: str | None = None,
    condicion_discapacidad_familiar: bool | None = None,
    numero_pac: int | None = None,
    tiene_creditos_activos: bool | None = None,
    subsidio_vivienda_anterior: bool | None = None,
    cabeza_de_hogar: bool | None = None,
    lugar_eleccion_vivir: str | None = None,
    municipio_normalizado: str | None = None,
    tiempo_compra_deseado: str | None = None,
    descripcion_vivienda_sueno: str | None = None,
    vis_recommended: bool | None = None,
    score_credito: int | None = None,
    conversation_id: str | None = None,
) -> str:
    """Save the answers collected so far onto the lead of this conversation.

    Only pass the fields you just collected: omitted fields keep their previous
    value. Enumerated fields accept either the verbatim option shown to the
    person or its canonical slug. This tool never sets the lead status — the
    classification is written by `classify_lead`.

    Args:
        tipo_documento: `CC`, `CE`, `PA`, `PEP` or `PPT`.
        numero_documento: document number, digits only.
        afiliado_colsubsidio: whether the person is a Colsubsidio affiliate.
        nombre_apellido: full name.
        categoria: affiliate categoria `A`, `B` or `C`.
        otra_caja_compensacion: another caja de compensación, or `ninguna`.
        estado_civil: Soltero, Casado, Divorciado, Union libre, Separado, Viudo.
        edad: age in full years (derived server-side; do not guess it).
        contrato_laboral: Termino fijo, Termino indefinido, Prestacion de servicios.
        rango_salarial: 2 millones o menos … mas de 10 millones.
        total_ingresos_mensuales: monthly income of a lead without a partner.
        total_ingresos_familiares_mensuales: household income when there is a partner.
        antiguedad_laboral: menos de 1 año, 1 a 2 años, mas de dos años.
        tiene_vivienda_propia: whether the person already owns a home.
        ahorros_o_cesantias: No tengo ahorros. … Más de $40 millones.
        condicion_discapacidad_familiar: disability in the household.
        numero_pac: number of dependants (personas a cargo).
        tiene_creditos_activos: whether the person has active loans.
        subsidio_vivienda_anterior: whether a housing subsidy was granted before.
        cabeza_de_hogar: derived head-of-household flag.
        lugar_eleccion_vivir: the location option chosen, verbatim.
        municipio_normalizado: catalogue municipio; derived from
            `lugar_eleccion_vivir` when omitted.
        tiempo_compra_deseado: 3 meses, 6 meses, 1 año, 2 años, no sé.
        descripcion_vivienda_sueno: free text describing the desired home.
        vis_recommended: whether VIS projects matched the chosen municipio.
        score_credito: credit score 150-950 taken from the affiliate record.
        conversation_id: ignored — the conversation is resolved from the runtime.

    Returns:
        JSON `{"id": ..., "status": "profiling"}`.
    """
    ctx = get_tool_context(config)
    if ctx.conversation_id is None:
        return _missing_conversation()
    if conversation_id is not None:
        # Accepted by the schema so a hallucinated argument does not break the
        # call, then discarded: the LLM cannot address another conversation.
        logger.warning(
            "save_lead.ignored_llm_conversation_id",
            extra={"conversation_id": str(ctx.conversation_id)},
        )

    candidate: dict[str, Any] = {
        "tipo_documento": tipo_documento,
        "numero_documento": numero_documento,
        "afiliado_colsubsidio": afiliado_colsubsidio,
        "nombre_apellido": nombre_apellido,
        "categoria": categoria,
        "otra_caja_compensacion": otra_caja_compensacion,
        "estado_civil": estado_civil,
        "edad": edad,
        "contrato_laboral": contrato_laboral,
        "rango_salarial": rango_salarial,
        "total_ingresos_mensuales": total_ingresos_mensuales,
        "total_ingresos_familiares_mensuales": total_ingresos_familiares_mensuales,
        "antiguedad_laboral": antiguedad_laboral,
        "tiene_vivienda_propia": tiene_vivienda_propia,
        "ahorros_o_cesantias": ahorros_o_cesantias,
        "condicion_discapacidad_familiar": condicion_discapacidad_familiar,
        "numero_pac": numero_pac,
        "tiene_creditos_activos": tiene_creditos_activos,
        "subsidio_vivienda_anterior": subsidio_vivienda_anterior,
        "cabeza_de_hogar": cabeza_de_hogar,
        "lugar_eleccion_vivir": lugar_eleccion_vivir,
        "municipio_normalizado": municipio_normalizado,
        "tiempo_compra_deseado": tiempo_compra_deseado,
        "descripcion_vivienda_sueno": descripcion_vivienda_sueno,
        "vis_recommended": vis_recommended,
        "score_credito": score_credito,
    }
    # `None` means "not collected in this turn", never "clear the column": the
    # merge upsert must not undo an answer the lead already gave.
    supplied = {key: value for key, value in candidate.items() if value is not None}
    if not supplied:
        return json_dumps(
            {
                "error": True,
                "code": "no_fields",
                "message": "No recibí ningún dato para guardar.",
            }
        )

    fields, notes = normalize_lead_fields(supplied)
    if notes:
        fields["normalization_notes"] = notes

    repo = LeadRepository(ctx.session)
    lead = await repo.upsert_by_conversation_id(ctx.conversation_id, fields)
    await repo.commit()
    logger.info(
        "save_lead.upserted",
        extra={"conversation_id": str(ctx.conversation_id), "fields": sorted(fields)},
    )
    return json_dumps({"id": lead.id, "status": lead.status})


@tool
@safe_tool
async def get_lead(*, config: RunnableConfig) -> str:
    """Return everything already saved about this conversation's lead.

    Returns:
        JSON with the current lead row, or `null` when nothing has been saved
        yet. Use it before asking a question to avoid repeating one.
    """
    ctx = get_tool_context(config)
    if ctx.conversation_id is None:
        return _missing_conversation()

    repo = LeadRepository(ctx.session)
    lead = await repo.find_by_conversation_id(ctx.conversation_id)
    if lead is None:
        return json_dumps(None)
    return json_dumps(_lead_to_dict(lead))


@tool
@safe_tool
async def get_projects(
    municipio: str | None = None,
    tipo: str | None = None,
    *,
    config: RunnableConfig,
) -> str:
    """List Colsubsidio housing projects for a municipio.

    Args:
        municipio: the **normalized** catalogue municipio (`Bogota`, `Soacha`,
            `Chía`, `Tocancipá`, `Girardot`, `Ricaurte`, `Ubate`), i.e. the
            lead's `municipio_normalizado` — never the raw location option.
        tipo: `VIS` or `NO VIS` to narrow the list.

    Returns:
        JSON `{"proyectos": [...], "total": n}` with at most five rows ordered
        by project name and model.
    """
    ctx = get_tool_context(config)

    lookup_municipio = municipio
    if municipio is not None:
        # Defensive: the caller must already pass `municipio_normalizado`, but a
        # raw lead-facing option ('Bogotá norte') still resolves to the
        # catalogue vocabulary instead of silently matching nothing.
        resolved = normalize_municipio(municipio)
        if resolved is None:
            logger.warning("get_projects.unmapped_municipio", extra={"municipio": municipio})
        else:
            lookup_municipio = resolved

    repo = ProyectoColsubsidioRepository(ctx.session)
    rows = await repo.find_filtered(
        municipio=lookup_municipio, tipo=tipo, limit=_PROJECT_RESULT_LIMIT
    )
    return json_dumps(
        {
            "proyectos": [_proyecto_to_dict(row) for row in rows],
            "total": len(rows),
            "municipio": lookup_municipio,
        }
    )


@tool
@safe_tool
async def classify_lead(*, config: RunnableConfig) -> str:
    """Score this conversation's lead and persist the classification.

    Returns:
        JSON `{"status", "score", "score_rating", "classification", "reasoning"}`
        where `classification` equals `status` and is one of `ready`, `nurture`
        or `nurture_social`.
    """
    ctx = get_tool_context(config)
    if ctx.conversation_id is None:
        return _missing_conversation()

    repo = LeadRepository(ctx.session)
    lead = await repo.find_by_conversation_id(ctx.conversation_id)
    if lead is None:
        return json_dumps(
            {
                "error": True,
                "code": "lead_not_found",
                "message": "Todavía no hay datos guardados para clasificar.",
            }
        )

    profile = _lead_to_dict(lead)
    afiliado = await _afiliado_for(ctx.session, lead)
    score, score_rating, classification, reasoning = lead_scorer.score_lead(
        profile, afiliado
    )

    verdict = {
        "status": classification,
        "score": score,
        "score_rating": score_rating,
        "classification": classification,
        "reasoning": reasoning,
    }
    try:
        await repo.upsert_by_conversation_id(
            ctx.conversation_id,
            {
                "status": classification,
                "score": score,
                "score_rating": score_rating,
                "classification_reasoning": reasoning,
            },
        )
    except LeadStatusTransitionError:
        # The row already carries a terminal verdict; the repository guard is
        # the single source of truth, so the stored verdict wins and the call
        # stays idempotent instead of raising at the LLM.
        logger.info(
            "classify_lead.terminal_status_preserved",
            extra={"conversation_id": str(ctx.conversation_id), "status": lead.status},
        )
        return json_dumps(
            {
                "status": lead.status,
                "score": lead.score,
                "score_rating": lead.score_rating,
                "classification": lead.status,
                "reasoning": lead.classification_reasoning,
            }
        )

    await repo.commit()
    logger.info(
        "classify_lead.persisted",
        extra={"conversation_id": str(ctx.conversation_id), "status": classification},
    )
    return json_dumps(verdict)


async def _afiliado_for(
    session: Any, lead: LeadColsubsidioEntity
) -> dict[str, Any] | None:
    """The affiliate record backing a lead, or ``None`` for a no-afiliado.

    The scorer's Bucket 1 and Bucket 2 read ``score_credito`` and
    ``categoria_afiliado`` from this mapping; ``None`` selects the no-afiliado
    path (bureau simulation + 0 affiliation points).
    """
    if not lead.afiliado_colsubsidio:
        return None
    if lead.tipo_documento and lead.numero_documento:
        repo = AfiliadoColsubsidioRepository(session)
        row = await repo.find_by_doc(lead.tipo_documento, lead.numero_documento)
        if row is not None:
            return _afiliado_to_dict(row)
    # The row was flagged as an affiliate but the source record is gone; the
    # mirrored columns on the lead keep the verdict reproducible.
    return {
        "score_credito": lead.score_credito,
        "categoria_afiliado": lead.categoria,
    }
