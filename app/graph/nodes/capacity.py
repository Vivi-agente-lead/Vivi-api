"""`recoger_empleo` and the four capacity bundles (`design.md` §4).

The bundles are selected by the two derived predicates `es_empleado` and
`tiene_pareja` — never by a raw source label. `contrato_laboral` holds one of
`termino_fijo` / `termino_indefinido` / `prestacion_servicios`; the literal
`"empleado"` appears nowhere in the source domain.

Three fields are collected in **all four** bundles:
`subsidio_vivienda_anterior`, `numero_pac` and
`condicion_discapacidad_familiar`. The spreadsheet's condition
("Preguntar si es casado o UL") governs the *phrasing* of the prior-subsidy
question — "su pareja" only parses with a partner — not who is eligible to hold
one. Gating the field to casado/union_libre left the absolute disqualifier inert
for every soltero, divorciado, separado and viudo lead, and left the `+8` PAC /
discapacidad bonus and the `cabeza_de_hogar` derivation unreachable on that
branch. The flow diagram asks all three in every bundle; it governs *who* is
asked (`design.md` §13.2).

The three fields that do vary:

* the income field — `total_ingresos_familiares_mensuales` with a partner,
  `total_ingresos_mensuales` without;
* `antiguedad_laboral` — only when `es_empleado`;
* `rango_salarial` — only when `es_empleado` **and** the lead is not an
  affiliate, per the source condition "Preguntar solo si es empleado y NO es
  afiliado Colsubsidio". For an affiliate it is derived from
  `salario_base_cotizacion`.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.graph.nodes._common import Field, collect
from app.graph.nodes._validators import (
    derive_cabeza_de_hogar,
    derive_es_empleado,
    parse_bool_si_no,
    parse_decimal,
    parse_int,
    validate_enumerated,
)

logger = logging.getLogger(__name__)

__all__ = [
    "recoger_empleo",
    "cap_emp_con_pareja",
    "cap_emp_sin_pareja",
    "cap_ind_con_pareja",
    "cap_ind_sin_pareja",
    "CAPACITY_PERSIST_FIELDS",
]

_EMPLEO_FIELDS = (
    Field(
        name="contrato_laboral",
        parse=lambda raw: validate_enumerated("contrato_laboral", raw),
        options_key="contrato_laboral",
    ),
)


def _derive_empleado(profile: dict[str, Any]) -> None:
    profile["es_empleado"] = derive_es_empleado(profile.get("contrato_laboral"))


async def recoger_empleo(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Store the specific contract slug and derive `es_empleado` from it."""
    return await collect(
        state,
        config,
        node="recoger_empleo",
        fields=_EMPLEO_FIELDS,
        finalize=_derive_empleado,
        persist_fields=("contrato_laboral",),
    )


# ── Bundle field definitions ────────────────────────────────────────────────
def _asks_rango_salarial(profile: dict[str, Any]) -> bool:
    """Source condition: "Preguntar solo si es empleado y NO es afiliado"."""
    return bool(profile.get("es_empleado")) and not profile.get("afiliado_colsubsidio")


_INGRESOS_CON_PAREJA = Field(
    name="total_ingresos_familiares_mensuales", parse=parse_decimal
)
_INGRESOS_SIN_PAREJA = Field(name="total_ingresos_mensuales", parse=parse_decimal)

_ANTIGUEDAD = Field(
    name="antiguedad_laboral",
    parse=lambda raw: validate_enumerated("antiguedad_laboral", raw),
    options_key="antiguedad_laboral",
)
_RANGO_SALARIAL = Field(
    name="rango_salarial",
    parse=lambda raw: validate_enumerated("rango_salarial", raw),
    applies=_asks_rango_salarial,
    options_key="rango_salarial",
)

