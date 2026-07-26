"""Tests for the lead domain normalizer.

Written BEFORE `app/services/domain_normalizer.py` (audit-driven tests-first
for the pure module where the previous revision's substring-match bug lived:
`"no" in "menos"` scoring `Menos de $3 millones` as 0).

Every verbatim label from the workbook (`docs/Preguntas y modelo tabla de
datos.xlsx`, sheet `Leads`) MUST map to its canonical slug, with and without
accents and casing; unrecognized values return None; the municipio table maps
all nine lead-facing options; the corrupt catalogue value `'VIS'` is repaired
to `'Bogota'` at lookup time.
"""

from __future__ import annotations

import pytest

from app.services.domain_normalizer import (
    MUNICIPIO_CATALOGO_REPAIR,
    normalize,
    normalize_municipio,
    repair_catalogo_municipio,
)


# ── tipo_documento (5 source types) ────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,slug",
    [
        ("Cédula de ciudadanía", "CC"),
        ("cédula de extranjería", "CE"),
        ("PASAPORTE", "PA"),
        ("permiso especial de permanencia", "PEP"),
        ("Permiso por Protección Temporal", "PPT"),
    ],
)
def test_normalize_tipo_documento(raw, slug):
    assert normalize("tipo_documento", raw) == slug


def test_normalize_tipo_documento_strip_accents_case():
    assert normalize("tipo_documento", "CEDULA DE CIUDADANIA") == "CC"
    assert normalize("tipo_documento", "cédula de ciudadanía") == "CC"
    assert normalize("tipo_documento", "  Pasaporte  ") == "PA"


def test_normalize_tipo_documento_rejects_ti():
    # TI appears nowhere in the source domain (only CC/CE/PA/PEP/PPT).
    assert normalize("tipo_documento", "Tarjeta de identidad") is None
    assert normalize("tipo_documento", "TI") is None


# ── estado_civil (6-value domain) ─────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,slug",
    [
        ("Soltero", "soltero"),
        ("Casado", "casado"),
        ("Divorciado", "divorciado"),
        ("Union libre", "union_libre"),
        ("Separado", "separado"),
        ("Viudo", "viudo"),
    ],
)
def test_normalize_estado_civil(raw, slug):
    assert normalize("estado_civil", raw) == slug


def test_normalize_estado_civil_casing_and_accents():
    assert normalize("estado_civil", "UNION LIBRE") == "union_libre"
    assert normalize("estado_civil", "unión libre") == "union_libre"
    assert normalize("estado_civil", "soltero") == "soltero"


# ── contrato_laboral (3-value domain; note trailing-space quirk on Termino
#    indefinido in the source sheet) ─────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,slug",
    [
        ("Termino fijo", "termino_fijo"),
        ("Termino indefinido ", "termino_indefinido"),  # source has trailing space
        ("Prestacion de servicios", "prestacion_servicios"),
    ],
)
def test_normalize_contrato_laboral(raw, slug):
    assert normalize("contrato_laboral", raw) == slug


def test_normalize_contrato_laboral_strips_internal_whitespace():
    # Multiple spaces / tabs are collapsed before exact lookup, never matched
    # by substring.
    assert normalize("contrato_laboral", "termino   fijo") == "termino_fijo"
    assert normalize("contrato_laboral", "PRESTACION DE SERVICIOS") == "prestacion_servicios"


# ── rango_salarial (5-value domain; `mas` has no accent in the source) ─────
@pytest.mark.parametrize(
    "raw,slug",
    [
        ("2 millones o menos", "hasta_2m"),
        ("2 a 4 millones", "2_4m"),
        ("4 a 8 millones", "4_8m"),
        ("8 a 10 millones", "8_10m"),
        ("mas de 10 millones", "mas_10m"),
    ],
)
def test_normalize_rango_salarial(raw, slug):
    assert normalize("rango_salarial", raw) == slug


def test_normalize_rango_salarial_accent_insensitive():
    assert normalize("rango_salarial", "Más de 10 millones") == "mas_10m"


# ── antiguedad_laboral (3-value domain) ────────────────────────────────────
@pytest.mark.parametrize(
    "raw,slug",
    [
        ("Menos de 1 año", "menos_1a"),
        ("1 a 2 años", "1_2a"),
        ("Mas de dos años", "mas_2a"),
    ],
)
def test_normalize_antiguedad_laboral(raw, slug):
    assert normalize("antiguedad_laboral", raw) == slug


def test_normalize_antiguedad_laboral_casing():
    assert normalize("antiguedad_laboral", "menos de 1 año") == "menos_1a"
    assert normalize("antiguedad_laboral", "MENOS DE 1 AÑO") == "menos_1a"
    assert normalize("antiguedad_laboral", "mas de dos años") == "mas_2a"


