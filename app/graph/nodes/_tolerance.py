"""Deterministic tolerance for natural answers to enumerated questions.

The exact normalizer (`domain_normalizer.normalize`) accepts only the verbatim
source label or the canonical slug. That protects the audit trail, but a real
lead does not type "4 a 8 millones" — they type "8 millones", "fijo",
"mas de 2 años". In the traced WhatsApp session four of the eight menu-driven
questions were rejected on the first attempt for exactly this reason.

This module is the second attempt, tried **only after** the exact match fails.
Two rules make it safe to sit in the value path:

1. **It is deterministic and pure.** No LLM, no I/O, no clock. Two identical
   answers always produce the same slug, so `Demo reproducibility` in the
   `lead-scoring` spec still holds.
2. **It resolves to a slug or to `None`.** It never invents a value and never
   substring-matches a domain label. When it returns `None` the caller re-asks,
   exactly as before.

Money and duration fields are resolved **numerically**, never by similarity,
and reuse the same band boundaries the affiliate derivation uses
(`_validators.derive_rango_salarial`). This matters: "8 millones" sits on a
band edge, and the difference between `4_8m` and `8_10m` is three points of
score. A judgement call there would make the score a function of who is asking.

Categorical fields fall back to a small synonym table of the shapes people
actually type. The table maps to slugs only — adding an entry can never widen
the domain.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from typing import Any, Final

__all__ = ["interpret"]


def _fold(raw: str) -> str:
    """Same folding the exact normalizer uses: lowercase, de-accent, collapse."""
    s = raw.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.split())


# ── Amounts ────────────────────────────────────────────────────────────────
# Colombian money is written many ways: "8 millones", "$3.500.000", "3,5
# millones", "14M". `_amount` reduces all of them to pesos.
_MAGNITUDE: Final[re.Pattern[str]] = re.compile(r"\b(millon(?:es)?|mill|mm?|palos?)\b")
_NUMBER: Final[re.Pattern[str]] = re.compile(r"\d[\d.,]*")

# Below this, a bare number cannot plausibly be a monthly salary or a savings
# balance in pesos, so it is read as a figure in millions ("gano 8" → 8M).
_BARE_NUMBER_IS_MILLIONS_BELOW: Final[int] = 100_000


def _to_decimal(token: str) -> Decimal | None:
    """`"3.500.000"` → 3500000, `"3,5"` → 3.5, `"8"` → 8."""
    t = token.strip().rstrip(".,")
    if not t:
        return None
    # A comma with 1-2 trailing digits is a decimal separator; dots are
    # thousands separators. Colombian convention, and the source spreadsheet
    # writes areas the same way ("56,29").
    if re.search(r",\d{1,2}$", t):
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(".", "").replace(",", "")
    try:
        return Decimal(t)
    except Exception:  # noqa: BLE001 — malformed number is simply not a number
        return None


def _amount(folded: str) -> Decimal | None:
    """Pesos expressed anywhere in a free-text answer, or `None`."""
    match = _NUMBER.search(folded)
    if match is None:
        return None
    value = _to_decimal(match.group())
    if value is None or value <= 0:
        return None
    if _MAGNITUDE.search(folded) or value < _BARE_NUMBER_IS_MILLIONS_BELOW:
        value *= 1_000_000
    return value


# Bands are inclusive of their ceiling and mirror `_validators._RANGO_SALARIAL_BANDS`
# and the `AHORROS_O_CESANTIAS` source labels respectively.
_RANGO_BANDS: Final[tuple[tuple[Decimal, str], ...]] = (
    (Decimal(2_000_000), "hasta_2m"),
    (Decimal(4_000_000), "2_4m"),
    (Decimal(8_000_000), "4_8m"),
    (Decimal(10_000_000), "8_10m"),
)
_AHORRO_BANDS: Final[tuple[tuple[Decimal, str], ...]] = (
    (Decimal(3_000_000), "menos_3m"),
    (Decimal(10_000_000), "3_10m"),
    (Decimal(20_000_000), "10_20m"),
    (Decimal(40_000_000), "20_40m"),
)
_NO_SAVINGS: Final[frozenset[str]] = frozenset(
    {"no", "nada", "ninguno", "ninguna", "cero", "0", "no tengo", "no tengo nada"}
)


def _bucket(value: Decimal, bands: tuple[tuple[Decimal, str], ...], over: str) -> str:
    for ceiling, slug in bands:
        if value <= ceiling:
            return slug
    return over


# ── Durations ──────────────────────────────────────────────────────────────
_YEAR_WORDS: Final[dict[str, int]] = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
}


def _years(folded: str) -> Decimal | None:
    """Duration in years, converting a months figure when that is what was said."""
    match = _NUMBER.search(folded)
    if match is not None:
        value = _to_decimal(match.group())
    else:
        value = next(
            (Decimal(n) for word, n in _YEAR_WORDS.items() if f" {word} " in f" {folded} "),
            None,
        )
    if value is None or value < 0:
        return None
    if re.search(r"\bmes(?:es)?\b", folded):
        value /= 12
    return value


def _antiguedad(folded: str) -> str | None:
    years = _years(folded)
    if years is None:
        return None
    # "mas de dos años" and "menos de un año" carry their answer in the
    # qualifier, not in the number.
    if re.search(r"\bmas de\b", folded) and years >= 2:
        return "mas_2a"
    if re.search(r"\bmenos de\b", folded) and years <= 1:
        return "menos_1a"
    if years < 1:
        return "menos_1a"
    if years <= 2:
        return "1_2a"
    return "mas_2a"


# ── Categorical synonyms ───────────────────────────────────────────────────
# Keys are folded. Values are canonical slugs, so no entry can widen a domain.
_SYNONYMS: Final[dict[str, dict[str, str]]] = {
    "contrato_laboral": {
        "fijo": "termino_fijo",
        "a termino fijo": "termino_fijo",
        "contrato fijo": "termino_fijo",
        "indefinido": "termino_indefinido",
        "a termino indefinido": "termino_indefinido",
        "contrato indefinido": "termino_indefinido",
        "de planta": "termino_indefinido",
        "nomina": "termino_indefinido",
        "independiente": "prestacion_servicios",
        "soy independiente": "prestacion_servicios",
        "prestacion": "prestacion_servicios",
        "prestacion de servicio": "prestacion_servicios",
        "servicios": "prestacion_servicios",
        "freelance": "prestacion_servicios",
        "por mi cuenta": "prestacion_servicios",
        "trabajo por mi cuenta": "prestacion_servicios",
    },
    "estado_civil": {
        "soltera": "soltero",
        "casada": "casado",
        "union libre": "union_libre",
        "en union libre": "union_libre",
        "conviviente": "union_libre",
        "vivo con mi pareja": "union_libre",
        "viuda": "viudo",
        "separada": "separado",
        "divorciada": "divorciado",
    },
    "tipo_documento": {
        "cc": "CC", "cedula": "CC", "cedula de ciudadania": "CC",
        "ti": None,  # not in the source domain — must keep failing
        "ce": "CE", "cedula de extranjeria": "CE", "extranjeria": "CE",
        "pa": "PA", "pasaporte": "PA",
        "pep": "PEP", "ppt": "PPT",
    },
    "tiempo_compra_deseado": {
        "ya": "3_meses", "ahora": "3_meses", "lo antes posible": "3_meses",
        "cuanto antes": "3_meses", "inmediato": "3_meses",
        "medio año": "6_meses", "seis meses": "6_meses",
        "un año": "1_ano", "1 año": "1_ano",
        "dos años": "2_anos", "2 años": "2_anos",
        "no se": "no_se", "ni idea": "no_se", "todavia no se": "no_se",
        "no estoy seguro": "no_se", "no estoy segura": "no_se",
    },
}
# `TI` is deliberately mapped to a falsy value above so the loop below skips it:
# the source offers five document types and `TI` is not one of them.
_SYNONYMS["tipo_documento"] = {
    k: v for k, v in _SYNONYMS["tipo_documento"].items() if v
}


_NUMERIC_FIELDS: Final[frozenset[str]] = frozenset(
    {"rango_salarial", "ahorros_o_cesantias", "antiguedad_laboral"}
)


def interpret(field: str, raw: Any) -> str | None:
    """Second-chance slug for a free-text answer, or `None` to re-ask.

    Called only after `domain_normalizer.normalize` has already failed.
    """
    if raw is None:
        return None
    folded = _fold(str(raw))
    if not folded:
        return None

    if field == "rango_salarial":
        amount = _amount(folded)
        return _bucket(amount, _RANGO_BANDS, "mas_10m") if amount else None

    if field == "ahorros_o_cesantias":
        if folded in _NO_SAVINGS:
            return "ninguno"
        amount = _amount(folded)
        return _bucket(amount, _AHORRO_BANDS, "mas_40m") if amount else None

    if field == "antiguedad_laboral":
        return _antiguedad(folded)

    table = _SYNONYMS.get(field)
    if not table:
        return None
    if folded in table:
        return table[folded]
    # Allow a leading filler ("soy casado", "es indefinido") without ever
    # substring-matching a domain label: the remainder must be a whole key.
    for prefix in ("soy ", "estoy ", "es ", "tengo ", "trabajo "):
        if folded.startswith(prefix):
            rest = folded[len(prefix) :]
            if rest in table:
                return table[rest]
    return None
