"""Conditional-edge predicates for the lead-profiling StateGraph.

`design.md` §3. Names are kept verbatim from the design (leading underscore
included) so the topology can be diffed against the artifact; they are exported
through `__all__` because `app/graph/builder.py` and the router tests are their
only consumers.

Two invariants this module exists to hold:

1. **Terminal returns use the `END` sentinel imported from `langgraph.graph`,
   never the literal string `"END"`.** LangGraph resolves an unregistered
   destination by logging `wrote to unknown channel …, ignoring it` and stopping
   — silently. A wrong sentinel therefore *looks* like it works, which is how the
   defect survived the previous design revision.
2. **`edad is None` routes to `END` in both age gates.** An unknown age is not an
   adult, on either branch.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END

__all__ = [
    "MINIMUM_AGE",
    "_route_autorizacion",
    "_route_afiliado",
    "_route_edad",
    "_route_otra_caja",
    "_route_capacity",
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

    `edad` is computed server-side from `fecha_nacimiento` by
    `recoger_identidad`; it is never taken from the LLM.
    """
    edad = _profile(state).get("edad")
    if edad is None or edad < MINIMUM_AGE:
        return END
    return "recoger_estado_civil"


def _route_otra_caja(state: Any) -> str:
    """Only a no-afiliado is asked about another caja de compensación."""
    if _profile(state).get("afiliado_colsubsidio"):
        return "recoger_empleo"
    return "recoger_otra_caja"


def _route_capacity(state: Any) -> str:
    """Bundle selection from two derived predicates, never from raw source labels.

    `contrato_laboral` holds one of `termino_fijo` / `termino_indefinido` /
    `prestacion_servicios`; the literal `"empleado"` appears nowhere in the
    source domain, so the routing reads the derived `es_empleado` flag instead.
    Both predicates fail closed to the `cap_ind_sin_pareja` bundle — every branch
    must still reach a bundle, because that is where
    `subsidio_vivienda_anterior`, `numero_pac` and
    `condicion_discapacidad_familiar` are collected.
    """
    profile = _profile(state)
    empleo = "emp" if profile.get("es_empleado") else "ind"
    pareja = "con_pareja" if profile.get("tiene_pareja") else "sin_pareja"
    return f"cap_{empleo}_{pareja}"