# ── ahorros_o_cesantias (6-value domain) — guards the substring bug ─────────
@pytest.mark.parametrize(
    "raw,slug",
    [
        ("No tengo ahorros.", "ninguno"),
        ("Menos de $3 millones", "menos_3m"),
        ("Entre $3 y $10 millones", "3_10m"),
        ("Entre $10 y $20 millones", "10_20m"),
        ("Entre $20 y $40 millones", "20_40m"),
        ("Más de $40 millones", "mas_40m"),
    ],
)
def test_normalize_ahorros(raw, slug):
    assert normalize("ahorros_o_cesantias", raw) == slug


def test_normalize_ahorros_menos_is_not_zero():
    """Regression guard for DATA-001: `"no"` substring in `"menos"`.

    The previous revision's `"no" not in ahorro` check scored
    `Menos de $3 millones` as 0. The normalizer must exact-match the whole
    label, so `Menos de $3 millones` → `menos_3m` (which scores 5), not None.
    """
    assert normalize("ahorros_o_cesantias", "Menos de $3 millones") == "menos_3m"
    assert normalize("ahorros_o_cesantias", "menos de $3 millones") == "menos_3m"


# ── tiempo_compra_deseado (5-value domain) ─────────────────────────────────
@pytest.mark.parametrize(
    "raw,slug",
    [
        ("3 meses", "3_meses"),
        ("6 meses", "6_meses"),
        ("1 año", "1_ano"),
        ("2 años", "2_anos"),
        ("No sé", "no_se"),
    ],
)
def test_normalize_tiempo_compra(raw, slug):
    assert normalize("tiempo_compra_deseado", raw) == slug


def test_normalize_tiempo_compra_accents():
    assert normalize("tiempo_compra_deseado", "no se") == "no_se"
    assert normalize("tiempo_compra_deseado", "NO SÉ") == "no_se"
    assert normalize("tiempo_compra_deseado", "1 AÑO") == "1_ano"


# ── canonical slugs pass through unchanged ─────────────────────────────────
@pytest.mark.parametrize(
    "field,slug",
    [
        ("tipo_documento", "CC"),
        ("estado_civil", "soltero"),
        ("contrato_laboral", "prestacion_servicios"),
        ("rango_salarial", "mas_10m"),
        ("antiguedad_laboral", "mas_2a"),
        ("ahorros_o_cesantias", "menos_3m"),
        ("tiempo_compra_deseado", "no_se"),
    ],
)
def test_canonical_slug_passes_through(field, slug):
    assert normalize(field, slug) == slug


# ── unknown / null behaviour ────────────────────────────────────────────────
def test_unknown_value_returns_none():
    assert normalize("estado_civil", "complicado") is None
    assert normalize("rango_salarial", "1 millón") is None
    assert normalize("ahorros_o_cesantias", "un montón") is None


def test_none_returns_none():
    assert normalize("estado_civil", None) is None
    assert normalize("tipo_documento", None) is None


def test_unknown_field_returns_none():
    assert normalize("no_such_field", "Soltero") is None


def test_never_substring_matches():
    """`'no'` must not match `'ninguno'` and `'fijo'` must not match
    `'termino fijo'` via a partial hit — exact match only."""
    assert normalize("ahorros_o_cesantias", "no") is None
    assert normalize("ahorros_o_cesantias", "ningun") is None
    assert normalize("contrato_laboral", "fijo") is None


# ── municipio normalization (9 lead-facing options) ────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Bogotá norte", "Bogota"),
        ("Bogotá centro", "Bogota"),
        ("Bogotásur", "Bogota"),  # source typo, no space — preserved as key
        ("Soacha", "Soacha"),
        ("Chía", "Chía"),
        ("Tocancipá", "Tocancipá"),
        ("Girardot", "Girardot"),
        ("Ricaurte", "Ricaurte"),
        ("Ubaté", "Ubate"),  # catalogue is unaccented
    ],
)
def test_normalize_municipio_all_nine_options(raw, expected):
    assert normalize_municipio(raw) == expected


def test_normalize_municipio_casing_and_accents():
    assert normalize_municipio("BOGOTÁ NORTE") == "Bogota"
    # `Bogotásur` is a source typo with no space; the verbatim key is the
    # one-word form. "bogota sur" (with space) is not a source option → None.
    assert normalize_municipio("bogotasur") == "Bogota"
    assert normalize_municipio("UBATÉ") == "Ubate"
    assert normalize_municipio("Ubate") == "Ubate"


def test_normalize_municipio_unknown_returns_none():
    assert normalize_municipio("Medellín") is None
    assert normalize_municipio(None) is None


# ── catalogue repair: corrupt `municipio='VIS'` on VIBO ONCE B2 ────────────
def test_repair_catalogo_municipio_vis_to_bogota():
    assert repair_catalogo_municipio("VIS") == "Bogota"
    assert repair_catalogo_municipio("Bogota") == "Bogota"
    assert repair_catalogo_municipio("Soacha") == "Soacha"
    assert repair_catalogo_municipio(None) is None


def test_municipio_catalogo_repair_constant():
    assert MUNICIPIO_CATALOGO_REPAIR == {"VIS": "Bogota"}


def test_repair_does_not_alter_other_values():
    assert repair_catalogo_municipio("Chía") == "Chía"
    assert repair_catalogo_municipio("Ubate") == "Ubate"