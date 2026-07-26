"""Lead domain normalizer — verbatim source label → canonical slug.

Pure module: no DB, no LLM, no I/O. Deterministic and side-effect free.

The verbatim labels shown to the user/LLM come from the workbook
(`docs/Preguntas y modelo tabla de datos.xlsx`, sheet `Leads`). The scorer keys
exclusively off the canonical slugs returned here, so the two vocabularies meet
in exactly one place.

Closes: DATA-001, DATA-002, DATA-004, DATA-005, DATA-006, DATA-009, DATA-010.

Hard rule (audit): matching is EXACT after case-folding, accent-stripping and
whitespace-collapsing. Never substring-matches — the previous revision's
`"no" not in ahorro` test scored `Menos de $3 millones` as 0 because `"menos"`
contains `"no"`.

v2 migration (``docs/v2-impact-analysis.md``): ``tipo_documento`` gains
`Carné Diplomático`, ``contrato_laboral`` gains `Independiente` as its own
slug (separate from `Prestacion de servicios` — column O of the v2 sheet),
``antiguedad_laboral`` is removed (the field it backed no longer exists), and
two verbatim tables are added for the new ``interes_afiliacion`` and
``preferencia_vis`` fields.
"""

from __future__ import annotations

import unicodedata
from typing import Final

# ── Verbatim source label → canonical slug ─────────────────────────────────
# Keys are the workbook's verbatim labels. Lookup is performed over the
# case-folding + accent-stripping + whitespace-collapsing transform of both
# the key and the raw input, so accents and casing on the source labels do not
# have to be reproduced exactly by callers.

TIPO_DOCUMENTO: Final[dict[str, str]] = {
    "cédula de ciudadanía": "CC",
    "cédula de extranjería": "CE",
    "pasaporte": "PA",
    "permiso especial de permanencia": "PEP",
    "permiso por protección temporal": "PPT",
    "carné diplomático": "CD",  # v2 sheet row B8 — new sixth document type
}

ESTADO_CIVIL: Final[dict[str, str]] = {
    "soltero": "soltero",
    "casado": "casado",
    "divorciado": "divorciado",
    "union libre": "union_libre",
    "separado": "separado",
    "viudo": "viudo",
}

CONTRATO_LABORAL: Final[dict[str, str]] = {
    "termino fijo": "termino_fijo",
    "termino indefinido": "termino_indefinido",
    "prestacion de servicios": "prestacion_servicios",
    # v2 sheet column O: `Independiente` is its own option, separate from
    # `Contrato de prestación de servicios`. Column P (the old 3-value list)
    # disagrees and keeps `prestacion_servicios` doubling as independiente;
    # column O is followed here — see docs/v2-impact-analysis.md §4.
    "independiente": "independiente",
}

RANGO_SALARIAL: Final[dict[str, str]] = {
    "2 millones o menos": "hasta_2m",
    "2 a 4 millones": "2_4m",
    "4 a 8 millones": "4_8m",
    "8 a 10 millones": "8_10m",
    "mas de 10 millones": "mas_10m",
}

AHORROS_O_CESANTIAS: Final[dict[str, str]] = {
    "no tengo ahorros.": "ninguno",
    "menos de $3 millones": "menos_3m",
    "entre $3 y $10 millones": "3_10m",
    "entre $10 y $20 millones": "10_20m",
    "entre $20 y $40 millones": "20_40m",
    "más de $40 millones": "mas_40m",
}

TIEMPO_COMPRA_DESEADO: Final[dict[str, str]] = {
    "3 meses": "3_meses",
    "6 meses": "6_meses",
    "1 año": "1_ano",
    "2 años": "2_anos",
    "no sé": "no_se",
}

# v2: `¿Te gustaría iniciar tu proceso de afiliación a Colsubsidio?` — gated
# to the no-afiliado path (docs/v2-impact-analysis.md §5). Verbatim from sheet
# column I.
INTERES_AFILIACION: Final[dict[str, str]] = {
    "no, estoy afiliado a otra caja de compensación": "afiliado_otra_caja",
    "si estoy interesado en afiliarme": "interesado_afiliarse",
    "no, prefiero en otro momento.": "prefiere_otro_momento",
}

