"""Conditional-edge predicates for the lead-profiling StateGraph.

Two invariants this module exists to hold:

1. **Terminal returns use the `END` sentinel imported from `langgraph.graph`,
   never the literal string `"END"`.** LangGraph resolves an unregistered
   destination by logging `wrote to unknown channel …, ignoring it` and stopping
   — silently. A wrong sentinel therefore *looks* like it works, which is how the
   defect survived the previous design revision.
2. **`edad is None` routes to `END` in both age gates.** An unknown age is not an
   adult, on either branch.

v2 migration (``docs/v2-impact-analysis.md``): `_route_capacity` is deleted —
the four capacity bundles it selected among collapse into the single
`recoger_capacidad` node, so `tiene_pareja` and `es_empleado` stop being
routing predicates. `_route_otra_caja` is also deleted: the affiliation
question (`interes_afiliacion`, replacing the old `otra_caja_compensacion`
prompt) moves to right after the no-afiliado age gate, a spot only the
no-afiliado branch ever reaches, so the gate is now structural — `_route_edad`
routes an adult no-afiliado straight to `recoger_interes_afiliacion` and no
separate predicate has to re-check `afiliado_colsubsidio` there.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END

__all__ = [
    "MINIMUM_AGE",
    "_route_autorizacion",
    "_route_afiliado",
    "_route_edad",
    "_route_menu",
    "_route_volver_menu",
    "_route_handoff",
]

MINIMUM_AGE = 18


def _profile(state: Any) -> dict[str, Any]:
    """The lead working copy, or an empty dict on the very first turn.

    `design.md` §3 indexes `state["lead_profile"]` directly. Reading defensively
    is deliberate: the consent gate can fire before any node has written the key,
    and a `KeyError` there would abort the whole conversation instead of ending
    it cordially.
    """
    return state.get("lead_profile") or {}


def _route_autorizacion(state: Any) -> str:
    """Consent gate. A refusal — or no answer yet — ends the turn cordially."""
    return "pedir_cedula" if _profile(state).get("autorizacion_datos") else END


def _route_afiliado(state: Any) -> str:
    """Affiliation branch, plus the afiliado-side underage gate.

    The source flow diagram carries `Consultar edad en BD → ¿Es mayor de edad?`
    on the afiliado side; `afiliado_check` already derived `edad` from the
    afiliado record, so the gate is evaluated here rather than in a dedicated
    node. The no-afiliado branch reaches its own gate through `recoger_identidad`
    and `_route_edad`.
    """
    profile = _profile(state)
    if not profile.get("afiliado_colsubsidio"):
        return "recoger_identidad"
    edad = profile.get("edad")
    if edad is None or edad < MINIMUM_AGE:
        return END
    return "recoger_estado_civil"


def _route_edad(state: Any) -> str:
    """No-afiliado underage gate.

    v2 asks `¿Que edad tienes?` directly on this branch (`recoger_identidad`);
    the value is taken from the lead's own answer, not derived from a birth
    date. An adult routes to `recoger_interes_afiliacion` — reachable only
    from here, which is what gates that question to non-affiliates without a
    separate predicate.
    """
    edad = _profile(state).get("edad")
    if edad is None or edad < MINIMUM_AGE:
        return END
    return "recoger_interes_afiliacion"


# ── Block B: entry inversion + catalogue browsing (``docs/v2-impact-analysis.md``
# §1, §8) ─────────────────────────────────────────────────────────────────────
def _route_menu(state: Any) -> str:
    """The v2 diagram's three-way entry menu.

    `"ver_otro_proyecto"` enters the catalogue-browsing loop; `"salir"` ends
    the conversation cordially; `"ver_detalle"` (and any unmapped/unanswered
    value, defensively — `turn_gated` should never let this run before
    `menu_opcion` is set) enters the same qualification flow both this branch
    and the browsing loop's "no volver" exit converge on.
    """
    opcion = _profile(state).get("menu_opcion")
    if opcion == "ver_otro_proyecto":
        return "elegir_preferencia_vis"
    if opcion == "salir":
        return "salir_menu"
    return "autorizacion_datos"


def _route_volver_menu(state: Any) -> str:
    """Back-navigation out of `mostrar_catalogo`.

    `True` loops back to `elegir_municipio_catalogo` (which re-asks because
    `mostrar_catalogo` just cleared `lugar_eleccion_vivir`); anything else
    proceeds into the qualification flow, carrying the browsing branch's
    `preferencia_vis` and `municipio_normalizado` forward.
    """
    if _profile(state).get("volver_menu_anterior") is True:
        return "elegir_municipio_catalogo"
    return "autorizacion_datos"


# ── Block C: credit-advisor hand-off (``docs/v2-impact-analysis.md`` §7-§8) ──
def _route_handoff(state: Any) -> str:
    """Only a `calificado` lead continues past `handoff` to the credit-advisor
    question and the email notification; `nutrible` and `no_calificado` end
    here, exactly as in Block A.
    """
    if _profile(state).get("status") == "calificado":
        return "recoger_interes_credito"
    return END
