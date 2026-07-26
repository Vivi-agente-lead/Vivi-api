"""The deterministic spine: `start`, `autorizacion_datos`, `pedir_cedula`,
`afiliado_check` (`design.md` §4).

`afiliado_check` is the only tool-dispatch node: it calls `lookup_afiliado`,
derives `edad` **server-side** from the affiliate's `fecha_nacimiento`, and
creates the `leads` row at `status='profiling'`. No LLM runs here — the
affiliation branch and the afiliado-side underage gate must not depend on model
discretion.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.graph.nodes._common import Field, collect, profile_of, say
from app.graph.nodes._validators import (
    parse_bool_si_no,
    parse_numero_documento,
    validate_enumerated,
)
from app.graph.router import MINIMUM_AGE
from app.prompts.slices import FIELD_QUESTIONS
from app.tools.lead_tools import compute_edad, lookup_afiliado, save_lead

logger = logging.getLogger(__name__)

__all__ = ["start", "autorizacion_datos", "pedir_cedula", "afiliado_check"]

_AUTORIZACION_FIELDS = (
    Field(name="autorizacion_datos", parse=parse_bool_si_no),
)

_CEDULA_FIELDS = (
    Field(
        name="tipo_documento",
        parse=lambda raw: validate_enumerated("tipo_documento", raw),
        options_key="tipo_documento",
    ),
    Field(name="numero_documento", parse=parse_numero_documento),
)


async def start(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Initialize the working copy. Deterministic — no LLM, no message.

    `design.md` §4 gives `start` a greeting slice; the greeting is folded into
    the `autorizacion_datos` question instead so a turn always produces exactly
    one outbound WhatsApp message. The node is kept because the topology's 15
    nodes and the `start → autorizacion_datos` edge are part of the contract.
    """
    return {
        "current_node": "start",
        "lead_profile": profile_of(state),
        "asked_this_turn": False,
    }


async def autorizacion_datos(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Consent gate. A refusal ends the conversation cordially."""
    delta = await collect(
        state,
        config,
        node="autorizacion_datos",
        fields=_AUTORIZACION_FIELDS,
    )
    profile = delta["lead_profile"]
    if profile.get("autorizacion_datos") is False:
        message = await say(
            state,
            node="farewell_optout",
            profile=profile,
            text=(
                "Entiendo, y respeto tu decisión. Sin esa autorización no puedo "
                "guardar tus datos ni continuar con el perfilamiento. Si más "
                "adelante quieres retomarlo, aquí estaré."
            ),
        )
        delta["messages"] = [message]
        delta["awaiting_field"] = ""
    return delta


async def pedir_cedula(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Collect the document type and number that identify the lead."""
    return await collect(
        state,
        config,
        node="pedir_cedula",
        fields=_CEDULA_FIELDS,
    )


async def afiliado_check(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Look the lead up in `afiliados_colsubsidio` and open the `leads` row.

    Writes `afiliado_colsubsidio`, and for a match also `afiliado_record`,
    `categoria`, `edad`, `score_credito`, `score_rating`, `ha_recibido_subsidio`,
    `nombre_apellido` and `fecha_nacimiento`. `edad` is derived here from the
    stored `Date`, never taken from the model.

    Idempotent: on a later turn the lookup is skipped, so replaying the spine
    costs one dict read rather than a query per turn.
    """
    profile = profile_of(state)
    if profile.get("afiliado_colsubsidio") is not None:
        return {"current_node": "afiliado_check", "lead_profile": profile}

    tipo = profile.get("tipo_documento")
    numero = profile.get("numero_documento")
    if not tipo or not numero:  # pragma: no cover — the spine guarantees both
        return {"current_node": "afiliado_check", "lead_profile": profile}

    raw = await lookup_afiliado.ainvoke(
        {"tipo_documento": tipo, "numero_documento": numero}, config=config
    )
    afiliado = _afiliado_from(raw)

    if afiliado is None:
        profile["afiliado_colsubsidio"] = False
        profile["afiliado_record"] = None
    else:
        profile["afiliado_colsubsidio"] = True
        profile["afiliado_record"] = afiliado
        profile["categoria"] = afiliado.get("categoria_afiliado")
        profile["score_credito"] = afiliado.get("score_credito")
        profile["score_rating"] = afiliado.get("score_rating")
        profile["ha_recibido_subsidio"] = afiliado.get("ha_recibido_subsidio")
        profile["nombre_apellido"] = afiliado.get("nombre_apellido")
        profile["fecha_nacimiento"] = afiliado.get("fecha_nacimiento")
        profile["edad"] = compute_edad(_as_date(afiliado.get("fecha_nacimiento")))
        if profile.get("estado_civil") is None and afiliado.get("estado_civil"):
            profile["estado_civil"] = validate_enumerated(
                "estado_civil", afiliado.get("estado_civil")
            )

    await _open_lead_row(profile, config)
    logger.info(
        "graph.afiliado_check",
        extra={
            "afiliado": profile["afiliado_colsubsidio"],
            "edad": profile.get("edad"),
        },
    )

    delta: dict[str, Any] = {
        "current_node": "afiliado_check",
        "lead_profile": profile,
    }
    if profile["afiliado_colsubsidio"] and _is_underage(profile.get("edad")):
        delta["messages"] = [
            await say(
                state,
                node="farewell_underage",
                profile=profile,
                text=(
                    "Gracias por escribirme. El programa de vivienda de "
                    "Colsubsidio está disponible para mayores de edad, así que "
                    "por ahora no puedo continuar con el proceso. Te espero más "
                    "adelante."
                ),
            )
        ]
    return delta


def _is_underage(edad: int | None) -> bool:
    """An unknown age is not an adult — the gate fails closed on both branches."""
    return edad is None or edad < MINIMUM_AGE


def _afiliado_from(raw: str) -> dict[str, Any] | None:
    """Unwrap `{"afiliado": {...} | null}`; `None` on any error envelope."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("graph.lookup_afiliado_unparseable")
        return None
    if not isinstance(payload, dict) or payload.get("error"):
        logger.warning("graph.lookup_afiliado_error", extra={"payload": str(payload)[:200]})
        return None
    afiliado = payload.get("afiliado")
    return afiliado if isinstance(afiliado, dict) else None


def _as_date(value: Any) -> date | None:
    """`date` from the ISO string `save_lead`'s JSON round-trip produces."""
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


async def _open_lead_row(profile: dict[str, Any], config: RunnableConfig) -> None:
    """First persistence: create the `leads` row at `status='profiling'`."""
    payload: dict[str, Any] = {
        "tipo_documento": profile.get("tipo_documento"),
        "numero_documento": profile.get("numero_documento"),
        "afiliado_colsubsidio": profile.get("afiliado_colsubsidio"),
    }
    for key in ("nombre_apellido", "categoria", "edad", "score_credito", "estado_civil"):
        if profile.get(key) is not None:
            payload[key] = profile[key]
    await save_lead.ainvoke(
        {key: value for key, value in payload.items() if value is not None},
        config=config,
    )


# Re-exported so the spine's question bank stays discoverable from one place.
SPINE_QUESTIONS = {
    key: FIELD_QUESTIONS[key]
    for key in ("autorizacion_datos", "tipo_documento", "numero_documento")
}