# v2: `¿Te interesan vivienda VIS, NO VIS o ambas?` (project-browsing loop).
PREFERENCIA_VIS: Final[dict[str, str]] = {
    "vis": "vis",
    "no vis": "no_vis",
    "ambas": "ambas",
}

# ── Boolean domain ─────────────────────────────────────────────────────────
# The `Leads` sheet stores its yes/no columns as the literals `SI` / `NO`, not
# as Python booleans. The scorer tests `is True`, so an un-normalized `'SI'`
# silently disabled every boolean rule — including the absolute
# subsidio-previo disqualifier. Same source-vocabulary-vs-code-vocabulary
# defect class as DATA-001..005, in the booleans.
BOOLEAN: Final[dict[str, bool]] = {
    "si": True,
    "sí": True,
    "no": False,
    "true": True,
    "false": False,
    "verdadero": True,
    "falso": False,
    "1": True,
    "0": False,
}

# Boolean `leads` columns. Registered here so `normalize(field, raw)` routes
# them through the boolean domain instead of returning None for an unknown
# field, and so every collection boundary has a single list to iterate.
#
# `otra_caja_compensacion` is intentionally NOT listed here even though it is
# now a `Boolean` column: it is never normalized from raw yes/no input, it is
# derived from `interes_afiliacion` (see `app.models.constants.
# OTRA_CAJA_COMPENSACION_TRIGGER`).
#
# v2 removes `condicion_discapacidad_familiar` and `cabeza_de_hogar` (fields
# no longer collected).
BOOLEAN_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "subsidio_vivienda_anterior",
        "tiene_vivienda_propia",
        "tiene_creditos_activos",
        "afiliado_colsubsidio",
    }
)

# Field name → verbatim→slug table. The keys here are the `lead_profile` /
# `leads` column names.
_TABLES: Final[dict[str, dict[str, str]]] = {
    "tipo_documento": TIPO_DOCUMENTO,
    "estado_civil": ESTADO_CIVIL,
    "contrato_laboral": CONTRATO_LABORAL,
    "rango_salarial": RANGO_SALARIAL,
    "ahorros_o_cesantias": AHORROS_O_CESANTIAS,
    "tiempo_compra_deseado": TIEMPO_COMPRA_DESEADO,
    "interes_afiliacion": INTERES_AFILIACION,
    "preferencia_vis": PREFERENCIA_VIS,
}

# ── Municipio normalization ────────────────────────────────────────────────
# The nine lead-facing options map to the project-catalogue vocabulary. The
# catalogue is unaccented for Bogota and Ubate but accented for Chía and
# Tocancipá; the values below reproduce the catalogue spelling exactly so a
# later join on `proyecto.municipio` matches.
MUNICIPIO_LEAD_TO_CATALOGO: Final[dict[str, str]] = {
    "Bogotá norte": "Bogota",
    "Bogotá centro": "Bogota",
    "Bogotásur": "Bogota",  # source typo, no space — preserved as the key
    "Soacha": "Soacha",
    "Chía": "Chía",
    "Tocancipá": "Tocancipá",
    "Girardot": "Girardot",
    "Ricaurte": "Ricaurte",
    "Ubaté": "Ubate",  # catalogue is unaccented
}

# Repair applied at lookup time ONLY; the stored proyecto row keeps 'VIS' verbatim.
MUNICIPIO_CATALOGO_REPAIR: Final[dict[str, str]] = {"VIS": "Bogota"}  # VIBO ONCE modelo B2


# ── Helpers ────────────────────────────────────────────────────────────────
def _fold(raw: str) -> str:
    """Lowercase, strip combining accents, collapse whitespace, trim ends.

    Exact-match key: never used for substring comparisons.
    """
    s = raw.strip().lower()
    # NFKD decomposition separates base letters from combining marks; the
    # filter drops the marks so 'á' → 'a', 'ñ' → 'n', 'é' → 'e'.
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = " ".join(s.split())  # collapse runs of whitespace to a single space
    return s


