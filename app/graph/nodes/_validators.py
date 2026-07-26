"""Post-LLM field validators and the state derivations (`design.md` §4.1, §7.1).

Every value a collection node is about to merge into `lead_profile` passes
through this module first. Three rules hold everywhere:

1. **Never guess.** A value that does not match the source domain returns
   `None`, so the node re-asks and the scorer's bucket contributes `0` rather
   than landing on a mid-range default.
2. **Never substring-match.** Enumerated fields are resolved by
   `domain_normalizer.normalize`, which is exact after case-folding and
   accent-stripping. `"Menos de $3 millones"` must not be read as a `"no"`.
3. **Rejects are recorded.** `note_rejected` produces the audit line appended to
   `normalization_notes`, so the raw thing the lead actually said survives.

The module is pure: no DB, no LLM, no I/O.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from app.models.constants import CONTRATO_EMPLEADO, ESTADO_CIVIL_CON_PAREJA
from app.graph.nodes._tolerance import interpret
from app.services.domain_normalizer import normalize, normalize_municipio

__all__ = [
    "derive_tiene_pareja",
    "derive_es_empleado",
    "derive_rango_salarial",
    "fold",
    "note_rejected",
    "validate_enumerated",
    "validate_municipio",
    "parse_bool_si_no",
    "parse_int",
    "parse_decimal",
    "parse_fecha_nacimiento",
    "parse_numero_documento",
    "parse_nombre",
    "parse_free_text",
]

_MIN_DOC_DIGITS: Final[int] = 6
_MAX_DOC_DIGITS: Final[int] = 12

_SI: Final[frozenset[str]] = frozenset(
    {
        "si",
        "s",
        "sip",
        "claro",
        "claro que si",
        "correcto",
        "afirmativo",
        "dale",
        "listo",
        "por supuesto",
        "de una",
        "acepto",
        "autorizo",
        "estoy de acuerdo",
        "yes",
        "1",
        "true",
        "verdadero",
    }
)
_NO: Final[frozenset[str]] = frozenset(
    {
        "no",
        "n",
        "nop",
        "negativo",
        "para nada",
        "nunca",
        "jamas",
        "no acepto",
        "no autorizo",
        "no estoy de acuerdo",
        "0",
        "false",
        "falso",
    }
)
_CERO: Final[frozenset[str]] = frozenset(
    {"ninguno", "ninguna", "cero", "nadie", "no", "no tengo", "n/a", "ninguno."}
)

_INT = re.compile(r"-?\d+")
_MILLONES = re.compile(r"\b(millon|millones)\b")


def fold(raw: str) -> str:
    """Lowercase, strip combining accents, collapse whitespace, trim ends.

    Same transform the domain normalizer uses. Exact-match key only — never a
    substring probe.
    """
    text = unicodedata.normalize("NFKD", str(raw).strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


# ── Derivations ─────────────────────────────────────────────────────────────
def derive_tiene_pareja(estado_civil: str | None) -> bool:
    """`estado_civil in {casado, union_libre}`.

    `soltero`, `divorciado`, `separado` and `viudo` are all partnerless, and an
    unknown estado civil fails closed to `False` so the lead still reaches a
    `sin_pareja` bundle instead of falling off the graph.
    """
    return estado_civil in ESTADO_CIVIL_CON_PAREJA


def derive_es_empleado(contrato_laboral: str | None) -> bool:
    """`contrato_laboral in {termino_fijo, termino_indefinido}`.

    Derived from the specific contract slug the source offers; the literal
    `"empleado"` is not a member of the source domain and yields `False`.
    """
    return contrato_laboral in CONTRATO_EMPLEADO


def derive_rango_salarial(salario: Any) -> str | None:
    """Bucket an affiliate's `salario_base_cotizacion` into a `rango_salarial` slug.

    `design.md` §4: an affiliate is never asked for `rango_salarial` — "Preguntar
    solo si es empleado y NO es afiliado Colsubsidio" — and the value "is derived
    from `salario_base_cotizacion`". The design states the derivation exists but
    not its boundaries; they are read off the source option labels themselves
    ("2 millones o menos", "2 a 4 millones", …), each band being inclusive of its
    upper bound. Without this the scorer's income bucket would contribute 0 for
    every affiliate, which is the population the 90/10 target is built on.

    Returns `None` when there is no salary on the record — unknown is not
    average.
    """
    if salario is None:
        return None
    try:
        value = Decimal(str(salario))
    except (InvalidOperation, ValueError):
        return None
    if value <= 0:
        return None
    for ceiling, slug in _RANGO_SALARIAL_BANDS:
        if value <= ceiling:
            return slug
    return "mas_10m"


_RANGO_SALARIAL_BANDS: Final[tuple[tuple[Decimal, str], ...]] = (
    (Decimal(2_000_000), "hasta_2m"),
    (Decimal(4_000_000), "2_4m"),
    (Decimal(8_000_000), "4_8m"),
    (Decimal(10_000_000), "8_10m"),
)


# ── Audit note ──────────────────────────────────────────────────────────────
def note_rejected(field: str, raw: Any) -> str:
    """The `normalization_notes` line for a value the domain does not accept."""
    return f"Valor no reconocido para {field}: {raw!r}"


# ── Enumerated fields ───────────────────────────────────────────────────────
def validate_enumerated(field: str, raw: str | None) -> str | None:
    """Canonical slug for an enumerated lead field, or `None`.

    Two attempts, in order:

    1. `domain_normalizer.normalize` — exact after folding, accepting the
       verbatim source label the slice showed the person, or the slug.
    2. `_tolerance.interpret` — deterministic second chance for the shapes
       people actually type ("8 millones", "fijo", "mas de 2 años"). Money and
       duration are resolved numerically against the same band boundaries the
       affiliate derivation uses, never by similarity, so the score stays a
       pure function of the answer.

    Rule 1 of this module still holds: when both fail the result is `None`, the
    node re-asks and the bucket contributes `0`. Nothing here guesses.
    """
    if raw is None:
        return None
    text = str(raw)
    exact = normalize(field, text)
    if exact is not None:
        return exact
    return interpret(field, text)


def validate_municipio(raw: str | None) -> str | None:
    """Catalogue municipio for a lead-facing location option, or `None`."""
    if raw is None:
        return None
    return normalize_municipio(str(raw))


# ── Scalars ─────────────────────────────────────────────────────────────────
def parse_bool_si_no(raw: str | None) -> bool | None:
    """Yes/no answer → `True` / `False`, or `None` when it is neither.

    Exact match on the whole folded answer first, then on its first token, so
    `"no acepto"` reads as `False` without `"acepto"` ever being probed as a
    substring.
    """
    if raw is None:
        return None
    text = fold(raw)
    if not text:
        return None
    if text in _SI:
        return True
    if text in _NO:
        return False
    head = text.split(" ", 1)[0].strip(".,;:!¡¿?")
    if head in _SI:
        return True
    if head in _NO:
        return False
    return None


def parse_int(raw: str | None) -> int | None:
    """First integer in the answer, or `0` for an explicit "ninguno"."""
    if raw is None:
        return None
    text = fold(raw)
    if not text:
        return None
    if text in _CERO:
        return 0
    match = _INT.search(text)
    if match is None:
        return None
    try:
        return int(match.group())
    except ValueError:  # pragma: no cover — the regex already guarantees digits
        return None


def parse_decimal(raw: str | None) -> Decimal | None:
    """A Colombian money answer → `Decimal`.

    Understands `3500000`, `$3.500.000`, `3,500,000` and `3,5 millones`.
    Thousands separators are dropped; `millon`/`millones` multiplies by 10^6.
    """
    if raw is None:
        return None
    text = fold(raw)
    for token in ("$", "cop", "pesos", "peso", "aprox", "mas o menos"):
        text = text.replace(token, " ")
    text = " ".join(text.split())
    if not text:
        return None

    scaled = bool(_MILLONES.search(text))
    numeric = re.sub(r"[^0-9.,]", "", text)
    if not numeric:
        return None

    if scaled:
        # "3,5 millones" / "3.5 millones" — a single separator is a decimal point.
        numeric = numeric.replace(",", ".")
        if numeric.count(".") > 1:
            numeric = numeric.replace(".", "")
    else:
        numeric = numeric.replace(".", "").replace(",", "")

    try:
        value = Decimal(numeric)
    except InvalidOperation:
        return None
    if scaled:
        value *= Decimal(1_000_000)
    if value < 0:
        return None
    return value


def parse_numero_documento(raw: str | None) -> str | None:
    """The document number: digits only, 6 to 12 of them."""
    if raw is None:
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if _MIN_DOC_DIGITS <= len(digits) <= _MAX_DOC_DIGITS:
        return digits
    return None


def parse_nombre(raw: str | None) -> str | None:
    """A person's full name: at least two letters, no digits."""
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    if any(ch.isdigit() for ch in text):
        return None
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 2:
        return None
    return text


def parse_free_text(raw: str | None, *, max_length: int = 2000) -> str | None:
    """Free-text answer, whitespace-collapsed and length-capped."""
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    if not text:
        return None
    return text[:max_length]
