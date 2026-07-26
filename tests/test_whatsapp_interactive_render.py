"""`render_options` picks buttons for <=3 options and a list for 4+.

Exhaustive option-matrix coverage is intentionally out of scope — see the
apply-progress note. This only proves the button/list split and the two
Meta limits (button title <=20 chars, row title <=24 with the full label
preserved in the row description) that motivate that split.
"""

from __future__ import annotations

from app.services.whatsapp_interactive import (
    InteractiveButtons,
    InteractiveList,
    render_options,
)


def test_two_options_render_as_buttons() -> None:
    shape = render_options("tiene_vivienda_propia", ["Sí", "No"])
    assert isinstance(shape, InteractiveButtons)
    assert len(shape.buttons) == 2
    titles = {b["reply"]["title"] for b in shape.buttons}
    assert titles == {"Sí", "No"}
    # No slug table for a synthetic boolean field — id falls back to the label.
    ids = {b["reply"]["id"] for b in shape.buttons}
    assert ids == {"Sí", "No"}


def test_rango_salarial_renders_as_a_list_with_canonical_slug_ids() -> None:
    options = (
        "2 millones o menos",
        "2 a 4 millones",
        "4 a 8 millones",
        "8 a 10 millones",
        "mas de 10 millones",
    )
    shape = render_options("rango_salarial", options)
    assert isinstance(shape, InteractiveList)
    rows = shape.sections[0]["rows"]
    assert len(rows) == 5
    row_ids = {row["id"] for row in rows}
    # Canonical slugs, not verbatim labels — a tap arrives already normalized.
    assert row_ids == {"hasta_2m", "2_4m", "4_8m", "8_10m", "mas_10m"}


def test_option_over_20_chars_falls_through_to_a_list_not_a_button() -> None:
    """3 options, one over the 20-char button title limit -> list, not buttons."""
    options = ("Termino fijo", "Termino indefinido", "Prestacion de servicios")
    shape = render_options("contrato_laboral", options)
    assert isinstance(shape, InteractiveList)


def test_long_label_is_truncated_in_the_row_title_but_kept_in_description() -> None:
    long_label = "Permiso especial de permanencia"  # 31 chars > 24-char row title cap
    shape = render_options("tipo_documento", ["Cédula de ciudadanía", long_label])
    assert isinstance(shape, InteractiveList)
    row = next(r for r in shape.sections[0]["rows"] if r["description"] == long_label)
    assert len(row["title"]) <= 24
    assert row["title"] != long_label


def test_more_than_100_options_do_not_fit_anything() -> None:
    options = [f"Opcion {i}" for i in range(101)]
    assert render_options("otra_caja_compensacion", options) is None


def test_empty_options_do_not_fit_anything() -> None:
    assert render_options("rango_salarial", []) is None
