"""Canonical slug domains and controlled vocabularies for Colsubsidio leads.

The Enumerated columns on ``LeadColsubsidioEntity`` store **canonical slugs**
(never verbatim source labels). The verbatim→slug translation lives in
``app/services/domain_normalizer.py``; this module holds only the *resulting*
slug sets, the derived predicate source sets, the ``status`` domain, and the
controlled ``caja de compensación`` vocabulary taken verbatim from
``docs/Preguntas y modelo tabla de datos.xlsx`` (sheet ``Leads``).

Keeping the slug sets here (rather than inside the normalizer) lets the models
and repositories validate persisted values without importing the normalizer.
"""

from __future__ import annotations

from typing import Final

# ── Enumerated lead-field slug domains (Source Domain Normalization) ───────
# Verbatim labels for each field are listed in the `lead-scoring` spec under
# "Source Domain Normalization"; the normalizer maps every verbatim label to
# one of these slugs.

TIPO_DOCUMENTO: Final[frozenset[str]] = frozenset({"CC", "CE", "PA", "PEP", "PPT"})
ESTADO_CIVIL: Final[frozenset[str]] = frozenset(
    {"soltero", "casado", "divorciado", "union_libre", "separado", "viudo"}
)
CONTRATO_LABORAL: Final[frozenset[str]] = frozenset(
    {"termino_fijo", "termino_indefinido", "prestacion_servicios"}
)
RANGO_SALARIAL: Final[frozenset[str]] = frozenset(
    {"hasta_2m", "2_4m", "4_8m", "8_10m", "mas_10m"}
)
ANTIGUEDAD_LABORAL: Final[frozenset[str]] = frozenset({"menos_1a", "1_2a", "mas_2a"})
AHORROS_O_CESANTIAS: Final[frozenset[str]] = frozenset(
    {"ninguno", "menos_3m", "3_10m", "10_20m", "20_40m", "mas_40m"}
)
TIEMPO_COMPRA_DESEADO: Final[frozenset[str]] = frozenset(
    {"3_meses", "6_meses", "1_ano", "2_anos", "no_se"}
)

# ── Derived predicate source sets ──────────────────────────────────────────
# `tiene_pareja := estado_civil in ESTADO_CIVIL_CON_PAREJA`
# `es_empleado := contrato_laboral in CONTRATO_EMPLEADO`
ESTADO_CIVIL_CON_PAREJA: Final[frozenset[str]] = frozenset({"casado", "union_libre"})
CONTRATO_EMPLEADO: Final[frozenset[str]] = frozenset(
    {"termino_fijo", "termino_indefinido"}
)

# ── Afiliado categorias (Bucket 2 of the scorer) ───────────────────────────
CATEGORIA_AFILIADO: Final[frozenset[str]] = frozenset({"A", "B", "C"})

# ── Lead status domain ─────────────────────────────────────────────────────
# `profiling` is the only non-terminal status; the other three are terminal.
STATUS_DOMAIN: Final[frozenset[str]] = frozenset(
    {"profiling", "ready", "nurture", "nurture_social"}
)
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {"ready", "nurture", "nurture_social"}
)

# ── Caja de compensación vocabulary (sheet `Leads`, column `Caja de
#    Compensación`, transcribed verbatim) ─────────────────────────────────────
# `otra_caja_compensacion` accepts a member of this set, the literal `ninguna`,
# or NULL. The trailing `*` on `Comfamiliar Amazonas*` is preserved verbatim
# from the workbook (it is a footnote marker in the source sheet).
CAJA_COMPENSACION: Final[frozenset[str]] = frozenset(
    {
        "Cafam",
        "Compensar",
        "Colsubsidio",
        "Comfacundi",
        "Comfaboy",
        "Comfama",
        "Comfenalco Antioquia",
        "Comfamiliar Camacol",
        "Cajacopi",
        "Combarranquilla",
        "Comfamiliar Atlántico",
        "ComfaCauca",
        "Comfachocó",
        "Comfacor",
        "Comfamiliar Cartagena y Bolívar",
        "Comfamiliares",
        "Comfacesar",
        "ComfaGuajira",
        "Cajamag",
        "Cofrem",
        "Comfamiliar Huila",
        "Comfamiliar Nariño",
        "Comfenalco Quindío",
        "Comfamiliar Risaralda",
        "Comfenalco Santander",
        "Cajasan",
        "Cafaba",
        "ComfaOriente",
        "Comfasucre",
        "Comfatolima",
        "Comfenalco Valle",
        "Comfandi",
        "ComfaUnión",
        "Comfiar",
        "Comfacasanare",
        "Comfaca",
        "Comfaputumayo",
        "Comcaja",
        "Cajasai",
        "Comfamiliar Guajira",
        "Comfamiliar Amazonas*",
        "Comfamar",
    }
)

# Accepted values for `otra_caja_compensacion`: a caja name, `ninguna`, or NULL.
CAJA_COMPENSACION_OR_NINGUNA: Final[frozenset[str]] = CAJA_COMPENSACION | {"ninguna"}