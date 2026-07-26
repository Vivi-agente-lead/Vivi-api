"""Block B — entry inversion and the catalogue-browsing loop.

`docs/v2-impact-analysis.md` §1, §8; `docs/Flujo asesor de venta de vivienda
Colsubsidio-v2.json`. v2 opens with a project already in hand and a three-way
menu, rather than the linear qualification flow Block A ships cold:

    [menu_proyecto] "Para continuar elige una opcion:"
        ├─ "Quiero saber más de este proyecto"  → the qualification flow
        │                                          (autorizacion_datos …)
        ├─ "Quiero ver otro proyecto."           → [elegir_preferencia_vis]
        │                                          → [elegir_municipio_catalogo]
        │                                          → [mostrar_catalogo]
        │                                          → loops back to
        │                                            elegir_municipio_catalogo
        │                                            OR into the qualification
        │                                            flow
        └─ "Salir" → [salir_menu] → END

This is new *stateful* surface with back-navigation, which the graph had no
concept of before this change. The machinery lives entirely here and in
`app/graph/router.py` — no WhatsApp/Meta reference, per the channel-agnostic
MUST in the `whatsapp-channel-pipeline` spec.

Both the "Quiero saber más" branch and the "no, sigo" exit of the browsing
loop converge on `autorizacion_datos`, exactly as the v2 diagram draws it
("¡Genial! Aquí empieza el camino…" is a single convergence point for both).
A lead who chooses to browse persists `preferencia_vis` and
`lugar_eleccion_vivir` / `municipio_normalizado` *before* qualification
starts; `recoger_intencion` (`app/graph/nodes/closing.py`) already skips any
field the profile already carries, so that lead is never asked either one
again.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.graph.nodes._common import Field, collect, profile_of, say
from app.graph.nodes._validators import parse_bool_si_no, parse_menu_opcion
from app.graph.nodes._validators import validate_enumerated, validate_municipio
from app.tools.lead_tools import get_projects

logger = logging.getLogger(__name__)

__all__ = [
    "menu_proyecto",
    "salir_menu",
    "elegir_preferencia_vis",
    "elegir_municipio_catalogo",
    "mostrar_catalogo",
]

_MENU_FIELDS = (
    Field(name="menu_opcion", parse=parse_menu_opcion, options_key="menu_opcion"),
)

_PREFERENCIA_VIS_FIELDS = (
    Field(
        name="preferencia_vis",
        parse=lambda raw: validate_enumerated("preferencia_vis", raw),
        options_key="preferencia_vis",
    ),
)

_MUNICIPIO_CATALOGO_FIELDS = (
    Field(
        name="lugar_eleccion_vivir",
        question_key="lugar_eleccion_vivir_catalogo",
        parse=lambda raw: raw if validate_municipio(raw) else None,
        options_key="lugar_eleccion_vivir",
    ),
)

_VOLVER_FIELDS = (
    Field(
        name="volver_menu_anterior",
        parse=parse_bool_si_no,
        options_key="volver_menu_anterior",
    ),
)


def _json_or_none(raw: str) -> dict[str, Any] | None:
    """Parse a tool response; `None` when it is not a JSON object."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("graph.browsing.tool_response_unparseable")
        return None
    return payload if isinstance(payload, dict) else None


def _welcome_text(proyecto: dict[str, Any] | None) -> str:
    """The v2 diagram's opening line, interpolated with a real catalogue row.

    `proyecto` comes from `_pick_default_project` — never hardcoded. When the
    catalogue is empty (nothing seeded yet) this degrades to a generic
    greeting instead of crashing or inventing project data.
    """
    saludo = (
        "Bienvenido(a), soy Vivi 🏠 y seré tu guía para encontrar tu hogar ideal."
    )
    if not proyecto:
        return saludo

    nombre = proyecto.get("proyecto")
    if not nombre:
        return saludo

    parts = [saludo, f"El proyecto en el cual estás interesado(a) es: {nombre}."]
    tipo = proyecto.get("tipo")
    if tipo:
        parts.append(f"{tipo}.")
    lugar = ", ".join(
        p for p in (proyecto.get("municipio"), proyecto.get("ubicacion")) if p
    )
    if lugar:
        parts.append(f"Su ubicación es: {lugar}.")
    area = proyecto.get("area_construida_m2")
    if area is not None:
        parts.append(f"Área desde: {area} m².")
    habitaciones = proyecto.get("cantidad_habitaciones")
    if habitaciones is not None:
        parts.append(f"Habitaciones desde: {habitaciones}.")
    return " ".join(parts)


async def _pick_default_project(config: RunnableConfig) -> dict[str, Any] | None:
    """A deterministic default project for the welcome message.

    Sourced from `proyectos_colsubsidio` through the existing `get_projects`
    tool (never hardcoded) — the first row of the unfiltered, deterministically
    ordered catalogue (`ProyectoColsubsidioRepository.find_filtered` orders by
    `(proyecto, modelo)`). Returns `None` when the catalogue is empty.
    """
    raw = await get_projects.ainvoke({}, config=config)
    payload = _json_or_none(raw) or {}
    rows = payload.get("proyectos") or []
    return rows[0] if rows else None


def _tipo_from_preferencia(preferencia: str | None) -> str | None:
    """`preferencia_vis` slug → the `tipo` filter `get_projects` accepts."""
    if preferencia == "vis":
        return "VIS"
    if preferencia == "no_vis":
        return "NO VIS"
    return None  # "ambas" or unknown: no narrowing