# Collected on every path — see the module docstring.
_COMMON_TAIL = (
    Field(name="tiene_vivienda_propia", parse=parse_bool_si_no),
    Field(
        name="ahorros_o_cesantias",
        parse=lambda raw: validate_enumerated("ahorros_o_cesantias", raw),
        options_key="ahorros_o_cesantias",
    ),
    Field(name="tiene_creditos_activos", parse=parse_bool_si_no),
    Field(name="numero_pac", parse=parse_int),
    Field(name="condicion_discapacidad_familiar", parse=parse_bool_si_no),
)

_SUBSIDIO_CON_PAREJA = Field(
    name="subsidio_vivienda_anterior",
    parse=parse_bool_si_no,
    question_key="subsidio_vivienda_anterior_con_pareja",
)
_SUBSIDIO_SIN_PAREJA = Field(
    name="subsidio_vivienda_anterior", parse=parse_bool_si_no
)

CAPACITY_PERSIST_FIELDS: tuple[str, ...] = (
    "total_ingresos_mensuales",
    "total_ingresos_familiares_mensuales",
    "antiguedad_laboral",
    "rango_salarial",
    "tiene_vivienda_propia",
    "ahorros_o_cesantias",
    "tiene_creditos_activos",
    "subsidio_vivienda_anterior",
    "numero_pac",
    "condicion_discapacidad_familiar",
    "cabeza_de_hogar",
)

_BUNDLES: dict[str, tuple[Field, ...]] = {
    "cap_emp_con_pareja": (
        _INGRESOS_CON_PAREJA,
        _ANTIGUEDAD,
        _RANGO_SALARIAL,
        *_COMMON_TAIL,
        _SUBSIDIO_CON_PAREJA,
    ),
    "cap_emp_sin_pareja": (
        _INGRESOS_SIN_PAREJA,
        _ANTIGUEDAD,
        _RANGO_SALARIAL,
        *_COMMON_TAIL,
        _SUBSIDIO_SIN_PAREJA,
    ),
    "cap_ind_con_pareja": (
        _INGRESOS_CON_PAREJA,
        *_COMMON_TAIL,
        _SUBSIDIO_CON_PAREJA,
    ),
    "cap_ind_sin_pareja": (
        _INGRESOS_SIN_PAREJA,
        *_COMMON_TAIL,
        _SUBSIDIO_SIN_PAREJA,
    ),
}


def _finalize_capacity(profile: dict[str, Any]) -> None:
    """Derive `cabeza_de_hogar` once `numero_pac` is known.

    All four branches converge here, which is the whole reason `numero_pac`
    moved into the bundles.
    """
    if profile.get("numero_pac") is not None:
        profile["cabeza_de_hogar"] = derive_cabeza_de_hogar(profile)


# The source flow's `Ya voy conociendote mejor, vamos con unas preguntas mas`,
# carried by the bundle's first question instead of a dedicated node.
_REASSURANCE = "Ya te voy conociendo mejor. Vamos con unas preguntas más."


async def _run_bundle(
    state: Any, config: RunnableConfig, node: str
) -> dict[str, Any]:
    return await collect(
        state,
        config,
        node=node,
        fields=_BUNDLES[node],
        finalize=_finalize_capacity,
        persist_fields=CAPACITY_PERSIST_FIELDS,
        intro=_REASSURANCE,
    )


async def cap_emp_con_pareja(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Empleado with a partner: household income, antigüedad, rango salarial."""
    return await _run_bundle(state, config, "cap_emp_con_pareja")


async def cap_emp_sin_pareja(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Empleado without a partner: individual income, antigüedad, rango salarial."""
    return await _run_bundle(state, config, "cap_emp_sin_pareja")


async def cap_ind_con_pareja(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Prestación de servicios with a partner: no antigüedad, no rango salarial."""
    return await _run_bundle(state, config, "cap_ind_con_pareja")


async def cap_ind_sin_pareja(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Prestación de servicios without a partner: individual income only."""
    return await _run_bundle(state, config, "cap_ind_sin_pareja")
