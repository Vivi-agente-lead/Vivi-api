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

# Demo-star cedulas — verbatim from ``design.md`` §7.4. These are the seeded
# *afiliado* rows (``scripts/seed_colsubsidio.py``), documented here so the
# demo walkthrough and the tests share one source. They are NOT consulted by
# :func:`simulate_bureau_cedula`: an afiliado never takes the simulation path.
DEMO_CEDULA_SCORES: Final[dict[str, int]] = {
    "1010101010": 880,  # Andrea Marín — A — Excelente
    "2020202020": 720,  # Beto Salazar  — B — Bueno
    "3030303030": 580,  # Camila Ríos   — C — Regular
}

# One representative score per band of :data:`CREDIT_BANDS`, in descending
# order — ``design.md`` §7.3 verbatim. The table deliberately includes the Malo
# outcome (400): a simulated no-afiliado must be able to land in every band a
# real afiliado can, otherwise affiliation stops being a strictly positive
# signal (spec scenario *Affiliation is a strictly positive signal*). A floored
# range would guarantee the no-afiliado at least Regular while a real afiliado
# could band Malo.
_SIM_BANDS: Final[list[int]] = [820, 760, 710, 670, 600, 400]


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


def simulate_bureau_cedula(numero_documento: str | int | None) -> int:
    """Deterministic cedula-derived credit-score simulation (``design.md`` §7.3).

    Used only for **no-afiliado** leads, whose ``score_credito`` is not on file.
    The cedula's digits pick one band of :data:`_SIM_BANDS` by modulo, so the
    same ``numero_documento`` always yields the same score across process
    invocations (pure integer arithmetic — no randomness, no hash seed) and the
    scorer stays a total function of its inputs.

    A cedula with no digits (or an empty/absent value) returns the Malo band:
    an unusable document is not evidence of creditworthiness.
    """
    digits = "".join(ch for ch in str(numero_documento or "") if ch.isdigit())
    if not digits:
        return _SIM_BANDS[-1]
    return _SIM_BANDS[int(digits) % len(_SIM_BANDS)]