"""Collection nodes between the spine and the capacity bundles.

`recoger_identidad` and `recoger_otra_caja` are reached only on the no-afiliado
branch — the affiliate's name, birth date and caja are already known, and the
spec forbids asking for them again. `recoger_estado_civil` is on both branches.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.graph.nodes._common import Field, collect, say
from app.graph.nodes._validators import (
    derive_tiene_pareja,
    parse_caja_compensacion,
    parse_fecha_nacimiento,
    parse_nombre,
    validate_enumerated,
)
from app.graph.router import MINIMUM_AGE
from app.tools.lead_tools import compute_edad

logger = logging.getLogger(__name__)

__all__ = ["recoger_identidad", "recoger_estado_civil", "recoger_otra_caja"]

_IDENTIDAD_FIELDS = (
    Field(name="nombre_apellido", parse=parse_nombre),
    Field(name="fecha_nacimiento", parse=parse_fecha_nacimiento),
)

_ESTADO_CIVIL_FIELDS = (
    Field(
        name="estado_civil",
        parse=lambda raw: validate_enumerated("estado_civil", raw),
        options_key="estado_civil",
    ),
)

_OTRA_CAJA_FIELDS = (
    Field(name="otra_caja_compensacion", parse=parse_caja_compensacion),
)


def _derive_edad(profile: dict[str, Any]) -> None:
    """Compute `edad` from `fecha_nacimiento` — server-side, always.

    The age gate decides whether a lead exists at all, so the number may never
    come from the model: it is recomputed here from the parsed date every time
    the node runs.
    """
    fecha = profile.get("fecha_nacimiento")
    if fecha is not None:
        profile["edad"] = compute_edad(fecha)


async def recoger_identidad(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Name and birth date of a lead with no affiliate record.

    Emits the underage farewell when the derived age is below 18; `_route_edad`
    then routes the turn to `END`.
    """
    delta = await collect(
        state,
        config,
        node="recoger_identidad",
        fields=_IDENTIDAD_FIELDS,
        finalize=_derive_edad,
        persist_fields=("nombre_apellido", "edad"),
    )
    profile = delta["lead_profile"]
    edad = profile.get("edad")
    if edad is not None and edad < MINIMUM_AGE:
        logger.info("graph.underage_gate", extra={"branch": "no_afiliado", "edad": edad})
        delta["messages"] = [
            await say(
                state,
                node="farewell_underage",
                profile=profile,
                text=(
                    "Gracias por contarme. El programa de vivienda de "
                    "Colsubsidio está disponible para mayores de edad, así que "
                    "por ahora no puedo continuar con el proceso. Te espero más "
                    "adelante."
                ),
            )
        ]
        delta["awaiting_field"] = ""
        delta["asked_this_turn"] = False
    return delta


def _derive_pareja(profile: dict[str, Any]) -> None:
    """`tiene_pareja` follows from the canonical `estado_civil` slug."""
    profile["tiene_pareja"] = derive_tiene_pareja(profile.get("estado_civil"))


async def recoger_estado_civil(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Estado civil over the six-value source domain, and `tiene_pareja`.

    `tiene_pareja` is one of the two predicates that pick the capacity bundle,
    so it is derived here from the canonical slug rather than read from a raw
    label anywhere downstream.
    """
    return await collect(
        state,
        config,
        node="recoger_estado_civil",
        fields=_ESTADO_CIVIL_FIELDS,
        finalize=_derive_pareja,
        persist_fields=("estado_civil",),
    )


async def recoger_otra_caja(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Another caja de compensación — no-afiliado branch only.

    `_route_otra_caja` keeps an affiliate away from this node entirely, so
    `otra_caja_compensacion` stays NULL for them, as the spec requires.
    """
    return await collect(
        state,
        config,
        node="recoger_otra_caja",
        fields=_OTRA_CAJA_FIELDS,
        persist_fields=("otra_caja_compensacion",),
    )
