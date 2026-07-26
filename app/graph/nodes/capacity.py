"""`recoger_empleo` and the single household capacity block (`docs/v2-impact-analysis.md`).

v2 collapses the four v1 capacity bundles (`cap_emp_con_pareja`,
`cap_emp_sin_pareja`, `cap_ind_con_pareja`, `cap_ind_sin_pareja`) and the
`_route_capacity` predicate that selected among them into a single household
block every lead answers, employed or not, partnered or not:

    ¿Cuanto suman los ingresos de tu hogar? ¿En promedio cuanto suman los
    gastos mensuales de tu hogar? ¿Tu o tu pareja cuenta con vivienda propia?
    ¿Cuantas personas tiene a cargo? ¿Usted o su pareja han recibido
    anteriormente un subsidio de vivienda? ¿Cuentan con ahorros o cesantias
    para iniciar?

`tiene_pareja` and `es_empleado` stop being routing predicates — both are still
derived (bookkeeping/audit only) but no longer pick a bundle. `antiguedad_laboral`
and `condicion_discapacidad_familiar` are dropped outright: absent from the v2
sheet's capacity question. `cabeza_de_hogar`, which depended on
`condicion_discapacidad_familiar`'s sibling `numero_pac` alone, is also
removed — no column, no question, in the v2 sheet.

`tiene_creditos_activos` is likewise no longer asked: neither the v2 flow
diagram's household node nor the v2 workbook's `Leads` sheet carries this
question (a fourth removal `docs/v2-impact-analysis.md` did not enumerate —
see the apply report). The `leads.tiene_creditos_activos` column and the
scorer's `-5` rule both stay in place, dormant: an always-NULL field already
fails the scorer's `is True` check closed, exactly like every other
uncollected boolean.

`rango_salarial` is not asked directly here either — neither the JSON node nor
the workbook's `Leads` sheet header carries a distinct rango_salarial prompt
in v2. Rather than leave Bucket 3 ("Ingreso", 20 pts) silently zeroed for the
entire no-afiliado population the way the old Bucket 6 was before v2's
re-budget, this module derives `rango_salarial` from the collected household
`total_ingresos_mensuales` once the afiliado-only direct derivation
(`app/graph/nodes/spine.py::afiliado_check`, from `salario_base_cotizacion`)
did not already set it — reusing the exact same `derive_rango_salarial` band
boundaries. This is a deliberate interpretation call, not a JSON requirement;
see the apply report.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.graph.nodes._common import Field, collect
from app.graph.nodes._validators import (
    derive_es_empleado,
    derive_rango_salarial,
    parse_bool_si_no,
    parse_decimal,
    parse_int,
    validate_enumerated,
)

logger = logging.getLogger(__name__)

__all__ = ["recoger_empleo", "recoger_capacidad", "CAPACITY_PERSIST_FIELDS"]

_EMPLEO_FIELDS = (
    Field(
        name="contrato_laboral",
        parse=lambda raw: validate_enumerated("contrato_laboral", raw),
        options_key="contrato_laboral",
    ),
)


def _derive_empleado(profile: dict[str, Any]) -> None:
    """Bookkeeping only — no longer a routing predicate (see module docstring)."""
    profile["es_empleado"] = derive_es_empleado(profile.get("contrato_laboral"))


async def recoger_empleo(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Store the specific contract slug and derive `es_empleado`."""
    return await collect(
        state,
        config,
        node="recoger_empleo",
        fields=_EMPLEO_FIELDS,
        finalize=_derive_empleado,
        persist_fields=("contrato_laboral",),
    )


# ── Household capacity block, in the order the v2 flow gives them ──────────
_CAPACITY_FIELDS: tuple[Field, ...] = (
    Field(name="total_ingresos_mensuales", parse=parse_decimal),
    Field(name="gastos_mensuales", parse=parse_decimal),
    Field(name="tiene_vivienda_propia", parse=parse_bool_si_no),
    Field(name="numero_pac", parse=parse_int),
    Field(name="subsidio_vivienda_anterior", parse=parse_bool_si_no),
    Field(
        name="ahorros_o_cesantias",
        parse=lambda raw: validate_enumerated("ahorros_o_cesantias", raw),
        options_key="ahorros_o_cesantias",
    ),
)

CAPACITY_PERSIST_FIELDS: tuple[str, ...] = (
    "total_ingresos_mensuales",
    "gastos_mensuales",
    "tiene_vivienda_propia",
    "numero_pac",
    "subsidio_vivienda_anterior",
    "ahorros_o_cesantias",
    "rango_salarial",
)

# The source flow's `Ya voy conociendote mejor, vamos con unas preguntas mas`,
# carried by the block's first question instead of a dedicated node.
_REASSURANCE = "Ya te voy conociendo mejor. Vamos con unas preguntas más."


def _finalize_capacidad(profile: dict[str, Any]) -> None:
    """Derive `rango_salarial` from household income when not already known.

    An afiliado's `rango_salarial` is already set in `afiliado_check` from
    `salario_base_cotizacion`; this only ever fires for a no-afiliado, once
    `total_ingresos_mensuales` is answered.
    """
    if profile.get("rango_salarial") is None:
        derived = derive_rango_salarial(profile.get("total_ingresos_mensuales"))
        if derived is not None:
            profile["rango_salarial"] = derived


async def recoger_capacidad(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """The single household capacity block every lead answers."""
    return await collect(
        state,
        config,
        node="recoger_capacidad",
        fields=_CAPACITY_FIELDS,
        finalize=_finalize_capacidad,
        persist_fields=CAPACITY_PERSIST_FIELDS,
        intro=_REASSURANCE,
    )
