"""Collection nodes between the spine and the household capacity block.

`recoger_identidad` and `recoger_interes_afiliacion` are reached only on the
no-afiliado branch — the affiliate's name, age and affiliation intent are
already known (or not applicable), and the spec forbids asking for them again.
`recoger_estado_civil` is on both branches.

v2 migration (``docs/v2-impact-analysis.md``): `recoger_identidad` asks
`¿Que edad tienes?` directly instead of `fecha_nacimiento` — the v2 flow
diagram has no birth-date node on the no-afiliado path at all, only the direct
age question; the afiliado path is unaffected, still reading `edad` from the
record (`app/graph/nodes/spine.py::afiliado_check`). `recoger_otra_caja`
(v1's caja-name prompt) is replaced by `recoger_interes_afiliacion`, which
collects `interes_afiliacion` and derives the now-boolean
`otra_caja_compensacion` from it (sheet column J) — never asked directly.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.graph.nodes._common import Field, collect, say
from app.graph.nodes._validators import (
    derive_tiene_pareja,
    parse_int,
    parse_nombre,
    validate_enumerated,
)
from app.graph.router import MINIMUM_AGE
from app.models.constants import OTRA_CAJA_COMPENSACION_TRIGGER

logger = logging.getLogger(__name__)

__all__ = [
    "recoger_identidad",
    "recoger_estado_civil",
    "recoger_interes_afiliacion",
]

_IDENTIDAD_FIELDS = (
    Field(name="nombre_apellido", parse=parse_nombre),
    Field(name="edad", parse=parse_int),
)

_ESTADO_CIVIL_FIELDS = (
    Field(
        name="estado_civil",
        parse=lambda raw: validate_enumerated("estado_civil", raw),
        options_key="estado_civil",
    ),
)

_INTERES_AFILIACION_FIELDS = (
    Field(
        name="interes_afiliacion",
        parse=lambda raw: validate_enumerated("interes_afiliacion", raw),
        options_key="interes_afiliacion",
    ),
)


async def recoger_identidad(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Name and age of a lead with no affiliate record.

    Emits the underage farewell when `edad` is below 18; `_route_edad` then
    routes the turn to `END`. `edad` is the lead's own stated answer here — the
    v2 flow diagram asks it directly on this branch, unlike the afiliado
    branch, which still reads it server-side from the record.
    """
    delta = await collect(
        state,
        config,
        node="recoger_identidad",
        fields=_IDENTIDAD_FIELDS,
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

    `tiene_pareja` is bookkeeping only in v2 — it no longer picks a capacity
    bundle (the four bundles collapsed into one, `recoger_capacidad`) — but is
    still derived here from the canonical slug for the audit trail.
    """
    return await collect(
        state,
        config,
        node="recoger_estado_civil",
        fields=_ESTADO_CIVIL_FIELDS,
        finalize=_derive_pareja,
        persist_fields=("estado_civil",),
    )


def _derive_otra_caja(profile: dict[str, Any]) -> None:
    """`otra_caja_compensacion` is derived, never asked (sheet column J, verbatim):

    "La respuesta es 'No, estoy afiliado a otra caja de compensación' setear
    en SI de lo contrario NO."
    """
    respuesta = profile.get("interes_afiliacion")
    if respuesta is not None:
        profile["otra_caja_compensacion"] = respuesta == OTRA_CAJA_COMPENSACION_TRIGGER


async def recoger_interes_afiliacion(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Affiliation intent — no-afiliado branch only.

    Reachable only from `_route_edad`'s adult branch, which only the
    no-afiliado side of `_route_afiliado` ever reaches, so an affiliate is
    structurally never asked this and `interes_afiliacion` /
    `otra_caja_compensacion` stay NULL for them, as the spec requires.
    """
    return await collect(
        state,
        config,
        node="recoger_interes_afiliacion",
        fields=_INTERES_AFILIACION_FIELDS,
        finalize=_derive_otra_caja,
        persist_fields=("interes_afiliacion", "otra_caja_compensacion"),
    )