def _build_lookup(table: dict[str, str]) -> dict[str, str]:
    """A fold-keyed lookup where both verbatim labels and canonical slugs resolve.

    A canonical slug passed through `normalize` must return itself (the spec
    scenario: "matches no verbatim label AND no canonical slug" → None;
    therefore a value that IS a canonical slug is accepted).
    """
    folded: dict[str, str] = {_fold(k): v for k, v in table.items()}
    # Add the slug self-mappings (slug → slug) so already-normalized input
    # round-trips. The slug KEY must be folded too: document slugs are
    # uppercase for `tipo_documento` (CC/CE/PA/PEP/PPT), so `_fold("CC")` is
    # `"cc"`, not `"CC"`.
    for slug in table.values():
        folded.setdefault(_fold(slug), slug)
    return folded


_LOOKUPS: Final[dict[str, dict[str, str]]] = {
    field: _build_lookup(table) for field, table in _TABLES.items()
}

_MUNICIPIO_LOOKUP: Final[dict[str, str]] = _build_lookup(MUNICIPIO_LEAD_TO_CATALOGO)

_BOOLEAN_LOOKUP: Final[dict[str, bool]] = {_fold(k): v for k, v in BOOLEAN.items()}


# ── Public API ─────────────────────────────────────────────────────────────
def normalize_bool(raw: object) -> bool | None:
    """Normalize a workbook yes/no value to a real Python boolean.

    Accepts the `Leads` sheet vocabulary (`SI` / `NO`, any casing, with or
    without the accent on `Sí`), the usual `true`/`false` and
    `verdadero`/`falso` spellings, `1`/`0`, and real `bool`s.

    Returns:
        True, False, or None when the value matches nothing. Fails closed —
        an unrecognized value is NEVER coerced to False, so the consuming rule
        treats it as absent instead of as a silent negative (spec scenario
        *Unrecognized value fails closed*).
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, float) and not raw.is_integer():
        return None
    if isinstance(raw, float):
        raw = int(raw)
    key = _fold(str(raw))
    if not key:
        return None
    return _BOOLEAN_LOOKUP.get(key)


def normalize(field: str, raw: object) -> str | bool | None:
    """Exact, case- and accent-insensitive lookup of an enumerated lead field.

    Args:
        field: one of the enumerated lead-field names (tipo_documento,
            estado_civil, contrato_laboral, rango_salarial,
            ahorros_o_cesantias, tiempo_compra_deseado, interes_afiliacion,
            preferencia_vis) or one of :data:`BOOLEAN_FIELDS`.
        raw: the verbatim source label OR an already-canonical slug (for a
            boolean field, the workbook `SI`/`NO` literal or a real bool).

    Returns:
        The canonical slug — a `bool` for a field in :data:`BOOLEAN_FIELDS` —
        or None if the value matches no verbatim label and no canonical slug
        for the field. None in → None out. An unknown field name → None.

    Never guesses: an unrecognized value yields None so the consuming bucket
    contributes 0, rather than silently landing on a mid-range default. Never
    substring-matches.
    """
    if raw is None:
        return None
    if field in BOOLEAN_FIELDS:
        return normalize_bool(raw)
    table = _LOOKUPS.get(field)
    if table is None:
        return None
    key = _fold(str(raw))
    if not key:
        return None
    return table.get(key)


def normalize_municipio(raw: str | None) -> str | None:
    """Map a lead-facing `lugar_eleccion_vivir` option to the catalogue municipio.

    Returns the catalogue municipio name (Bogota, Chía, Tocancipá, …) the
    `proyectos_colsubsidio` rows use, or None for an unknown option.
    """
    if raw is None:
        return None
    key = _fold(str(raw))
    if not key:
        return None
    return _MUNICIPIO_LOOKUP.get(key)


def repair_catalogo_municipio(municipio: str | None) -> str | None:
    """Repair a stored proyecto municipio value at lookup time.

    Only the corrupt `municipio='VIS'` on the VIBO ONCE B2 row is repaired (to
    `Bogota`); the stored row is left untouched to preserve the source verbatim.
    """
    if municipio is None:
        return None
    return MUNICIPIO_CATALOGO_REPAIR.get(municipio, municipio)