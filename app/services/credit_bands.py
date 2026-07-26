"""Credit-band lookup and bureau simulation for the Colsubsidio lead scorer.

The bands and their point allocations are reproduced **verbatim** from
``docs/Preguntas y modelo tabla de datos.xlsx`` (sheet *Afiliados Colsubsidio*,
legend cells ``R3:R8`` — also mirrored with descriptions at ``O18:O23``):

    150-499 pts: Malo / Riesgo Alto
    500-649 pts: Regular / En construcción
    650-699 pts: Aceptable / Riesgo Medio
    700-749 pts: Bueno                    (umbral mínimo recomendado créditos hipotecarios)
    750-799 pts: Muy Bueno
    800-950 pts: Excelente / Premium

A NULL/unknown ``score_credito`` is treated as not creditworthy and maps to
``(0, "Malo")`` — the source legend has no row for the missing case, so the
design decision (``design.md`` §6 / §7.3) governs.

This module is pure: no LLM, no network, no DB. It must stay import-safe so the
graph, the scorer, the tools layer and the tests can all reach it without
spinning up a database.
"""

from __future__ import annotations

import hashlib
from typing import Final

__all__ = [
    "CREDIT_BANDS",
    "DEMO_CEDULA_SCORES",
    "band_from_score_credito",
    "simulate_bureau_cedula",
]

# Each tuple: (low, high, label, points). Bands are inclusive on both ends and
# contiguous — a lookup walks the list in declared order and returns the first
# match. Points are the per-bucket contribution documented in ``design.md`` §7.3
# and the ``lead-scoring`` spec scenario *Bucket 1 — Credito*.
CREDIT_BANDS: Final[list[tuple[int, int, str, int]]] = [
    (800, 950, "Excelente", 25),
    (750, 799, "Muy Bueno", 22),
    (700, 749, "Bueno", 18),
    (650, 699, "Aceptable", 12),
    (500, 649, "Regular", 6),
    (150, 499, "Malo", 0),
]

# Demo-star cedulas — verbatim from ``design.md`` §7.4. Harcoding them here keeps
# the live demo reproductible even when the afiliado seed table is empty: the
# same cedula always yields the same ``score_credito`` the seeded afiliado row
# would have carried, so the demo can drive ``simulate_bureau_cedula`` directly.
DEMO_CEDULA_SCORES: Final[dict[str, int]] = {
    "1010101010": 880,  # Andrea Marín — A — Excelente
    "2020202020": 720,  # Beto Salazar  — B — Bueno
    "3030303030": 580,  # Camila Ríos   — C — Regular
}

# The deterministic fallback band for a no-afiliado cedula is constrained to
# [550, 850] so the live demo always lands inside a real (non-Malo) band and
# the 90/10 differential stays observable. Anything below 500 (Malo) would
# collapse Bucket-1 of no-afiliado to 0 for almost every cedula, hiding the
# threshold lever that the ``lead-scoring`` spec (90/10) and case 12 rely on.
_SIM_FLOOR: Final[int] = 550
_SIM_CEIL: Final[int] = 850


def band_from_score_credito(score_credito: int | None) -> tuple[int, str]:
    """Return ``(points, label)`` for a 150-950 credit score.

    NULL / unknown → ``(0, "Malo")`` per the design decision that an unknown
    credit score is not creditworthy (the bucket contributes 0, never a
    mid-range default — see spec scenario *Unrecognized value fails closed*).
    """
    if score_credito is None:
        return (0, "Malo")
    for lo, hi, label, pts in CREDIT_BANDS:
        if lo <= score_credito <= hi:
            return (pts, label)
    # Out-of-range scores (negative, 0, or above 950) are treated as Malo
    # rather than rewarded for an impossible ceiling.
    return (0, "Malo")


def simulate_bureau_cedula(numero_documento: str) -> int:
    """Deterministic cedula-derived credit-score simulation.

    Used only for **no-afiliado** leads whose ``score_credito`` is not on file.
    Same ``numero_documento`` always yields the same ``score_credito`` across
    process invocations (pure-Python, no randomness), so the scorer stays a
    total function of its inputs.

    Order of resolution:

    1. A member of :data:`DEMO_CEDULA_SCORES` returns the demo-band score.
    2. Any other cedula returns a SHA-256-derived score in
       ``[_SIM_FLOOR, _SIM_CEIL]`` (550-850) so the demo always lands in a
       real band.
    3. A cedula with no digits (or an empty string) falls back to ``_SIM_FLOOR``
       rather than 0 — missing input is not a disaster scenario in the demo.
    """
    if numero_documento in DEMO_CEDULA_SCORES:
        return DEMO_CEDULA_SCORES[numero_documento]
    digits = "".join(ch for ch in (numero_documento or "") if ch.isdigit())
    if not digits:
        return _SIM_FLOOR
    digest = hashlib.sha256(digits.encode("utf-8")).digest()
    n = int.from_bytes(digest[:8], "big")
    return _SIM_FLOOR + (n % (_SIM_CEIL - _SIM_FLOOR + 1))