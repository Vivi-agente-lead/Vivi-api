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
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from app.models.constants import (
    CAJA_COMPENSACION,
    CONTRATO_EMPLEADO,
    ESTADO_CIVIL_CON_PAREJA,
)
from app.services.domain_normalizer import normalize, normalize_municipio

__all__ = [
    "derive_tiene_pareja",
    "derive_es_empleado",
    "derive_cabeza_de_hogar",
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
    "parse_caja_compensacion",
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

_MESES: Final[dict[str, int]] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_ISO_DATE = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
_DMY_DATE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")
_TEXT_DATE = re.compile(r"\b(\d{1,2})\s+de\s+([a-z]+)\s+(?:de\s+|del\s+)?(\d{4})\b")
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


def derive_cabeza_de_hogar(profile: dict[str, Any]) -> bool:
    """Source note: "Si es soltero o casado y tiene PAC entonces SI".

    Leads without a partner are always cabeza de hogar; leads with a partner
    only when they have dependants. Applied at the end of every capacity bundle
    — the one place all four branches converge and where `numero_pac` is
    collected.
    """
    if not profile.get("tiene_pareja"):
        return True
    return (profile.get("numero_pac") or 0) > 0


# ── Audit note ──────────────────────────────────────────────────────────────
def note_rejected(field: str, raw: Any) -> str:
    """The `normalization_notes` line for a value the domain does not accept."""
    return f"Valor no reconocido para {field}: {raw!r}"


# ── Enumerated fields ───────────────────────────────────────────────────────
def validate_enumerated(field: str, raw: str | None) -> str | None:
    """Canonical slug for an enumerated lead field, or `None`.

    Delegates to `domain_normalizer.normalize`, which accepts both the verbatim
    source label the slice showed the person and the canonical slug.
    """
    if raw is None:
        return None
    return normalize(field, str(raw))


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


def parse_fecha_nacimiento(raw: str | None) -> date | None:
    """A birth date in ISO, `dd/mm/yyyy` or `12 de marzo de 1990` form.

    Returns `None` for anything unparseable or in the future — the age gate must
    never run on a guessed date.
    """
    if raw is None:
        return None
    text = fold(raw)
    if not text:
        return None

    parsed: date | None = None
    iso = _ISO_DATE.search(text)
    if iso is not None:
        parsed = _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    if parsed is None:
        dmy = _DMY_DATE.search(text)
        if dmy is not None:
            parsed = _safe_date(int(dmy.group(3)), int(dmy.group(2)), int(dmy.group(1)))
    if parsed is None:
        textual = _TEXT_DATE.search(text)
        if textual is not None:
            month = _MESES.get(textual.group(2))
            if month is not None:
                parsed = _safe_date(
                    int(textual.group(3)), month, int(textual.group(1))
                )
    if parsed is None or parsed > date.today():
        return None
    return parsed


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


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


def parse_caja_compensacion(raw: str | None) -> str | None:
    """A caja de compensación from the controlled vocabulary, or `ninguna`."""
    if raw is None:
        return None
    text = fold(raw)
    if not text:
        return None
    if text in {"ninguna", "ninguno", "no", "no tengo", "ninguna."}:
        return "ninguna"
    for caja in CAJA_COMPENSACION:
        if fold(caja) == text:
            return caja
    return None


def parse_free_text(raw: str | None, *, max_length: int = 2000) -> str | None:
    """Free-text answer, whitespace-collapsed and length-capped."""
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    if not text:
        return None
    return text[:max_length]
