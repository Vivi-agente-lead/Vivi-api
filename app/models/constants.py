"""Canonical slug domains and controlled vocabularies for Colsubsidio leads.

The Enumerated columns on ``LeadColsubsidioEntity`` store **canonical slugs**
(never verbatim source labels). The verbatim→slug translation lives in
``app/services/domain_normalizer.py``; this module holds only the *resulting*
slug sets, the derived predicate source sets, the ``status`` domain, and the
(legacy, see note below) controlled ``caja de compensación`` vocabulary taken
verbatim from ``docs/Preguntas y modelo tabla de datos.xlsx`` (sheet ``Leads``).

Keeping the slug sets here (rather than inside the normalizer) lets the models
and repositories validate persisted values without importing the normalizer.

v2 migration (``docs/v2-impact-analysis.md``): ``tipo_documento`` gains a
sixth option, ``contrato_laboral`` gains a fourth (``independiente``, now
distinct from ``prestacion_servicios``), the ``status`` domain is renamed, and
two new enumerated domains are added (``INTERES_AFILIACION``,
``PREFERENCIA_VIS``). ``ANTIGUEDAD_LABORAL`` is removed: the field it backed
(``antiguedad_laboral``) is absent from the v2 sheet's capacity question.
"""

from __future__ import annotations

from typing import Final

# ── Enumerated lead-field slug domains (Source Domain Normalization) ───────
# Verbatim labels for each field are listed in the `lead-scoring` spec under
# "Source Domain Normalization"; the normalizer maps every verbatim label to
# one of these slugs.

# v2 sheet, column B (`Leads`): six document types — `Carné Diplomático` is
# new (row B8). `CD` follows the two-letter convention of the other five.
TIPO_DOCUMENTO: Final[frozenset[str]] = frozenset({"CC", "CE", "PA", "PEP", "PPT", "CD"})
ESTADO_CIVIL: Final[frozenset[str]] = frozenset(
    {"soltero", "casado", "divorciado", "union_libre", "separado", "viudo"}
)
# v2 sheet, column N/O: four contract types. Column O lists
# `Contrato de prestación de servicios` and `Independiente` as two SEPARATE
# options; column P (the old three-value list) disagrees and keeps
# `prestacion_servicios` doubling as the independiente bucket. Column O is
# followed here (see docs/v2-impact-analysis.md §4 and the apply report for
# why): `independiente` is its own slug, `prestacion_servicios` no longer
# covers it.
CONTRATO_LABORAL: Final[frozenset[str]] = frozenset(
    {"termino_fijo", "termino_indefinido", "prestacion_servicios", "independiente"}
)
RANGO_SALARIAL: Final[frozenset[str]] = frozenset(
    {"hasta_2m", "2_4m", "4_8m", "8_10m", "mas_10m"}
)
AHORROS_O_CESANTIAS: Final[frozenset[str]] = frozenset(
    {"ninguno", "menos_3m", "3_10m", "10_20m", "20_40m", "mas_40m"}
)
TIEMPO_COMPRA_DESEADO: Final[frozenset[str]] = frozenset(
    {"3_meses", "6_meses", "1_ano", "2_anos", "no_se"}
)

# ── New in v2 ────────────────────────────────────────────────────────────
# `¿Te gustaría iniciar tu proceso de afiliación a Colsubsidio?` (sheet column
# H/I). Gated to the no-afiliado path only (product decision recorded in
# `docs/v2-impact-analysis.md` §5): an afiliado never sees this question, so
# `interes_afiliacion` stays NULL for them.
INTERES_AFILIACION: Final[frozenset[str]] = frozenset(
    {"afiliado_otra_caja", "interesado_afiliarse", "prefiere_otro_momento"}
)
# `¿Te interesan vivienda VIS, NO VIS o ambas?` (flow node, project-browsing
# loop).
PREFERENCIA_VIS: Final[frozenset[str]] = frozenset({"vis", "no_vis", "ambas"})

# ── Derived predicate source sets ──────────────────────────────────────────
# `tiene_pareja := estado_civil in ESTADO_CIVIL_CON_PAREJA`
# `es_empleado := contrato_laboral in CONTRATO_EMPLEADO`
ESTADO_CIVIL_CON_PAREJA: Final[frozenset[str]] = frozenset({"casado", "union_libre"})
# `independiente` and `prestacion_servicios` are both NOT `es_empleado` — the
# v2 split does not change which contracts count as salaried employment.
CONTRATO_EMPLEADO: Final[frozenset[str]] = frozenset(
    {"termino_fijo", "termino_indefinido"}
)

# ── `otra_caja_compensacion` derivation (sheet column J, verbatim) ─────────
# "La respuesta es 'No, estoy afiliado a otra caja de compensación' setear en
# SI de lo contrario NO" — i.e. `otra_caja_compensacion` is `True` only when
# `interes_afiliacion == "afiliado_otra_caja"`. Never asked directly.
OTRA_CAJA_COMPENSACION_TRIGGER: Final[str] = "afiliado_otra_caja"

# ── Afiliado categorias (Bucket 2 of the scorer) ───────────────────────────
CATEGORIA_AFILIADO: Final[frozenset[str]] = frozenset({"A", "B", "C"})

# ── Lead status domain ─────────────────────────────────────────────────────
# `profiling` is the only non-terminal status; the other three are terminal.
# v2 renames the terminal vocabulary to match the flow's three explicit
# terminal nodes (`Calificado` / `Nutrible` / `No calificado`):
#   ready → calificado, nurture → nutrible, nurture_social → no_calificado.
STATUS_DOMAIN: Final[frozenset[str]] = frozenset(
    {"profiling", "calificado", "nutrible", "no_calificado"}
)
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {"calificado", "nutrible", "no_calificado"}
)

# ── Caja de compensación vocabulary — DELETED by the graph-topology migration
# (docs/v2-impact-analysis.md §5). The 43-name `CAJA_COMPENSACION` vocabulary
# and its `CAJA_COMPENSACION_OR_NINGUNA` companion, kept in this module by
# step 1 only so `app/graph/nodes/_validators.py` and `app/prompts/slices.py`
# kept importing, are removed together with their last call sites in this
# change: the caja-name question is replaced by the `interes_afiliacion`
# boolean derivation above.
