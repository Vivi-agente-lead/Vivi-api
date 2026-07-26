"""Register and completeness guards for the per-node prompt slices.

Closes DOC-001. The previous design revision shipped slice text mixing
Rioplatense voseo with German and Portuguese fragments (`Gespräch`, `atualizá`,
`pregunts`), and the ReAct-era `system.py` persona sold apartments in voseo. Both
are behaviour, not cosmetics: an enumerated question whose option list is not
printed verbatim produces an answer `domain_normalizer` cannot map, the field is
written NULL, and the scorer's bucket silently contributes 0.
"""

from __future__ import annotations

import pytest

from app.prompts.slices import FIELD_OPTIONS, FIELD_QUESTIONS, SHARED_PREAMBLE, SLICES
from app.prompts.system import render_system_prompt

REQUIRED_SLICES = (
    "start",
    "autorizacion_datos",
    "pedir_cedula",
    "recoger_identidad",
    "recoger_estado_civil",
    "recoger_interes_afiliacion",
    "recoger_empleo",
    "recoger_capacidad",
    "recoger_intencion",
    "handoff_calificado",
    "handoff_nutrible",
    "handoff_no_calificado",
    "farewell_underage",
    "farewell_optout",
)

# Rioplatense imperatives and pronouns, plus the fragments of other languages the
# audit found in the previous revision.
FORBIDDEN = (
    "preguntá",
    "actualizá",
    "confirmá",
    "atualizá",
    "respondé",
    "hablás",
    "tenés",
    "podés",
    "querés",
    "sos vivi",
    "gespräch",
    "pregunts",
    "laconfirmation",
)


def _all_prompt_text() -> dict[str, str]:
    texts = {f"SLICES[{key}]": value for key, value in SLICES.items()}
    texts.update({f"FIELD_QUESTIONS[{k}]": v for k, v in FIELD_QUESTIONS.items()})
    texts["SHARED_PREAMBLE"] = SHARED_PREAMBLE
    texts["legacy_system_prompt"] = render_system_prompt()
    return texts


@pytest.mark.parametrize("node", REQUIRED_SLICES)
def test_every_node_of_the_topology_has_a_slice(node: str) -> None:
    assert SLICES.get(node, "").strip(), f"missing slice for node {node}"


@pytest.mark.parametrize("token", FORBIDDEN)
def test_no_voseo_and_no_foreign_fragments(token: str) -> None:
    offenders = [
        name for name, text in _all_prompt_text().items() if token in text.lower()
    ]
    assert not offenders, f"{token!r} found in {offenders}"


@pytest.mark.parametrize("field", sorted(FIELD_OPTIONS))
def test_enumerated_questions_print_the_source_options_verbatim(field: str) -> None:
    """An option the person never saw cannot come back normalizable."""
    question = FIELD_QUESTIONS[field]
    for option in FIELD_OPTIONS[field]:
        assert option in question, f"{field}: option {option!r} not shown"


def test_every_slice_declares_an_objective_and_a_style() -> None:
    for node, text in SLICES.items():
        assert "## Objetivo" in text, f"{node} has no Objetivo section"
        assert "## Estilo" in text, f"{node} has no Estilo section"


def test_capacidad_slice_collects_the_absolute_disqualifier() -> None:
    """`subsidio_vivienda_anterior` and `numero_pac` are collected of every lead —
    the single household block every branch now converges on."""
    text = SLICES["recoger_capacidad"]
    assert "subsidio_vivienda_anterior" in text
    assert "numero_pac" in text
    assert "total_ingresos_mensuales" in text
    assert "gastos_mensuales" in text


def test_capacidad_slice_does_not_mention_removed_fields() -> None:
    """v2 drops `antiguedad_laboral`, `condicion_discapacidad_familiar` and
    `cabeza_de_hogar` outright — no lingering mention in the one remaining
    capacity slice."""
    text = SLICES["recoger_capacidad"]
    assert "condicion_discapacidad_familiar" not in text
    assert "cabeza_de_hogar" not in text


def test_render_system_prompt_composes_preamble_slice_and_profile() -> None:
    rendered = render_system_prompt(
        "recoger_estado_civil", lead_profile={"nombre_apellido": "Andrea Marín"}
    )
    assert SHARED_PREAMBLE.strip() in rendered
    assert "Union libre" in rendered
    assert "Andrea Marín" in rendered


def test_render_system_prompt_hides_the_raw_affiliate_record() -> None:
    rendered = render_system_prompt(
        "recoger_empleo", lead_profile={"afiliado_record": {"secreto": 1}}
    )
    assert "secreto" not in rendered
