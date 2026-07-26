"""Conditional-edge predicate tests for the lead-profiling graph.

Covers task 4.2/4.3 and the `leads-conversational-flow` scenarios *Menor de edad
… no-afiliado path*, *Menor de edad … afiliado path*, *Terminal routing uses the
LangGraph END sentinel*, *Afiliado branch skips identidad, otra_caja, edad* and
*Pareja vs sin-pareja income fields*.

Why these tests drive a **compiled graph** instead of only comparing return
values: LangGraph accepts an unregistered destination silently. A predicate that
returns the literal string ``"END"`` (or any typo'd node id) makes the runtime
log ``wrote to unknown channel branch:to:END, ignoring it`` and simply stop — no
exception, no failed assertion if the test only inspects the returned value. So
every case below asserts the **traversal** the predicate produced, and the
terminal cases additionally assert that LangGraph logged no unknown-channel
warning, which is the only observable difference between the real ``END``
sentinel and a string that merely looks like it.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Callable, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from app.graph.nodes._validators import derive_es_empleado, derive_tiene_pareja
from app.graph.router import (
    MINIMUM_AGE,
    _route_afiliado,
    _route_autorizacion,
    _route_capacity,
    _route_edad,
    _route_otra_caja,
)

# Every destination any predicate under test can return.
_DESTINATIONS: tuple[str, ...] = (
    "pedir_cedula",
    "recoger_identidad",
    "recoger_estado_civil",
    "recoger_otra_caja",
    "recoger_empleo",
    "cap_emp_con_pareja",
    "cap_emp_sin_pareja",
    "cap_ind_con_pareja",
    "cap_ind_sin_pareja",
)


def _append(left: list[str] | None, right: list[str] | None) -> list[str]:
    return (left or []) + (right or [])


class _ProbeState(TypedDict, total=False):
    """Minimal state carrying what the predicates read plus a visit trail."""

    lead_profile: dict
    trail: Annotated[list[str], _append]


def _recorder(name: str) -> Callable[[_ProbeState], dict[str, Any]]:
    async def _node(state: _ProbeState) -> dict[str, Any]:
        return {"trail": [name]}

    return _node


def _compile_probe(predicate: Callable[[Any], str]):
    """A graph of `source -> predicate -> every possible destination`."""
    graph = StateGraph(_ProbeState)
    graph.add_node("source", _recorder("source"))
    for destination in _DESTINATIONS:
        graph.add_node(destination, _recorder(destination))
        graph.add_edge(destination, END)
    graph.add_edge(START, "source")
    graph.add_conditional_edges("source", predicate)
    return graph.compile()


async def _traverse(
    predicate: Callable[[Any], str],
    profile: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> list[str]:
    """Run the probe graph and return the visited node trail.

    Asserts LangGraph never fell back to its silent unknown-channel path, which
    is what a `return "END"` defect looks like from the outside.
    """
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="langgraph"):
        result = await _compile_probe(predicate).ainvoke({"lead_profile": profile})
    assert "unknown channel" not in caplog.text, (
        "the predicate returned a destination LangGraph does not know; it was "
        f"ignored silently. Log: {caplog.text}"
    )
    return result["trail"]


# ── Consent gate ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ({"autorizacion_datos": True}, ["source", "pedir_cedula"]),
        ({"autorizacion_datos": False}, ["source"]),
        ({}, ["source"]),
    ],
    ids=["autoriza", "rechaza", "sin_respuesta"],
)
async def test_route_autorizacion_traversal(profile, expected, caplog):
    assert await _traverse(_route_autorizacion, profile, caplog) == expected


def test_route_autorizacion_terminates_with_the_imported_sentinel():
    assert _route_autorizacion({"lead_profile": {"autorizacion_datos": False}}) is END


# ── Affiliation branch + afiliado-side underage gate ────────────────────────
@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ({"afiliado_colsubsidio": False}, ["source", "recoger_identidad"]),
        ({}, ["source", "recoger_identidad"]),
        (
            {"afiliado_colsubsidio": True, "edad": 30},
            ["source", "recoger_estado_civil"],
        ),
        (
            {"afiliado_colsubsidio": True, "edad": MINIMUM_AGE},
            ["source", "recoger_estado_civil"],
        ),
        ({"afiliado_colsubsidio": True, "edad": 17}, ["source"]),
        ({"afiliado_colsubsidio": True, "edad": None}, ["source"]),
        ({"afiliado_colsubsidio": True}, ["source"]),
    ],
    ids=[
        "no_afiliado",
        "afiliacion_desconocida",
        "afiliado_adulto",
        "afiliado_justo_18",
        "afiliado_menor",
        "afiliado_edad_nula",
        "afiliado_sin_edad",
    ],
)
async def test_route_afiliado_traversal(profile, expected, caplog):
    assert await _traverse(_route_afiliado, profile, caplog) == expected


def test_route_afiliado_underage_returns_the_imported_sentinel():
    state = {"lead_profile": {"afiliado_colsubsidio": True, "edad": 17}}
    assert _route_afiliado(state) is END


# ── No-afiliado underage gate ───────────────────────────────────────────────
@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ({"edad": 41}, ["source", "recoger_estado_civil"]),
        ({"edad": MINIMUM_AGE}, ["source", "recoger_estado_civil"]),
        ({"edad": 17}, ["source"]),
        ({"edad": 0}, ["source"]),
        ({"edad": None}, ["source"]),
        ({}, ["source"]),
    ],
    ids=["adulto", "justo_18", "menor", "cero", "edad_nula", "sin_edad"],
)
async def test_route_edad_traversal(profile, expected, caplog):
    assert await _traverse(_route_edad, profile, caplog) == expected


def test_route_edad_unknown_age_returns_the_imported_sentinel():
    assert _route_edad({"lead_profile": {}}) is END


# ── Otra caja de compensación (no-afiliado only) ────────────────────────────
@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ({"afiliado_colsubsidio": True}, ["source", "recoger_empleo"]),
        ({"afiliado_colsubsidio": False}, ["source", "recoger_otra_caja"]),
        ({}, ["source", "recoger_otra_caja"]),
    ],
    ids=["afiliado_salta", "no_afiliado_pregunta", "desconocido_pregunta"],
)
async def test_route_otra_caja_traversal(profile, expected, caplog):
    assert await _traverse(_route_otra_caja, profile, caplog) == expected


# ── Capacity bundle selection ───────────────────────────────────────────────
@pytest.mark.parametrize(
    ("contrato", "estado_civil", "expected_bundle"),
    [
        ("termino_indefinido", "casado", "cap_emp_con_pareja"),
        ("termino_fijo", "union_libre", "cap_emp_con_pareja"),
        ("termino_indefinido", "soltero", "cap_emp_sin_pareja"),
        ("termino_fijo", "divorciado", "cap_emp_sin_pareja"),
        ("termino_indefinido", "separado", "cap_emp_sin_pareja"),
        ("termino_fijo", "viudo", "cap_emp_sin_pareja"),
        ("prestacion_servicios", "casado", "cap_ind_con_pareja"),
        ("prestacion_servicios", "union_libre", "cap_ind_con_pareja"),
        ("prestacion_servicios", "soltero", "cap_ind_sin_pareja"),
        ("prestacion_servicios", "divorciado", "cap_ind_sin_pareja"),
        ("prestacion_servicios", "separado", "cap_ind_sin_pareja"),
        ("prestacion_servicios", "viudo", "cap_ind_sin_pareja"),
    ],
)
async def test_route_capacity_traversal(contrato, estado_civil, expected_bundle, caplog):
    profile = {
        "contrato_laboral": contrato,
        "es_empleado": derive_es_empleado(contrato),
        "estado_civil": estado_civil,
        "tiene_pareja": derive_tiene_pareja(estado_civil),
    }
    assert await _traverse(_route_capacity, profile, caplog) == ["source", expected_bundle]


async def test_route_capacity_defaults_to_independiente_sin_pareja(caplog):
    """Unknown employment and marital status must still reach a real bundle.

    The bundle is where `subsidio_vivienda_anterior`, `numero_pac` and
    `condicion_discapacidad_familiar` are collected, so no lead may fall off the
    graph here.
    """
    assert await _traverse(_route_capacity, {}, caplog) == ["source", "cap_ind_sin_pareja"]


def test_route_capacity_never_reads_the_literal_empleado():
    """`"empleado"` appears nowhere in the source `contrato_laboral` domain."""
    profile = {"contrato_laboral": "empleado", "es_empleado": derive_es_empleado("empleado")}
    assert _route_capacity({"lead_profile": profile}) == "cap_ind_sin_pareja"


# ── Derived predicates ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("estado_civil", "expected"),
    [
        ("casado", True),
        ("union_libre", True),
        ("soltero", False),
        ("divorciado", False),
        ("separado", False),
        ("viudo", False),
        (None, False),
        ("cualquier_cosa", False),
    ],
)
def test_derive_tiene_pareja(estado_civil, expected):
    assert derive_tiene_pareja(estado_civil) is expected


@pytest.mark.parametrize(
    ("contrato", "expected"),
    [
        ("termino_fijo", True),
        ("termino_indefinido", True),
        ("prestacion_servicios", False),
        ("empleado", False),
        (None, False),
    ],
)
def test_derive_es_empleado(contrato, expected):
    assert derive_es_empleado(contrato) is expected
