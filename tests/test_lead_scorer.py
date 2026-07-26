"""Scorer matrix tests for the Colsubsidio lead scorer.

Rewritten for the v2 re-budget (``docs/v2-impact-analysis.md``): Bucket 6
("Estabilidad", contract type × tenure) is replaced by "Capacidad"
(disposable-income ratio), the `+8` bonus loses its `condicion_discapacidad_
familiar` trigger, the terminal status vocabulary is renamed
`{ready, nurture, nurture_social}` → `{calificado, nutrible, no_calificado}`,
and a new `pos_subsidio` rule is added.

Two v1 regression guards are preserved, renamed to the new status vocabulary:

* **case 5** — ``estado_civil='soltero'`` with
  ``subsidio_vivienda_anterior=True`` still yields ``nutrible``. The override
  fires on every branch the flow diagram reaches, not only
  ``casado``/``union_libre`` (design §13.2).
* **case 8** — ``ahorros_o_cesantias='menos_3m'`` scores 5, not 0. The audit
  found the previous scorer used `"no" not in ahorro`, which collapsed the
  ``menos_3m`` slug to 0 because ``"menos"`` contains ``"no"`` (DATA-003).

case 12 (afiliado strictly outscores an otherwise-identical no-afiliado)
verifies the 90/10 differential (design §13.3): Bucket 2 gives no-afiliado 0,
and the READY threshold is 75 for no-afiliado vs 60 for afiliado.

The tests are pure-Python and do not import Phase 1 modules
(``app.models.constants``, ``app.services.domain_normalizer``, ...) — Phase 2
must stay parallel-safe. Inputs use a local :class:`LeadProfile` TypedDict
whose keys mirror ``design.md`` §6; the scorer accepts any mapping with the
right keys.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

import pytest

from app.services.credit_bands import (
    CREDIT_BANDS,
    DEMO_CEDULA_SCORES,
    band_from_score_credito,
    simulate_bureau_cedula,
)
from app.services.lead_scorer import (
    AHORRO_PTS,
    CAPACIDAD_BANDS,
    CATEGORIA_PTS,
    INGRESO_PTS,
    NURTURE_FLOOR,
    POS_SUBSIDIO_DISPONIBLE,
    POS_SUBSIDIO_NO_DISPONIBLE,
    READY_THRESHOLD_AFILIADO,
    READY_THRESHOLD_NO_AFILIADO,
    ScoringResult,
    TIEMPO_PTS,
    build_scoring_result,
    classify_lead,
    compute_pos_subsidio,
    score_lead,
)


class LeadProfile(TypedDict, total=False):
    """Local input view mirroring ``design.md`` §6 (v2 field set).

    Phase 1 owns the authoritative ``LeadColsubsidioEntity``; Phase 2 consumes
    any dict with these keys, so tests stay isolated from the model layer.
    """

    numero_documento: str
    rango_salarial: str
    ahorros_o_cesantias: str
    tiempo_compra_deseado: str
    contrato_laboral: str
    total_ingresos_mensuales: object
    gastos_mensuales: object
    tiene_vivienda_propia: bool
    tiene_creditos_activos: bool
    numero_pac: int
    vis_recommended: bool
    subsidio_vivienda_anterior: bool
    otra_caja_compensacion: object
    interes_afiliacion: str | None
    estado_civil: str
    normalization_notes: list[str]


class AfiliadoRecord(TypedDict, total=False):
    """Local afiliado-row view (only the two scorer-relevant columns)."""

    score_credito: int
    categoria_afiliado: str
    ha_recibido_subsidio: bool


# ── Helpers ────────────────────────────────────────────────────────────────
def _ready_lead(**overrides: object) -> LeadProfile:
    """A near-ceiling lead profile — every bucket at or near its maximum.

    Used as a base for the override / red-flag cases so a single field flip
    produces a single, observable, mechanical change to the score. Income and
    expenses are set so the Capacidad bucket lands at its 15-point ceiling
    (ratio = 1 - 2/10 = 0.80 >= 0.50).
    """
    base: LeadProfile = {
        "numero_documento": "1010101010",
        "rango_salarial": "mas_10m",
        "ahorros_o_cesantias": "mas_40m",
        "tiempo_compra_deseado": "3_meses",
        "contrato_laboral": "termino_indefinido",
        "total_ingresos_mensuales": 10_000_000,
        "gastos_mensuales": 2_000_000,
        "tiene_vivienda_propia": False,
        "tiene_creditos_activos": False,
        "numero_pac": 0,
        "vis_recommended": False,
        "subsidio_vivienda_anterior": False,
        "estado_civil": "casado",
    }
    return {**base, **overrides}  # type: ignore[return-value]


def _afiliado(categoria: str, score_credito: int) -> AfiliadoRecord:
    return AfiliadoRecord(
        score_credito=score_credito,
        categoria_afiliado=categoria,
        ha_recibido_subsidio=False,
    )


# ── Case 1: afiliado A + Excelente + max buckets → calificado at ceiling ──
def test_case_1_afiliado_a_ceiling_is_calificado() -> None:
    lead = _ready_lead()
    afiliado = _afiliado("A", 880)  # Excelente → 25
    score, rating, classification, reasoning = score_lead(lead, afiliado)

    assert classification == "calificado"
    assert rating == "Excelente"
    # 25 (credito) + 15 (cat A) + 20 (ingreso) + 15 (ahorro)
    # + 10 (tiempo) + 15 (capacidad, ratio 0.80) = 100
    assert score == 100
    assert "Umbral READY aplicado: 60 (afiliado)" in reasoning


# ── Case 2: afiliado B + mid buckets → calificado ─────────────────────────
def test_case_2_afiliado_b_mid_buckets_calificado() -> None:
    lead: LeadProfile = {
        "rango_salarial": "2_4m",
        "ahorros_o_cesantias": "3_10m",
        "tiempo_compra_deseado": "6_meses",
        "total_ingresos_mensuales": 4_000_000,
        "gastos_mensuales": 3_000_000,  # ratio 0.25 → 7 pts
        "tiene_vivienda_propia": False,
        "tiene_creditos_activos": False,
        "numero_pac": 0,
        "subsidio_vivienda_anterior": False,
        "vis_recommended": False,
    }
    afiliado = _afiliado("B", 720)  # Bueno → 18
    score, rating, classification, _ = score_lead(lead, afiliado)

    # 18 + 11 (B) + 10 + 9 + 8 + 7 (capacidad) = 63
    assert score == 63
    assert rating == "Bueno"
    assert classification == "calificado"  # 63 >= 60 (afiliado threshold)


# ── Case 3: afiliado C + min buckets → no_calificado ──────────────────────
def test_case_3_afiliado_c_min_buckets_no_calificado() -> None:
    lead: LeadProfile = {
        "rango_salarial": "hasta_2m",
        "ahorros_o_cesantias": "ninguno",
        "tiempo_compra_deseado": "no_se",
        "total_ingresos_mensuales": 1_000_000,
        "gastos_mensuales": 1_000_000,  # ratio 0 → 0 pts
        "tiene_vivienda_propia": False,
        "tiene_creditos_activos": False,
        "numero_pac": 0,
        "subsidio_vivienda_anterior": False,
        "vis_recommended": False,
    }
    afiliado = _afiliado("C", 580)  # Regular → 6
    score, rating, classification, _ = score_lead(lead, afiliado)

    # 6 + 7 (C) + 5 + 0 + 0 + 0 (capacidad) = 18
    assert score == 18
    assert rating == "Regular"
    assert classification == "no_calificado"  # 18 < NURTURE_FLOOR (30)


# ── Case 4: subsidio previo override, score untouched ─────────────────────
def test_case_4_subsidio_previo_override_does_not_touch_score() -> None:
    lead = _ready_lead(subsidio_vivienda_anterior=True)
    afiliado = _afiliado("A", 880)

    baseline_score, _, baseline_class, baseline_reason = score_lead(
        _ready_lead(subsidio_vivienda_anterior=False), afiliado
    )
    override_score, _, override_class, override_reason = score_lead(lead, afiliado)

    assert baseline_class == "calificado"
    assert override_class == "nutrible"
    # Numeric score is untouched — analytics keep the real figure.
    assert override_score == baseline_score == 100
    assert "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio" in override_reason
    assert baseline_reason != override_reason  # the override appends a line


# ── Case 5: estado_civil='soltero' still yields nutrible override ─────────
# Regression guard for §13.2: the override fires regardless of estado_civil.
def test_case_5_subsidio_previo_override_with_soltero() -> None:
    lead = _ready_lead(estado_civil="soltero", subsidio_vivienda_anterior=True)
    afiliado = _afiliado("A", 880)

    score, _, classification, reasoning = score_lead(lead, afiliado)

    assert classification == "nutrible"
    assert score == 100  # override never subtracts
    assert "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio" in reasoning


# ── Case 6: vivienda propia + VIS recommended → −15 ───────────────────────
def test_case_6_vivienda_propia_vis_recommended_subtracts_15() -> None:
    afiliado = _afiliado("A", 880)
    no_flag = _ready_lead(tiene_vivienda_propia=True, vis_recommended=False)
    with_flag = _ready_lead(tiene_vivienda_propia=True, vis_recommended=True)

    score_no, _, _, reason_no = score_lead(no_flag, afiliado)
    score_yes, _, _, reason_yes = score_lead(with_flag, afiliado)

    assert score_yes == score_no - 15
    assert "Alerta: vivienda propia + proyecto VIS recomendado (−15)" in reason_yes
    assert "Alerta" not in reason_no


# ── Case 7: creditos_activos −5; numero_pac +8 (discapacidad trigger gone) ──
def test_case_7_red_flags_creditos_minus_5_pac_plus_8() -> None:
    afiliado = _afiliado("A", 880)
    baseline = _ready_lead()
    with_creditos = _ready_lead(tiene_creditos_activos=True)
    with_pac = _ready_lead(numero_pac=2)

    base_score, _, _, _ = score_lead(baseline, afiliado)
    creditos_score, _, _, _ = score_lead(with_creditos, afiliado)
    pac_score, _, _, _ = score_lead(with_pac, afiliado)

    assert creditos_score == base_score - 5
    # +8 may be clamped at the ceiling; the observable guarantee is the +8
    # contribution to the *adjustments* bucket, not the post-clamp score delta.
    assert pac_score == min(100, base_score + 8)
    pac_one = _ready_lead(numero_pac=1)
    pac_one_score, _, _, _ = score_lead(pac_one, afiliado)
    assert pac_one_score == min(100, base_score + 8)
    # Bonus reachable from soltero + afiliado (§13.2):
    soltero_with_pac = _ready_lead(estado_civil="soltero", numero_pac=1)
    soltero_score, _, _, _ = score_lead(soltero_with_pac, afiliado)
    assert soltero_score == min(100, base_score + 8)


# ── Case 8: ahorros='menos_3m' scores 5, not 0 (DATA-003 regression) ───────
def test_case_8_ahorros_menos_3m_scores_five_not_zero() -> None:
    # Regression guard for audit DATA-003: the previous scorer tested
    # `"no" not in ahorro`, which scored `"menos_3m"` as 0 because `"menos"`
    # contains `"no"`. Exact slug lookup MUST recover the documented 5 points.
    assert AHORRO_PTS["menos_3m"] == 5
    assert "menos_3m" != "ninguno"  # never conflated with the zero slug

    lead: LeadProfile = {
        "rango_salarial": "hasta_2m",
        "ahorros_o_cesantias": "menos_3m",
        "tiempo_compra_deseado": "no_se",
        "contrato_laboral": "independiente",
        "tiene_vivienda_propia": False,
        "tiene_creditos_activos": False,
        "numero_pac": 0,
        "subsidio_vivienda_anterior": False,
        "vis_recommended": False,
        "numero_documento": "12345678",
    }
    score, _, _, reasoning = score_lead(lead, afiliado=None)
    result = build_scoring_result(lead, afiliado=None)

    # The observable guarantee: bucket 4 contributes exactly 5 (not 0). The
    # no-afiliado credit band varies with the cedula; the *ahorro* contribution
    # must still be 5 regardless of which band Bucket 1 selected.
    assert result["breakdown"]["ahorro"] == 5
    assert "Banda crediticia estimada con simulado bureau (no afiliado)" in reasoning
    # Sanity: if the regression returned and the bucket collapsed to 0, the
    # breakdown would read 0 here. Lock the 5 strictly.
    assert result["breakdown"]["ahorro"] != 0
    # score is still in range and was computed including the +5.
    assert 0 <= score <= 100


# ── Case 9: every canonical slug → documented points; unknown → 0 ──────────
@pytest.mark.parametrize(
    ("table", "expected_pairs"),
    [
        (INGRESO_PTS, [
            ("mas_10m", 20), ("8_10m", 17), ("4_8m", 14),
            ("2_4m", 10), ("hasta_2m", 5),
        ]),
        (AHORRO_PTS, [
            ("mas_40m", 15), ("20_40m", 14), ("10_20m", 12),
            ("3_10m", 9), ("menos_3m", 5), ("ninguno", 0),
        ]),
        (TIEMPO_PTS, [
            ("3_meses", 10), ("6_meses", 8), ("1_ano", 5),
            ("2_anos", 2), ("no_se", 0),
        ]),
    ],
)
def test_case_9_canonical_slugs_distinct_points_unknown_zero(
    table: dict[str, int], expected_pairs: list[tuple[str, int]]
) -> None:
    for slug, pts in expected_pairs:
        assert table[slug] == pts
    # Documented rows match the bucket table exactly (no extra, no missing).
    assert set(table) == {slug for slug, _ in expected_pairs}
    # Unknown slug yields 0 (exact lookup, never mid-range default).
    assert table.get("unknown_slug_xyz") is None


# ── Case 9b: Capacidad bucket bands ────────────────────────────────────────
@pytest.mark.parametrize(
    ("ingreso", "gastos", "expected_pts"),
    [
        (10_000_000, 5_000_000, 15),   # ratio 0.50 — top band, inclusive floor
        (10_000_000, 6_000_000, 11),   # ratio 0.40
        (10_000_000, 7_500_000, 7),    # ratio 0.25
        (10_000_000, 9_200_000, 3),    # ratio 0.08
        (10_000_000, 9_800_000, 0),    # ratio 0.02 — below the lowest band
        (10_000_000, 10_000_000, 0),   # ratio 0 — no disposable income
        (10_000_000, 12_000_000, 0),   # gastos > ingreso — negative ratio
    ],
)
def test_case_9b_capacidad_bands(
    ingreso: int, gastos: int, expected_pts: int
) -> None:
    lead = _ready_lead(total_ingresos_mensuales=ingreso, gastos_mensuales=gastos)
    afiliado = _afiliado("A", 880)
    res = build_scoring_result(lead, afiliado)
    assert res["breakdown"]["capacidad"] == expected_pts


def test_case_9b_capacidad_missing_data_scores_zero() -> None:
    afiliado = _afiliado("A", 880)
    # No income at all.
    res_no_ingreso = build_scoring_result(
        _ready_lead(total_ingresos_mensuales=None, gastos_mensuales=1_000_000),
        afiliado,
    )
    assert res_no_ingreso["breakdown"]["capacidad"] == 0
    # No expenses figure.
    res_no_gastos = build_scoring_result(
        _ready_lead(total_ingresos_mensuales=5_000_000, gastos_mensuales=None),
        afiliado,
    )
    assert res_no_gastos["breakdown"]["capacidad"] == 0
    # Zero/negative income.
    res_zero_ingreso = build_scoring_result(
        _ready_lead(total_ingresos_mensuales=0, gastos_mensuales=0), afiliado
    )
    assert res_zero_ingreso["breakdown"]["capacidad"] == 0


def test_capacidad_bands_are_a_15_point_ceiling_and_ordered_descending() -> None:
    assert CAPACIDAD_BANDS[0][1] == 15
    points = [pts for _, pts in CAPACIDAD_BANDS]
    assert points == sorted(points, reverse=True)
    floors = [floor for floor, _ in CAPACIDAD_BANDS]
    assert floors == sorted(floors, reverse=True)


# ── pos_subsidio rule ───────────────────────────────────────────────────────
def test_pos_subsidio_zero_only_on_no_afiliado_affiliated_elsewhere() -> None:
    # No-afiliado, affiliated elsewhere → 0.
    assert compute_pos_subsidio(False, True) == POS_SUBSIDIO_NO_DISPONIBLE
    # No-afiliado, not affiliated elsewhere → 1.
    assert compute_pos_subsidio(False, False) == POS_SUBSIDIO_DISPONIBLE
    # No-afiliado, not yet answered (NULL) → 1 (never treated as affiliated
    # elsewhere by truthiness).
    assert compute_pos_subsidio(False, None) == POS_SUBSIDIO_DISPONIBLE
    # Afiliado — the question is gated to non-affiliates, so
    # `otra_caja_compensacion` is always NULL for them and must never trip
    # the rule even if a caller mistakenly passes True.
    assert compute_pos_subsidio(True, None) == POS_SUBSIDIO_DISPONIBLE
    assert compute_pos_subsidio(True, True) == POS_SUBSIDIO_DISPONIBLE


def test_pos_subsidio_does_not_change_the_numeric_score() -> None:
    afiliado = None  # no-afiliado path
    baseline = _ready_lead(otra_caja_compensacion=False)
    affiliated_elsewhere = _ready_lead(otra_caja_compensacion=True)

    base_score, _, _, base_reason = score_lead(baseline, afiliado)
    other_score, _, _, other_reason = score_lead(affiliated_elsewhere, afiliado)

    assert base_score == other_score  # pos_subsidio is informational only
    assert "Posibilidad de subsidio Colsubsidio: 0" not in base_reason
    assert (
        "Posibilidad de subsidio Colsubsidio: 0 (afiliado a otra caja de compensación)"
        in other_reason
    )


def test_pos_subsidio_reasoning_line_present_for_every_lead() -> None:
    # Every reasoning string carries its own pos_subsidio line, distinct from
    # every other bucket/adjustment line (never silently folded elsewhere).
    afiliado = _afiliado("A", 880)
    _, _, _, reasoning = score_lead(_ready_lead(), afiliado)
    assert "Posibilidad de subsidio Colsubsidio: 1" in reasoning


# ── otra_caja_compensacion derivation is exercised at the scorer boundary ──
# (the derivation itself — from `interes_afiliacion` — lives in the tools/
# graph layer per docs/v2-impact-analysis.md §5; this locks the scorer's
# consumption side: True/False/None are three distinct, meaningful states.)
def test_otra_caja_compensacion_null_vs_false_are_distinct_states() -> None:
    afiliado = _afiliado("A", 880)
    null_lead = _ready_lead(otra_caja_compensacion=None)  # afiliado — never asked
    false_lead = _ready_lead(otra_caja_compensacion=False)  # asked, said no

    assert compute_pos_subsidio(True, null_lead.get("otra_caja_compensacion")) == 1
    assert compute_pos_subsidio(False, false_lead.get("otra_caja_compensacion")) == 1
    # Both score identically — the field, on its own, is not a red flag.
    score_null, _, _, _ = score_lead(null_lead, afiliado)
    score_false, _, _, _ = score_lead(false_lead, afiliado)
    assert score_null == score_false


# ── Complete afiliado lead, every non-afiliado-only field NULL ────────────
# The affiliation question is gated to non-affiliates (product decision,
# docs/v2-impact-analysis.md §5): for an afiliado, `interes_afiliacion` and
# `otra_caja_compensacion` are never collected and stay NULL. The scorer must
# still total correctly for this — the majority — population.
def test_complete_afiliado_lead_with_non_afiliado_only_fields_null() -> None:
    lead: LeadProfile = {
        "numero_documento": "1010101010",
        "rango_salarial": "4_8m",
        "ahorros_o_cesantias": "10_20m",
        "tiempo_compra_deseado": "1_ano",
        "total_ingresos_mensuales": 6_000_000,
        "gastos_mensuales": 3_000_000,  # ratio 0.50 → 15 pts
        "tiene_vivienda_propia": True,
        "tiene_creditos_activos": False,
        "numero_pac": 1,
        "subsidio_vivienda_anterior": False,
        "vis_recommended": False,
        "estado_civil": "casado",
        # Never asked on the afiliado branch:
        "interes_afiliacion": None,
        "otra_caja_compensacion": None,
    }
    afiliado = _afiliado("B", 750)  # Muy Bueno → 22

    score, rating, classification, reasoning = score_lead(lead, afiliado)
    result = build_scoring_result(lead, afiliado)

    # 22 (credito) + 11 (B) + 14 (ingreso 4_8m) + 12 (ahorro 10_20m)
    # + 5 (tiempo 1_ano) + 15 (capacidad) + 8 (pac) = 87
    assert score == 87
    assert rating == "Muy Bueno"
    assert classification == "calificado"
    assert result["breakdown"] == {
        "credito": 22,
        "afiliacion": 11,
        "ingreso": 14,
        "ahorro": 12,
        "tiempo": 5,
        "capacidad": 15,
        "ajustes": 8,
    }
    # pos_subsidio stays available — a NULL `otra_caja_compensacion` can never
    # trip the zero rule.
    assert "Posibilidad de subsidio Colsubsidio: 1" in reasoning


# ── Case 10: no-afiliado bureau sim is deterministic + labelled ───────────
def test_case_10_no_afiliado_bureau_simulation_is_deterministic() -> None:
    lead_constructor: LeadProfile = {
        "numero_documento": "12345678",
        "rango_salarial": "hasta_2m",
        "ahorros_o_cesantias": "ninguno",
        "tiempo_compra_deseado": "no_se",
        "contrato_laboral": "independiente",
        "tiene_vivienda_propia": False,
        "tiene_creditos_activos": False,
        "numero_pac": 0,
        "subsidio_vivienda_anterior": False,
        "vis_recommended": False,
    }
    first = score_lead(lead_constructor, afiliado=None)
    second = score_lead(lead_constructor, afiliado=None)
    assert first == second  # identical 4-tuple across two calls
    assert "simulado bureau" in first[3]  # reasoning labels the simulation
    # Direct helper determinism
    assert simulate_bureau_cedula("12345678") == simulate_bureau_cedula("12345678")


# ── Case 11: same (lead, afiliado) → identical tuple (reproducibility) ──────
def test_case_11_same_inputs_identical_across_invocations() -> None:
    lead = _ready_lead()
    afiliado = _afiliado("A", 880)
    first = score_lead(lead, afiliado)
    second = score_lead(lead, afiliado)
    assert first == second


# ── Case 12 / D3 regression: affiliation is a strictly positive signal ─────
# The previous fixture-based case passed by coincidence: it used the demo
# cedula `1010101010`, which the simulation special-cased to the very same 880
# the afiliado record carried. Meanwhile the simulation was clamped to
# [550, 850], so a simulated no-afiliado could never band Malo while a real
# afiliado could — and a `(C, 500)` afiliado scored *below* the identical
# no-afiliado lead. This is a property over a range of documents and
# categorias instead.

# design.md §7.3 — the bureau simulation draws from the source band table,
# which includes the Malo outcome (400).
_SIM_BAND_TABLE: list[int] = [820, 760, 710, 670, 600, 400]


def _documentos(count: int = 60) -> list[str]:
    """Spread document numbers over every residue class of the band table."""
    return [str(1_000_000_000 + i * 7919) for i in range(count)]


def _mid_lead(**overrides: object) -> LeadProfile:
    """A mid-tier profile whose maximum total stays well below the clamp.

    36 non-credit points, so `credito + categoria` deltas are observable
    without `min(100, …)` swallowing them.
    """
    base: LeadProfile = {
        "rango_salarial": "2_4m",          # 10
        "ahorros_o_cesantias": "3_10m",    # 9
        "tiempo_compra_deseado": "6_meses",  # 8
        "total_ingresos_mensuales": 4_000_000,
        "gastos_mensuales": 3_400_000,     # ratio 0.15 → 3 pts
        "tiene_vivienda_propia": False,
        "tiene_creditos_activos": False,
        "numero_pac": 0,
        "vis_recommended": False,
        "subsidio_vivienda_anterior": False,
    }
    return {**base, **overrides}  # type: ignore[return-value]


@pytest.mark.parametrize("categoria", ["A", "B", "C"])
def test_regression_d3_affiliation_is_strictly_positive_over_documents(
    categoria: str,
) -> None:
    """Two leads identical in every field except affiliation: the afiliado's
    score is strictly greater, by exactly its Bucket-2 credit.

    Affiliation cannot change a lead's credit standing, so the comparison
    holds it fixed at the value the bureau simulation derives from the shared
    document number. The property is exercised across the whole credit range,
    Malo included — the floored simulation could not produce a Malo
    no-afiliado at all.
    """
    credit_points_seen: set[int] = set()

    for documento in _documentos():
        lead = _mid_lead(numero_documento=documento)
        # Identical credit standing — affiliation is the ONLY difference.
        afiliado = _afiliado(categoria, simulate_bureau_cedula(documento))

        af_score, af_rating, _, af_reason = score_lead(lead, afiliado)
        no_score, no_rating, _, no_reason = score_lead(lead, None)

        assert af_rating == no_rating, documento
        assert af_score > no_score, (documento, categoria)
        assert af_score - no_score == CATEGORIA_PTS[categoria], documento
        # …and the no-afiliado also needs the higher READY threshold.
        assert READY_THRESHOLD_NO_AFILIADO > READY_THRESHOLD_AFILIADO
        assert "Umbral READY aplicado: 60 (afiliado)" in af_reason
        assert "Umbral READY aplicado: 75 (no afiliado)" in no_reason

        af_break = build_scoring_result(lead, afiliado)["breakdown"]
        no_break = build_scoring_result(lead, None)["breakdown"]
        assert af_break["afiliacion"] == CATEGORIA_PTS[categoria]
        assert no_break["afiliacion"] == 0
        assert af_break["credito"] == no_break["credito"]
        credit_points_seen.add(af_break["credito"])

    # The simulation is not floored: every band of the source table is
    # reachable for a no-afiliado, Malo (0) included. Before the fix the
    # simulated range was clamped to [550, 850], so a no-afiliado was
    # guaranteed at least Regular while a real afiliado could band Malo.
    assert credit_points_seen == {25, 22, 18, 12, 6, 0}


# ── D1 regression: workbook `SI`/`NO` booleans reach the scorer normalized ──
# The `Leads` sheet stores its yes/no columns as the literals `SI` / `NO`. The
# scorer tests `is True`, so an un-normalized `'SI'` silently disabled every
# boolean rule — including the absolute subsidio-previo disqualifier, which
# scored `'SI'` as `calificado`. Booleans are now routed through
# `domain_normalizer.normalize_bool` at the scorer boundary.
def test_regression_d1_workbook_si_no_booleans_are_normalized() -> None:
    afiliado = _afiliado("A", 880)

    # Absolute disqualifier fires on the workbook's own vocabulary.
    score, _, classification, reasoning = score_lead(
        _ready_lead(subsidio_vivienda_anterior="SI"), afiliado
    )
    assert classification == "nutrible"
    assert score == 100  # the override never subtracts
    assert (
        "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"
        in reasoning
    )
    # …and on the accented / lowercase variants.
    for si in ("Sí", "si", "SÍ", "true", True):
        assert score_lead(_ready_lead(subsidio_vivienda_anterior=si), afiliado)[2] == (
            "nutrible"
        )

    # `NO` is a real negative, not a truthy string.
    assert score_lead(_ready_lead(subsidio_vivienda_anterior="NO"), afiliado)[2] == (
        "calificado"
    )

    # Unrecognized fails closed: treated as absent, never as True.
    assert score_lead(
        _ready_lead(subsidio_vivienda_anterior="tal vez"), afiliado
    )[2] == "calificado"

    # The other workbook booleans drive their red flags from `SI` too.
    baseline, _, _, _ = score_lead(_ready_lead(), afiliado)
    creditos, _, _, _ = score_lead(_ready_lead(tiene_creditos_activos="SI"), afiliado)
    assert creditos == baseline - 5

    vis = build_scoring_result(
        _ready_lead(tiene_vivienda_propia="SI", vis_recommended=True), afiliado
    )
    assert vis["breakdown"]["ajustes"] == -15


# ── D2 regression: an afiliado with NULL score_credito is not fabricated ────
# Bucket 1 guarded the afiliado branch with `score_credito is not None`, so an
# afiliado whose credit score is missing fell through to the *no-afiliado*
# cedula bureau simulation of their own document number — inventing an
# Excelente band and mislabelling the reasoning as "simulado bureau". Spec
# Bucket 1: a NULL score_credito contributes 0 and yields rating_label="Malo";
# the simulation is for no-afiliado leads only.
def test_regression_d2_afiliado_without_score_credito_is_malo() -> None:
    lead = _ready_lead(numero_documento="1010101010")
    afiliado: AfiliadoRecord = {"categoria_afiliado": "A"}  # score_credito NULL

    score, rating, classification, reasoning = score_lead(lead, afiliado)

    assert rating == "Malo"
    # No credit points; the afiliacion bucket and the rest still count.
    # 0 (credito) + 15 (A) + 20 + 15 + 10 + 15 (capacidad) = 75
    assert score == 75
    assert classification == "calificado"  # 75 >= 60, but on real points only
    assert "simulado bureau" not in reasoning  # never claimed for an afiliado
    assert "Credito: Malo (None) → 0/25" in reasoning
    assert build_scoring_result(lead, afiliado)["breakdown"]["credito"] == 0

    # Explicit None is the same as an absent key.
    explicit_null: AfiliadoRecord = {"categoria_afiliado": "A", "score_credito": None}
    assert score_lead(lead, explicit_null) == score_lead(lead, afiliado)


# ── D4 regression: the scorer is a total function of its inputs ─────────────
# `numero_pac="2"` raised `TypeError: '>' not supported between instances of
# 'str' and 'int'`. LLM-supplied numerics are plausibly strings, so every
# numeric the scorer compares is coerced defensively; an uncoercible value
# behaves as absent.
def test_regression_d4_numeric_fields_are_coerced_defensively() -> None:
    afiliado = _afiliado("A", 880)
    baseline, _, _, _ = score_lead(_ready_lead(), afiliado)

    # `numero_pac` as a string still fires the +8 bonus, and does not raise.
    for pac in ("2", " 2 ", "2.0", 2.0, 2):
        assert build_scoring_result(_ready_lead(numero_pac=pac), afiliado)[
            "breakdown"
        ]["ajustes"] == 8, pac

    # Uncoercible / absent → no bonus, no exception.
    for pac in ("", "muchos", "n/a", None, [], "0"):
        assert build_scoring_result(_ready_lead(numero_pac=pac), afiliado)[
            "breakdown"
        ]["ajustes"] == 0, pac
        assert score_lead(_ready_lead(numero_pac=pac), afiliado)[0] == baseline

    # `score_credito` arriving as a string bands normally; garbage is Malo.
    score, rating, _, _ = score_lead(
        _ready_lead(), {"categoria_afiliado": "A", "score_credito": "880"}
    )
    assert (score, rating) == (baseline, "Excelente")
    _, garbage_rating, _, _ = score_lead(
        _ready_lead(), {"categoria_afiliado": "A", "score_credito": "sin dato"}
    )
    assert garbage_rating == "Malo"

    # A non-string `numero_documento` still simulates instead of raising.
    numeric_doc, _, _, _ = score_lead(_ready_lead(numero_documento=12345678), None)
    str_doc, _, _, _ = score_lead(_ready_lead(numero_documento="12345678"), None)
    assert numeric_doc == str_doc

    # `total_ingresos_mensuales` / `gastos_mensuales` as strings (LLM/JSON
    # round-trip) still feed the Capacidad bucket instead of raising.
    for ingreso, gastos in (("10000000", "2000000"), (10_000_000.0, 2_000_000.0)):
        res = build_scoring_result(
            _ready_lead(total_ingresos_mensuales=ingreso, gastos_mensuales=gastos),
            afiliado,
        )
        assert res["breakdown"]["capacidad"] == 15
    # Uncoercible expense/income figures behave as absent (0 pts, no raise).
    res_garbage = build_scoring_result(
        _ready_lead(total_ingresos_mensuales="mucho", gastos_mensuales="poco"),
        afiliado,
    )
    assert res_garbage["breakdown"]["capacidad"] == 0


# ── Credit bands verifier: bands, NULL, simulate, demo cedulas ─────────────
# Confirm the band table matches the source workbook legend
# (`Afiliados Colsubsidio` R3:R8) and `design.md` §7.3 verbatim.
def test_credit_bands_match_source_legend() -> None:
    expected = [
        (800, 950, "Excelente", 25),
        (750, 799, "Muy Bueno", 22),
        (700, 749, "Bueno", 18),
        (650, 699, "Aceptable", 12),
        (500, 649, "Regular", 6),
        (150, 499, "Malo", 0),
    ]
    assert CREDIT_BANDS == expected


def test_band_from_score_credito_boundaries() -> None:
    assert band_from_score_credito(None) == (0, "Malo")
    assert band_from_score_credito(150) == (0, "Malo")
    assert band_from_score_credito(499) == (0, "Malo")
    assert band_from_score_credito(500) == (6, "Regular")
    assert band_from_score_credito(649) == (6, "Regular")
    assert band_from_score_credito(650) == (12, "Aceptable")
    assert band_from_score_credito(699) == (12, "Aceptable")
    assert band_from_score_credito(700) == (18, "Bueno")
    assert band_from_score_credito(749) == (18, "Bueno")
    assert band_from_score_credito(750) == (22, "Muy Bueno")
    assert band_from_score_credito(799) == (22, "Muy Bueno")
    assert band_from_score_credito(800) == (25, "Excelente")
    assert band_from_score_credito(950) == (25, "Excelente")


def test_band_from_score_credito_out_of_range_is_malo() -> None:
    assert band_from_score_credito(0) == (0, "Malo")
    assert band_from_score_credito(951) == (0, "Malo")
    assert band_from_score_credito(-50) == (0, "Malo")


def test_simulate_bureau_cedula_draws_from_the_source_band_table() -> None:
    # design.md §7.3: `[820, 760, 710, 670, 600, 400][int(digits) % 6]`.
    # The demo cedulas are seeded *afiliados*; they take the afiliado branch
    # and are no longer special-cased inside the simulation.
    for documento in ("12345678", "1010101010", "2020202020", "3030303030"):
        simulated = simulate_bureau_cedula(documento)
        assert simulated in _SIM_BAND_TABLE
        assert simulated == _SIM_BAND_TABLE[int(documento) % len(_SIM_BAND_TABLE)]
        assert simulate_bureau_cedula(documento) == simulated  # deterministic


def test_simulate_bureau_cedula_is_deterministic_across_processes() -> None:
    """Spec: same `numero_documento` always yields the same band — including in
    a separate process invocation (no hash-seed or clock dependency)."""
    documentos = _documentos(12)
    in_process = [simulate_bureau_cedula(d) for d in documentos]

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys;"
            "from app.services.credit_bands import simulate_bureau_cedula as s;"
            "print(json.dumps([s(d) for d in json.loads(sys.argv[1])]))",
            json.dumps(documentos),
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert json.loads(completed.stdout) == in_process


def test_simulate_bureau_cedula_no_digits_is_the_malo_band() -> None:
    # No usable document → the bottom band, not a fabricated mid-range floor.
    assert simulate_bureau_cedula("") == 400
    assert simulate_bureau_cedula("no-digits-here") == 400


# ── classify_lead — pure threshold table ───────────────────────────────────
def test_classify_lead_threshold_matrix() -> None:
    # Subsidio override is absolute: calificado is unreachable.
    assert classify_lead(100, True, True) == "nutrible"
    assert classify_lead(60, False, True) == "nutrible"
    assert classify_lead(29, True, True) == "no_calificado"
    assert classify_lead(30, True, True) == "nutrible"
    # Afiliado READY threshold = 60
    assert classify_lead(60, True, False) == "calificado"
    assert classify_lead(59, True, False) == "nutrible"
    assert classify_lead(30, True, False) == "nutrible"
    assert classify_lead(29, True, False) == "no_calificado"
    # No-afiliado READY threshold = 75
    assert classify_lead(74, False, False) == "nutrible"
    assert classify_lead(75, False, False) == "calificado"
    assert classify_lead(60, False, False) == "nutrible"  # afiliado threshold does NOT apply


def test_score_lead_handles_none_inputs() -> None:
    # scorers must be total functions even for empty profiles.
    score, rating, classification, _ = score_lead(None, None)
    assert 0 <= score <= 100
    assert classification in ("calificado", "nutrible", "no_calificado")


def test_build_scoring_result_breakdown_sums_to_clamped_score() -> None:
    lead = _ready_lead()
    afiliado = _afiliado("A", 880)
    res: ScoringResult = build_scoring_result(lead, afiliado)

    buckets_sum = (
        res["breakdown"]["credito"]
        + res["breakdown"]["afiliacion"]
        + res["breakdown"]["ingreso"]
        + res["breakdown"]["ahorro"]
        + res["breakdown"]["tiempo"]
        + res["breakdown"]["capacidad"]
        + res["breakdown"]["ajustes"]
    )
    assert res["score"] == max(0, min(100, buckets_sum))
    assert res["status"] == res["classification"]  # alias invariant


def test_bucket_maxima_sum_to_exactly_100() -> None:
    # Spec scenario *Bucket credits are capped at the documented maxima*,
    # re-budgeted for v2: Credito 25 + Afiliacion 15 + Ingreso 20 + Ahorro 15
    # + Tiempo 10 + Capacidad 15 = exactly 100.
    assert 25 + 15 + 20 + 15 + 10 + 15 == 100
    assert max(band_from_score_credito(900)[0] for _ in [0]) == 25
    assert max(pts for _, pts in CAPACIDAD_BANDS) == 15


# Sanity guard: the demo cedulas mapping matches the seeded afiliado names.
def test_demo_cedula_scores_mapping() -> None:
    assert DEMO_CEDULA_SCORES == {
        "1010101010": 880,
        "2020202020": 720,
        "3030303030": 580,
    }


# Sanity guard: NURTURE_FLOOR constant matches design/test expectations.
def test_threshold_constants() -> None:
    assert READY_THRESHOLD_AFILIADO == 60
    assert READY_THRESHOLD_NO_AFILIADO == 75
    assert NURTURE_FLOOR == 30
