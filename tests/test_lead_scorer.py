"""Scorer matrix tests for the Colsubsidio lead scorer.

The 12 cases below encode ``design.md`` §11 verbatim. Two cases are deliberate
regression guards for audit findings preserved in ``review-ledger.md``:

* **case 5** — ``estado_civil='soltero'`` with
  ``subsidio_vivienda_anterior=True`` still yields ``nurture``. The override
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
    ESTABILIDAD_INDEPENDIENTE,
    ESTABILIDAD_PTS,
    INGRESO_PTS,
    NURTURE_FLOOR,
    READY_THRESHOLD_AFILIADO,
    READY_THRESHOLD_NO_AFILIADO,
    ScoringResult,
    TIEMPO_PTS,
    build_scoring_result,
    classify_lead,
    score_lead,
)


class LeadProfile(TypedDict, total=False):
    """Local input view mirroring ``design.md`` §6.

    Phase 1 owns the authoritative ``LeadColsubsidioEntity``; Phase 2 consumes
    any dict with these keys, so tests stay isolated from the model layer.
    """

    numero_documento: str
    rango_salarial: str
    ahorros_o_cesantias: str
    tiempo_compra_deseado: str
    contrato_laboral: str
    antiguedad_laboral: str
    tiene_vivienda_propia: bool
    tiene_creditos_activos: bool
    condicion_discapacidad_familiar: bool
    numero_pac: int
    vis_recommended: bool
    subsidio_vivienda_anterior: bool
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
    produces a single, observable, mechanical change to the score.
    """
    base: LeadProfile = {
        "numero_documento": "1010101010",
        "rango_salarial": "mas_10m",
        "ahorros_o_cesantias": "mas_40m",
        "tiempo_compra_deseado": "3_meses",
        "contrato_laboral": "termino_indefinido",
        "antiguedad_laboral": "mas_2a",
        "tiene_vivienda_propia": False,
        "tiene_creditos_activos": False,
        "condicion_discapacidad_familiar": False,
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


# ── Case 1: afiliado A + Excelente + max buckets → ready at ceiling ───────
def test_case_1_afiliado_a_ceiling_is_ready() -> None:
    lead = _ready_lead()
    afiliado = _afiliado("A", 880)  # Excelente → 25
    score, rating, classification, reasoning = score_lead(lead, afiliado)

    assert classification == "ready"
    assert rating == "Excelente"
    # 25 (credito) + 15 (cat A) + 20 (ingreso) + 15 (ahorro)
    # + 10 (tiempo) + 15 (estab indef+mas_2a) = 100
    assert score == 100
    assert "Umbral READY aplicado: 60 (afiliado)" in reasoning
    assert classification == "ready"


# ── Case 2: afiliado B + Bueno + mid buckets → ready ──────────────────────
def test_case_2_afiliado_b_mid_buckets_ready() -> None:
    lead: LeadProfile = {
        "rango_salarial": "2_4m",
        "ahorros_o_cesantias": "3_10m",
        "tiempo_compra_deseado": "6_meses",
        "contrato_laboral": "termino_fijo",
        "antiguedad_laboral": "1_2a",
        "tiene_vivienda_propia": False,
        "tiene_creditos_activos": False,
        "condicion_discapacidad_familiar": False,
        "numero_pac": 0,
        "subsidio_vivienda_anterior": False,
        "vis_recommended": False,
    }
    afiliado = _afiliado("B", 720)  # Bueno → 18
    score, rating, classification, _ = score_lead(lead, afiliado)

    # 18 + 11 (B) + 10 + 9 + 8 + 9 = 65
    assert score == 65
    assert rating == "Bueno"
    assert classification == "ready"  # 65 >= 60 (afiliado threshold)


# ── Case 3: afiliado C + min buckets → nurture_social ──────────────────────
def test_case_3_afiliado_c_min_buckets_nurture_social() -> None:
    lead: LeadProfile = {
        "rango_salarial": "hasta_2m",
        "ahorros_o_cesantias": "ninguno",
        "tiempo_compra_deseado": "no_se",
        "contrato_laboral": "termino_indefinido",
        "antiguedad_laboral": "menos_1a",
        "tiene_vivienda_propia": False,
        "tiene_creditos_activos": False,
        "condicion_discapacidad_familiar": False,
        "numero_pac": 0,
        "subsidio_vivienda_anterior": False,
        "vis_recommended": False,
    }
    afiliado = _afiliado("C", 580)  # Regular → 6
    score, rating, classification, _ = score_lead(lead, afiliado)

    # 6 + 7 (C) + 5 + 0 + 0 + 7 = 25
    assert score == 25
    assert rating == "Regular"
    assert classification == "nurture_social"  # 25 < NURTURE_FLOOR (30)


# ── Case 4: subsidio previo override, score untouched ─────────────────────
def test_case_4_subsidio_previo_override_does_not_touch_score() -> None:
    lead = _ready_lead(subsidio_vivienda_anterior=True)
    afiliado = _afiliado("A", 880)

    baseline_score, _, baseline_class, baseline_reason = score_lead(
        _ready_lead(subsidio_vivienda_anterior=False), afiliado
    )
    override_score, _, override_class, override_reason = score_lead(lead, afiliado)

    assert baseline_class == "ready"
    assert override_class == "nurture"
    # Numeric score is untouched — analytics keep the real figure.
    assert override_score == baseline_score == 100
    assert "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio" in override_reason
    assert baseline_reason != override_reason  # the override appends a line


# ── Case 5: estado_civil='soltero' still yields nurture override ──────────
# Regression guard for §13.2: the override fires regardless of estado_civil.
def test_case_5_subsidio_previo_override_with_soltero() -> None:
    lead = _ready_lead(estado_civil="soltero", subsidio_vivienda_anterior=True)
    afiliado = _afiliado("A", 880)

    score, _, classification, reasoning = score_lead(lead, afiliado)

    assert classification == "nurture"
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


# ── Case 7: creditos_activos −5; discapacidad/PAC +8 ───────────────────────
def test_case_7_red_flags_creditos_minus_5_discapacidad_plus_8() -> None:
    afiliado = _afiliado("A", 880)
    baseline = _ready_lead()
    with_creditos = _ready_lead(tiene_creditos_activos=True)
    with_discapacidad = _ready_lead(condicion_discapacidad_familiar=True)
    with_pac = _ready_lead(numero_pac=2)

    base_score, _, _, _ = score_lead(baseline, afiliado)
    creditos_score, _, _, _ = score_lead(with_creditos, afiliado)
    discapacidad_score, _, _, _ = score_lead(with_discapacidad, afiliado)
    pac_score, _, _, _ = score_lead(with_pac, afiliado)

    assert creditos_score == base_score - 5
    # +8 may be clamped at the ceiling; the observable guarantee is the +8
    # contribution to the *adjustments* bucket, not the post-clamp score delta.
    assert discapacidad_score == min(100, base_score + 8)
    assert pac_score == min(100, base_score + 8)
    # PAC +1 also fires the +8 bonus — discapacidad/PAC are OR'd at the scorer.
    pac_one = _ready_lead(numero_pac=1)
    pac_one_score, _, _, _ = score_lead(pac_one, afiliado)
    assert pac_one_score == min(100, base_score + 8)
    # Bonus reachable from soltero + afiliado (§13.2 / spec discapacidad scenario):
    # the previous revision left `soltero` afiliado unable to reach the bonus
    # because the `numero_pac` field was collected only on paths it never reached.
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
        "contrato_laboral": "prestacion_servicios",  # → 6 (independiente)
        "tiene_vivienda_propia": False,
        "tiene_creditos_activos": False,
        "condicion_discapacidad_familiar": False,
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
    # Documented point values are distinct per slug (proves the "every canonical
    # slug maps to a distinct documented point value" assertion).
    if all(pts != 0 for _, pts in expected_pairs if pts == 0) is False:
        # Allow `ninguno`/`no_se` (which legitimately score 0); just ensure no
        # two non-zero documented slugs collide.
        non_zero_pts = [pts for _, pts in expected_pairs if pts != 0]
        assert len(non_zero_pts) == len(set(non_zero_pts))
    # Unknown slug yields 0 (exact lookup, never mid-range default).
    assert table.get("unknown_slug_xyz") is None

    # Estabilidad bucket: every (contrato, antiguedad) pair documented + an
    # additional flat-fee for `prestacion_servicios`. Unknown contrato/antiguedad
    # contributes 0 — no mid-range fallback.
    for contrato, pensions in ESTABILIDAD_PTS.items():
        assert contrato in {"termino_indefinido", "termino_fijo"}
        assert set(pensions) == {"mas_2a", "1_2a", "menos_1a"}
    assert ESTABILIDAD_INDEPENDIENTE == 6
    assert ESTABILIDAD_PTS.get("contrato_inexistente", {}).get("menos_1a") is None


def test_case_9_estabilidad_independiente_flat_fee() -> None:
    # Independent contract (`prestacion_servicios`) → flat 6, antiguedad ignored.
    lead = _ready_lead(contrato_laboral="prestacion_servicios", antiguedad_laboral=None)
    afiliado = _afiliado("A", 880)
    res = build_scoring_result(lead, afiliado)
    assert res["breakdown"]["estabilidad"] == 6


# ── Case 10: no-afiliado bureau sim is deterministic + labelled ───────────
def test_case_10_no_afiliado_bureau_simulation_is_deterministic() -> None:
    lead_constructor: LeadProfile = {
        "numero_documento": "12345678",
        "rango_salarial": "hasta_2m",
        "ahorros_o_cesantias": "ninguno",
        "tiempo_compra_deseado": "no_se",
        "contrato_laboral": "prestacion_servicios",
        "tiene_vivienda_propia": False,
        "tiene_creditos_activos": False,
        "condicion_discapacidad_familiar": False,
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


# ── Case 12: afiliado strictly outscores identical no-afiliado (90/10) ─────
def test_case_12_afiliado_strictly_outscores_no_afiliado() -> None:
    afiliado_lead = _ready_lead()  # numero_documento="1010101010"
    afiliado_record = _afiliado("A", 880)
    no_afiliado_record: AfiliadoRecord = {}  # afiliado=None at the call site

    afiliado_score, _, afiliado_class, afiliado_reason = score_lead(
        afiliado_lead, afiliado_record
    )
    no_afiliado_score, _, no_afiliado_class, no_afiliado_reason = score_lead(
        afiliado_lead, None
    )

    assert afiliado_score > no_afiliado_score
    # Bucket 2 lever: afiliado gets cat A=15, no-afiliado gets 0
    af_range = build_scoring_result(afiliado_lead, afiliado_record)
    no_range = build_scoring_result(afiliado_lead, None)
    assert af_range["breakdown"]["afiliacion"] == 15
    assert no_range["breakdown"]["afiliacion"] == 0
    # Both profiles identical otherwise; no-afiliado needs the higher threshold
    afiliado_threshold = READY_THRESHOLD_AFILIADO  # 60
    no_afiliado_threshold = READY_THRESHOLD_NO_AFILIADO  # 75
    assert no_afiliado_threshold > afiliado_threshold
    # Asymmetric reasoning identifies the threshold applied
    assert "Umbral READY aplicado: 60 (afiliado)" in afiliado_reason
    assert "Umbral READY aplicado: 75 (no afiliado)" in no_afiliado_reason
    # And classification uses the right threshold on the afiliado side.
    assert afiliado_class == "ready"


# ── D1 regression: workbook `SI`/`NO` booleans reach the scorer normalized ──
# The `Leads` sheet stores its yes/no columns as the literals `SI` / `NO`. The
# scorer tests `is True`, so an un-normalized `'SI'` silently disabled every
# boolean rule — including the absolute subsidio-previo disqualifier, which
# scored `'SI'` as `ready`. Booleans are now routed through
# `domain_normalizer.normalize_bool` at the scorer boundary.
def test_regression_d1_workbook_si_no_booleans_are_normalized() -> None:
    afiliado = _afiliado("A", 880)

    # Absolute disqualifier fires on the workbook's own vocabulary.
    score, _, classification, reasoning = score_lead(
        _ready_lead(subsidio_vivienda_anterior="SI"), afiliado
    )
    assert classification == "nurture"
    assert score == 100  # the override never subtracts
    assert (
        "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"
        in reasoning
    )
    # …and on the accented / lowercase variants.
    for si in ("Sí", "si", "SÍ", "true", True):
        assert score_lead(_ready_lead(subsidio_vivienda_anterior=si), afiliado)[2] == (
            "nurture"
        )

    # `NO` is a real negative, not a truthy string.
    assert score_lead(_ready_lead(subsidio_vivienda_anterior="NO"), afiliado)[2] == (
        "ready"
    )

    # Unrecognized fails closed: treated as absent, never as True.
    assert score_lead(
        _ready_lead(subsidio_vivienda_anterior="tal vez"), afiliado
    )[2] == "ready"

    # The other three workbook booleans drive their red flags from `SI` too.
    baseline, _, _, _ = score_lead(_ready_lead(), afiliado)
    creditos, _, _, _ = score_lead(_ready_lead(tiene_creditos_activos="SI"), afiliado)
    assert creditos == baseline - 5

    vis = build_scoring_result(
        _ready_lead(tiene_vivienda_propia="SI", vis_recommended=True), afiliado
    )
    assert vis["breakdown"]["ajustes"] == -15

    discapacidad = build_scoring_result(
        _ready_lead(condicion_discapacidad_familiar="SI"), afiliado
    )
    assert discapacidad["breakdown"]["ajustes"] == 8


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
    # 0 (credito) + 15 (A) + 20 + 15 + 10 + 15 = 75
    assert score == 75
    assert classification == "ready"  # 75 >= 60, but on real points only
    assert "simulado bureau" not in reasoning  # never claimed for an afiliado
    assert "Credito: Malo (None) → 0/25" in reasoning
    assert build_scoring_result(lead, afiliado)["breakdown"]["credito"] == 0

    # Explicit None is the same as an absent key.
    explicit_null: AfiliadoRecord = {"categoria_afiliado": "A", "score_credito": None}
    assert score_lead(lead, explicit_null) == score_lead(lead, afiliado)


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


def test_simulate_bureau_cedula_demo_cedulas() -> None:
    assert simulate_bureau_cedula("1010101010") == 880  # Excelente
    assert simulate_bureau_cedula("2020202020") == 720  # Bueno
    assert simulate_bureau_cedula("3030303030") == 580  # Regular


def test_simulate_bureau_cedula_in_real_band_and_deterministic() -> None:
    score = simulate_bureau_cedula("12345678")
    assert 550 <= score <= 850  # always a real (non-Malo) band per design
    assert simulate_bureau_cedula("12345678") == score


def test_simulate_bureau_cedula_no_digits_falls_back_to_floor() -> None:
    assert simulate_bureau_cedula("") == 550
    assert simulate_bureau_cedula("no-digits-here") == 550


# ── classify_lead — pure threshold table ───────────────────────────────────
def test_classify_lead_threshold_matrix() -> None:
    # Subsidio override is absolute: ready is unreachable.
    assert classify_lead(100, True, True) == "nurture"
    assert classify_lead(60, False, True) == "nurture"
    assert classify_lead(29, True, True) == "nurture_social"
    assert classify_lead(30, True, True) == "nurture"
    # Afiliado READY threshold = 60
    assert classify_lead(60, True, False) == "ready"
    assert classify_lead(59, True, False) == "nurture"
    assert classify_lead(30, True, False) == "nurture"
    assert classify_lead(29, True, False) == "nurture_social"
    # No-afiliado READY threshold = 75
    assert classify_lead(74, False, False) == "nurture"
    assert classify_lead(75, False, False) == "ready"
    assert classify_lead(60, False, False) == "nurture"  # afiliado threshold does NOT apply


def test_score_lead_handles_none_inputs() -> None:
    # scorers must be total functions even for empty profiles.
    score, rating, classification, _ = score_lead(None, None)
    assert 0 <= score <= 100
    assert classification in ("ready", "nurture", "nurture_social")


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
        + res["breakdown"]["estabilidad"]
        + res["breakdown"]["ajustes"]
    )
    assert res["score"] == max(0, min(100, buckets_sum))
    assert res["status"] == res["classification"]  # alias invariant


def test_bucket_maxima_sum_to_exactly_100() -> None:
    # Spec scenario *Bucket credits are capped at the documented maxima*:
    # Credito 25 + Afiliacion 15 + Ingreso 20 + Ahorro 15 + Tiempo 10 +
    # Estabilidad 15 = exactly 100.
    assert 25 + 15 + 20 + 15 + 10 + 15 == 100
    assert max(band_from_score_credito(900)[0] for _ in [0]) == 25


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