async def _catalogo_listing_text(
    profile: dict[str, Any], config: RunnableConfig
) -> str:
    """Up to 5 project names for the chosen municipio/tipo, or a fallback line.

    This is the `get_projects` call the browsing loop makes *before* any
    qualification or scoring — the `agent-tools` spec's "get_projects filtered
    for Calificado recommendation" scenario is amended for exactly this call
    (`openspec/changes/colsubsidio-lead-profiling/specs/agent-tools/spec.md`).
    """
    municipio = profile.get("municipio_normalizado")
    tipo = _tipo_from_preferencia(profile.get("preferencia_vis"))
    raw = await get_projects.ainvoke({"municipio": municipio, "tipo": tipo}, config=config)
    payload = _json_or_none(raw) or {}
    rows = payload.get("proyectos") or []
    if not rows:
        return (
            "Por ahora no tengo proyectos disponibles en esa zona con ese tipo "
            "de vivienda."
        )
    names: list[str] = []
    for row in rows:
        name = row.get("proyecto")
        if name and name not in names:
            names.append(name)
    listado = "\n".join(f"- {name}" for name in names)
    return f"Estos son los proyectos disponibles:\n{listado}"


async def menu_proyecto(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """The entry-inversion welcome + three-way menu.

    Fetches a default project once per conversation (idempotent, mirroring
    `afiliado_check`'s guard), then asks `menu_opcion`. `_route_menu`
    (`app/graph/router.py`) sends the answer to the qualification flow, the
    browsing loop, or the exit farewell.
    """
    profile = profile_of(state)
    if profile.get("proyecto_interes") is None:
        proyecto = await _pick_default_project(config)
        if proyecto is not None:
            profile["proyecto_interes"] = proyecto
            state = {**state, "lead_profile": profile}
    intro = _welcome_text(profile.get("proyecto_interes"))
    return await collect(state, config, node="menu_proyecto", fields=_MENU_FIELDS, intro=intro)


async def salir_menu(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """`Salir` — farewell without ever entering qualification."""
    profile = profile_of(state)
    message = await say(
        state,
        node="farewell_salir_menu",
        profile=profile,
        text=(
            "Hablaste con Vivi, tu guía para encontrar tu hogar ideal. Que "
            "pases un buen día."
        ),
    )
    logger.info("graph.salir_menu")
    return {"current_node": "salir_menu", "lead_profile": profile, "messages": [message]}


async def elegir_preferencia_vis(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """`¿Te interesan vivienda VIS, NO VIS o ambas?` — browsing branch only."""
    return await collect(
        state,
        config,
        node="elegir_preferencia_vis",
        fields=_PREFERENCIA_VIS_FIELDS,
        persist_fields=("preferencia_vis",),
    )


def _finalize_municipio_catalogo(profile: dict[str, Any]) -> None:
    """Derive the catalogue join key, and clear the stale back-navigation flag.

    `municipio_normalizado` is what `mostrar_catalogo` and, later,
    `recoger_intencion` query and skip on respectively. Resetting
    `volver_menu_anterior` here (not in `mostrar_catalogo`) is what makes the
    back-navigation loop askable again: it must survive long enough for
    `_route_volver_menu` to read it after `mostrar_catalogo` returns, so it
    cannot be cleared there — this node runs next, on the very same turn when
    the lead loops back, and is the one place after which asking again makes
    sense.
    """
    raw = profile.get("lugar_eleccion_vivir")
    if raw is not None:
        profile["municipio_normalizado"] = validate_municipio(raw)
    profile["volver_menu_anterior"] = None


async def elegir_municipio_catalogo(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """`Tenemos proyectos disponibles en los siguientes municipios…`

    Same nine-option domain as `recoger_intencion`'s `lugar_eleccion_vivir`,
    phrased as the catalogue-menu question instead — `FIELD_QUESTIONS` keys
    the two phrasings separately under `lugar_eleccion_vivir_catalogo` and
    `lugar_eleccion_vivir`, sharing the same option list and the same
    `lead_profile` field.
    """
    return await collect(
        state,
        config,
        node="elegir_municipio_catalogo",
        fields=_MUNICIPIO_CATALOGO_FIELDS,
        finalize=_finalize_municipio_catalogo,
        persist_fields=("lugar_eleccion_vivir", "municipio_normalizado"),
    )


async def mostrar_catalogo(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Show the filtered catalogue and ask whether to go back or continue.

    `_route_volver_menu` reads `volver_menu_anterior` after this node returns:
    `True` loops back to `elegir_municipio_catalogo` (which re-asks because
    that node's `finalize` cleared `lugar_eleccion_vivir` here first); `False`
    (or unanswered) proceeds into `autorizacion_datos`, carrying the chosen
    `preferencia_vis` and `municipio_normalizado` forward.
    """
    profile = profile_of(state)
    listing = await _catalogo_listing_text(profile, config)

    def _finalize(p: dict[str, Any]) -> None:
        if p.get("volver_menu_anterior") is True:
            p["lugar_eleccion_vivir"] = None
            p["municipio_normalizado"] = None

    modified_state = {**state, "lead_profile": profile}
    return await collect(
        modified_state,
        config,
        node="mostrar_catalogo",
        fields=_VOLVER_FIELDS,
        finalize=_finalize,
        intro=listing,
    )
