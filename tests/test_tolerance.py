"""Natural answers reach the right slug, and unclear ones still fail closed.

The four rejections below are the ones observed in a real WhatsApp session
(`logs/conversation-trace.md`): four of the eight menu-driven questions were
re-asked because the lead answered in a natural form.

These cases feed the scorer, so a wrong bucket is a wrong score — that is why
they are asserted here rather than left to manual checking.

v2 migration (``docs/v2-impact-analysis.md``): ``antiguedad_laboral`` cases
are removed (the field no longer exists); ``"soy independiente"`` now
resolves to the new, distinct ``independiente`` slug (column O of the v2
sheet separates it from ``Contrato de prestación de servicios``).
"""

from __future__ import annotations

import pytest

from app.graph.nodes._validators import validate_enumerated


@pytest.mark.parametrize(
    ("field", "answer", "expected"),
    [
        # ── Real rejections from the traced session (v1) ───────────────────
        ("rango_salarial", "8 millones", "4_8m"),
        ("contrato_laboral", "Fijo", "termino_fijo"),
        ("estado_civil", "casada", "casado"),
        # ── Money, written the ways Colombians write it ────────────────────
        ("rango_salarial", "$3.500.000", "2_4m"),
        ("rango_salarial", "14 millones", "mas_10m"),
        ("rango_salarial", "gano 9", "8_10m"),
        ("ahorros_o_cesantias", "no tengo", "ninguno"),
        ("ahorros_o_cesantias", "como 15 millones", "10_20m"),
        # ── Categorical shapes with a leading filler ──────────────────────
        # v2: `Independiente` is its own slug now (column O of the v2 sheet),
        # separate from `Prestacion de servicios`.
        ("contrato_laboral", "soy independiente", "independiente"),
        ("tiempo_compra_deseado", "lo antes posible", "3_meses"),
    ],
)
def test_natural_answers_resolve_to_the_documented_slug(field, answer, expected):
    assert validate_enumerated(field, answer) == expected


@pytest.mark.parametrize(
    ("field", "answer"),
    [
        ("contrato_laboral", "no sé"),
        ("rango_salarial", "depende"),
        ("rango_salarial", ""),
        # `TI` is not one of the five source document types and must not be
        # rescued into `CC` by any tolerance rule.
        ("tipo_documento", "TI"),
    ],
)
def test_unclear_answers_still_fail_closed(field, answer):
    """Tolerance widens the accepted shapes; it never guesses a value."""
    assert validate_enumerated(field, answer) is None


@pytest.mark.parametrize(
    ("field", "answer", "expected"),
    [
        ("rango_salarial", "mas de 10 millones", "mas_10m"),
        ("contrato_laboral", "Termino indefinido", "termino_indefinido"),
    ],
)
def test_the_exact_source_labels_are_unaffected(field, answer, expected):
    """The verbatim path still resolves first; tolerance is only a fallback."""
    assert validate_enumerated(field, answer) == expected


def test_the_band_edge_is_deterministic_and_matches_the_affiliate_derivation():
    """"8 millones" sits on a band edge worth three points of score.

    `derive_rango_salarial` buckets an affiliate's 8_000_000 as `4_8m` (bands
    are inclusive of their ceiling). A lead who types the same figure must land
    in the same bucket, or the score would depend on how the number arrived.
    """
    from app.graph.nodes._validators import derive_rango_salarial

    assert validate_enumerated("rango_salarial", "8 millones") == "4_8m"
    assert derive_rango_salarial(8_000_000) == "4_8m"
    assert validate_enumerated("rango_salarial", "8 millones") == derive_rango_salarial(
        8_000_000
    )
