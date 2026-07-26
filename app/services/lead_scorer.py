"""Pure-Python lead scorer for Colsubsidio profiling.

Implements the scoring matrix in ``design.md`` §7.3 and the ``lead-scoring``
spec, re-budgeted for the v2 field set (``docs/v2-impact-analysis.md``). Six
additive buckets summing to exactly 100, then additive red-flag adjustments,
then a clamp to ``[0, 100]``. Classification is a deterministic function of
the clamped score, the affiliation flag, and the ``subsidio_vivienda_anterior``
absolute override.

The scorer:

* takes a dict-like ``lead`` profile (any object implementing ``.get``) and an
  optional ``afiliado`` dict carrying ``score_credito`` and
  ``categoria_afiliado``;
* performs **exact canonical-slug lookups** — never substring matches — so a
  value that escaped the normalizer is recorded as the bucket's ``0`` (spec
  scenario *Unrecognized value fails closed*);
* owns no I/O: no LLM, no network, no DB session, no SQLAlchemy import;
* is a total function of its inputs — the same ``(lead, afiliado)`` tuple
  always yields the same return tuple (spec scenario *Demo reproducibility*).

The persisted ``lead.status`` MUST carry the same value as the returned
``classification`` from the single domain ``{"calificado", "nutrible",
"no_calificado"}``.

v2 re-budget (``docs/v2-impact-analysis.md`` §10, §12): v2 removes
``antiguedad_laboral``, so **Bucket 6** no longer scores contract-tenure
"Estabilidad" — it is replaced by **Capacidad** (disposable-income ratio),
computed from the two figures v2 now collects on every lead,
``total_ingresos_mensuales`` and ``gastos_mensuales``. The bucket keeps its
15-point ceiling, so the six maxima still sum to exactly 100. The ``+8``
bonus loses its ``condicion_discapacidad_familiar`` trigger (field removed);
only ``numero_pac > 0`` remains, unchanged at ``+8``. A new, separate
``pos_subsidio`` rule (not a scored bucket) mirrors the v2 diagram's
``Setear variable pos_subsidio = 0`` node.

Graph-topology migration (the ``-15`` VIS red flag, decided): v2 collects
``preferencia_vis`` as a stated field. ``_vis_preference`` fires the flag on
the stated ``vis``/``ambas`` answer when present, falling back to the
project-lookup-derived ``vis_recommended`` only when it is not.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, TypedDict

from app.services.credit_bands import band_from_score_credito, simulate_bureau_cedula
from app.services.domain_normalizer import normalize_bool

__all__ = [
    "READY_THRESHOLD_AFILIADO",
    "READY_THRESHOLD_NO_AFILIADO",
    "NURTURE_FLOOR",
    "INGRESO_PTS",
    "AHORRO_PTS",
    "TIEMPO_PTS",
    "CATEGORIA_PTS",
    "CAPACIDAD_BANDS",
    "POS_SUBSIDIO_DISPONIBLE",
    "POS_SUBSIDIO_NO_DISPONIBLE",
    "ScoringResult",
    "score_lead",
    "classify_lead",
    "compute_pos_subsidio",
    "build_scoring_result",
]

# ── READY / NURTURE thresholds (design §7.3 + §13.3) ─────────────────────────
# Afiliado reaches READY at 60; no-afiliado needs 75. Subsidio previo overrides
# both thresholds absolutely. NURTURE_FLOOR (30) splits nutrible from
# no_calificado when the override fires or when READY is not reached.
READY_THRESHOLD_AFILIADO: int = 60
READY_THRESHOLD_NO_AFILIADO: int = 75
NURTURE_FLOOR: int = 30

# ── Bucket lookups (design §7.3, re-budgeted per docs/v2-impact-analysis.md) ─
# Every bucket scores 0 for a NULL or unrecognized value — never a mid-range
# default. The previous revision's mid-range fallbacks inflated leads whose
# data was never collected (audit finding "unknown is not average").
INGRESO_PTS: dict[str, int] = {
    "mas_10m": 20,
    "8_10m": 17,
    "4_8m": 14,
    "2_4m": 10,
    "hasta_2m": 5,
}
AHORRO_PTS: dict[str, int] = {
    "mas_40m": 15,
    "20_40m": 14,
    "10_20m": 12,
    "3_10m": 9,
    "menos_3m": 5,  # spec scenario: "menos_3m" MUST score 5, not 0 (DATA-003)
    "ninguno": 0,
}
TIEMPO_PTS: dict[str, int] = {
    "3_meses": 10,
    "6_meses": 8,
    "1_ano": 5,
    "2_anos": 2,
    "no_se": 0,
}
CATEGORIA_PTS: dict[str, int] = {"A": 15, "B": 11, "C": 7}

# ── Bucket 6 — Capacidad (max 15) ────────────────────────────────────────────
# v2 removes `antiguedad_laboral`; the old Estabilidad bucket (contract type ×
# tenure) has no input left. It is replaced by a disposable-income ratio,
# computed from the two figures v2 now asks of every lead:
#
#     ratio = (total_ingresos_mensuales - gastos_mensuales) / total_ingresos_mensuales
#
# Disposable income as a share of income is a stronger purchasing-capacity
# signal than tenure ever was, and it is the reason v2 added the expenses
# question in the first place (docs/v2-impact-analysis.md §4, §10). Bands are
# this change's own design decision (not stated verbatim in either v2 source
# document) and are documented here in full:
#
#   ratio >= 0.50            → 15 pts  ("holgura alta": half of income is free)
#   0.35 <= ratio <  0.50    → 11 pts  ("holgura media-alta")
#   0.20 <= ratio <  0.35    →  7 pts  ("holgura media")
#   0.05 <= ratio <  0.20    →  3 pts  ("holgura baja")
#   ratio <  0.05            →  0 pts  (expenses consume essentially all income)
#
# A NULL/unrecognized income or expense figure, or a non-positive income,
# contributes 0 — unknown is not average, the same rule every other bucket
# follows. Bands are inclusive of their floor and evaluated in descending
# order; a ratio of exactly 0.50 lands in the top band.
CAPACIDAD_BANDS: tuple[tuple[Decimal, int], ...] = (
    (Decimal("0.50"), 15),
    (Decimal("0.35"), 11),
    (Decimal("0.20"), 7),
    (Decimal("0.05"), 3),
)

# ── `pos_subsidio` rule (not a scored bucket) ────────────────────────────────
# v2 diagram: the no-afiliado branch of `¿Te gustaría iniciar tu proceso de
# afiliación a Colsubsidio?` labelled `SI` ("No, estoy afiliado a otra caja de
# compensación") leads to `Setear variable pos_subsidio = 0`. Being affiliated
# elsewhere removes the Colsubsidio subsidy possibility — it reduces
# purchasing capacity but does NOT disqualify the lead (subsidio_vivienda_
# anterior remains the only absolute disqualifier). Kept as its own named
# rule, never folded into a bucket, so it is independently testable and
# surfaces its own line in `classification_reasoning`. It does not change the
# numeric score: neither v2 source document states a point penalty, only the
# flag assignment.
POS_SUBSIDIO_DISPONIBLE: int = 1
POS_SUBSIDIO_NO_DISPONIBLE: int = 0
POS_SUBSIDIO_ZERO_REASON: str = (
    "Posibilidad de subsidio Colsubsidio: 0 (afiliado a otra caja de compensación)"
)

# Reasoning string the spec scenario *Subsidio previo absolute override* MUST
# contain verbatim. Centralised so the test does not duplicate the literal.
SUBSIDIO_PREVIO_REASON: str = (
    "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"
)


class ScoringResult(TypedDict):
    """Structured view of a scoring verdict.

    Provided as a convenience for callers that prefer a single dict over the
    spec-mandated 4-tuple. The persisted ``leads`` row keeps the 4-tuple's
    members on its columns (``score``, ``status``, ``classification_reasoning``,
    ``score_rating``); ``classification`` mirrors ``status``.
    """

    score: int                 # 0..100 post-clamp
    status: str                # one of {"calificado", "nutrible", "no_calificado"}
    classification: str        # alias of status (single source of truth)
    rating_label: str          # credit-band label of score_credito
    reasoning: str             # multi-line audit text
    breakdown: dict[str, int]  # per-bucket points (plus the "ajustes" red flags)


def _get(profile: Mapping[str, Any] | None, key: str, default: Any = None) -> Any:
    """Dict-style ``.get`` tolerant of ``None`` profiles."""
    if profile is None:
        return default
    return profile.get(key, default)


def _as_int(value: Any) -> int | None:
    """Best-effort integer coercion; an uncoercible value behaves as absent.

    LLM-supplied numerics plausibly arrive as strings (``"2"``, ``"2.0"``), and
    the scorer must stay a total function of its inputs — comparing ``"2" > 0``
    raised ``TypeError``. ``bool`` is deliberately rejected: a flag is not a
    count.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        as_float = float(text)
    except ValueError:
        return None
    return int(as_float) if math.isfinite(as_float) else None


def _as_decimal(value: Any) -> Decimal | None:
    """Best-effort ``Decimal`` coercion; an uncoercible value behaves as absent.

    Mirrors :func:`_as_int`'s defensiveness (D4 regression: the scorer is a
    total function of its inputs) for the two money fields the Capacidad
    bucket reads — ``total_ingresos_mensuales`` and ``gastos_mensuales`` may
    arrive as ``Decimal`` (from the ORM), ``float``/``int`` (LLM-supplied), or
    ``str``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _int_field(profile: Mapping[str, Any] | None, key: str) -> int | None:
    """Read a numeric lead field, coerced. Uncoercible → ``None`` (absent)."""
    return _as_int(_get(profile, key))


def _flag(profile: Mapping[str, Any] | None, key: str) -> bool | None:
    """Read a boolean lead field through the domain normalizer.

    The workbook stores its yes/no columns as the literals ``SI`` / ``NO``, and
    an LLM may echo either those or a real ``bool``. Routing every boolean read
    through :func:`normalize_bool` keeps the scorer's ``is True`` tests keyed
    off one vocabulary. An unrecognized value yields ``None`` (fail closed) —
    it is treated as absent, never as a silent ``False``.
    """
    return normalize_bool(_get(profile, key))


def _capacidad_pts(ingreso: Any, gastos: Any) -> tuple[int, Decimal | None]:
    """Bucket 6 — Capacidad (max 15). Returns ``(points, ratio)``.

    ``ratio`` is returned (possibly ``None``) purely for the reasoning line;
    the scorer never re-derives it.
    """
    ingreso_dec = _as_decimal(ingreso)
    gastos_dec = _as_decimal(gastos)
    if ingreso_dec is None or gastos_dec is None or ingreso_dec <= 0:
        return 0, None
    ratio = (ingreso_dec - gastos_dec) / ingreso_dec
    for floor, pts in CAPACIDAD_BANDS:
        if ratio >= floor:
            return pts, ratio
    return 0, ratio


def _vis_preference(lead: Mapping[str, Any] | None) -> bool:
    """Whether the lead's preference points at a VIS project — v2 graph-topology
    migration (``docs/v2-impact-analysis.md`` §4, §12 "The VIS red flag").

    v2 collects `preferencia_vis` (`vis`, `no_vis`, `ambas`) as a stated
    answer instead of only deriving `vis_recommended` from the project
    lookup. The `-15` red flag fires on the **stated** preference (`vis` or
    `ambas`) when it is present, falling back to the derived
    `vis_recommended` only when `preferencia_vis` was never collected — which
    is every lead on the linear qualification flow this change ships, since
    `preferencia_vis` is asked only inside the not-yet-built project-browsing
    loop (`docs/v2-impact-analysis.md` §1, §8). A stated `no_vis` therefore
    suppresses the flag even when `vis_recommended` derived `True`.
    """
    stated = _get(lead, "preferencia_vis")
    if stated is not None:
        return stated in ("vis", "ambas")
    return _get(lead, "vis_recommended") is True


def compute_pos_subsidio(is_afiliado: bool, otra_caja_compensacion: bool | None) -> int:
    """The v2 diagram's ``Setear variable pos_subsidio = 0`` rule.

    Reachable only on the no-afiliado path — the affiliation question
    (`interes_afiliacion`) is gated to non-affiliates (product decision,
    ``docs/v2-impact-analysis.md`` §5), so an afiliado's `otra_caja_
    compensacion` is always ``None`` and can never trip this rule.

    Tested with ``is True`` (never truthiness): ``None`` (afiliado, or a
    no-afiliado who has not yet answered) must NOT be treated as "affiliated
    elsewhere".

    Returns:
        :data:`POS_SUBSIDIO_NO_DISPONIBLE` (``0``) when the no-afiliado lead
        is affiliated elsewhere; :data:`POS_SUBSIDIO_DISPONIBLE` (``1``)
        otherwise.
    """
    if not is_afiliado and otra_caja_compensacion is True:
        return POS_SUBSIDIO_NO_DISPONIBLE
    return POS_SUBSIDIO_DISPONIBLE


def score_lead(
    lead: Mapping[str, Any] | None,
    afiliado: Mapping[str, Any] | None = None,
) -> tuple[int, str, str, str]:
    """Score a lead profile against the Colsubsidio matrix.

    Args:
        lead: the working ``lead_profile`` dict (or any mapping). Accepts
            ``None`` for the unit test path.
        afiliado: the afiliado record dict carrying ``score_credito`` and
            ``categoria_afiliado``. ``None`` (or a dict without those keys)
            selects the no-afiliado path: Bucket 1 falls back to
            :func:`simulate_bureau_cedula` and Bucket 2 contributes 0.

    Returns:
        ``(score, rating_label, classification, reasoning)`` — the tuple the
        ``lead-scoring`` spec mandates for the ``score_lead`` signature.
    """
    notes: list[str] = []

    # ── Bucket 1: Credito (max 25) ───────────────────────────────────────────
    # Afiliado's score_credito is the afiliado record's; no-afiliado's is
    # cedula-derived from the bureau simulation. An afiliado whose
    # score_credito is NULL stays on the afiliado branch and contributes 0 /
    # "Malo" — falling through to the simulation would fabricate a credit band
    # out of their own document number (spec Bucket 1).
    if afiliado:
        score_credito = _as_int(afiliado.get("score_credito"))
        credit_pts, rating_label = band_from_score_credito(score_credito)
    else:
        score_credito = simulate_bureau_cedula(_get(lead, "numero_documento", ""))
        credit_pts, rating_label = band_from_score_credito(score_credito)
        notes.append(
            "Banda crediticia estimada con simulado bureau (no afiliado)"
        )

    # ── Bucket 2: Afiliacion (max 15) ────────────────────────────────────────
    # No-afiliado scores 0 here so every afiliado categoria ranks strictly
    # above it — the first of the two 90/10 structural levers.
    cat = (afiliado or {}).get("categoria_afiliado") if afiliado else None
    cat_pts = CATEGORIA_PTS.get(cat, 0)

    # ── Bucket 3: Ingreso (max 20) ───────────────────────────────────────────
    ingreso_slug = _get(lead, "rango_salarial")
    ingreso_pts = INGRESO_PTS.get(ingreso_slug)

    # ── Bucket 4: Ahorro (max 15) — exact slug lookup, never substring ───────
    # Audit DATA-003: the previous revision tested `"no" not in ahorro`, which
    # scored `"menos_3m"` as 0 because `"menos"` contains `"no"`. Exact lookup
    # makes `"menos_3m"` score 5.
    ahorro_pts = AHORRO_PTS.get(_get(lead, "ahorros_o_cesantias"))

    # ── Bucket 5: Tiempo de compra (max 10) ──────────────────────────────────
    tiempo_pts = TIEMPO_PTS.get(_get(lead, "tiempo_compra_deseado"))

    # ── Bucket 6: Capacidad (max 15) — replaces the removed Estabilidad ──────
    # v2 removes `antiguedad_laboral`; disposable income vs. household income
    # is the replacement signal (see the module docstring / CAPACIDAD_BANDS).
    capacidad_pts, capacidad_ratio = _capacidad_pts(
        _get(lead, "total_ingresos_mensuales"), _get(lead, "gastos_mensuales")
    )

    # ── Red flags (additive, applied to the sum, then clamped) ───────────────
    # Every lead-supplied boolean is read through the normalizer (`_flag`), so
    # the workbook's `SI`/`NO` literals drive these rules. `vis_recommended` is
    # derived by the scoring node's project lookup, never collected, so it is
    # already a real bool; `preferencia_vis` (v2) is the lead's own stated
    # answer and takes priority when present — see `_vis_preference`.
    vis_flag = _vis_preference(lead) and _flag(lead, "tiene_vivienda_propia") is True
    red = 0
    if vis_flag:
        red -= 15
    if _flag(lead, "tiene_creditos_activos") is True:
        red -= 5
    # v2 removes `condicion_discapacidad_familiar`; only `numero_pac > 0`
    # remains as a trigger. The +8 value itself is kept unchanged — dependants
    # in the household are, on their own, still a valid positive signal for
    # this bucket, and the brief leaves the amount at the team's discretion.
    if (_int_field(lead, "numero_pac") or 0) > 0:
        red += 8
    # USER-LOCKED: subsidio_vivienda_anterior never subtracts from the score —
    # it is an absolute classification override applied below.

    raw = (
        credit_pts
        + cat_pts
        + (ingreso_pts or 0)
        + (ahorro_pts or 0)
        + (tiempo_pts or 0)
        + capacidad_pts
        + red
    )
    score = max(0, min(100, raw))

    # ── Classification ───────────────────────────────────────────────────────
    is_afiliado = bool(afiliado)
    ha_recibido_subsidio = _flag(lead, "subsidio_vivienda_anterior") is True
    classification = classify_lead(score, is_afiliado, ha_recibido_subsidio)

    # ── pos_subsidio (not a scored bucket — see module docstring) ───────────
    otra_caja_flag = _flag(lead, "otra_caja_compensacion")
    pos_subsidio = compute_pos_subsidio(is_afiliado, otra_caja_flag)

    # ── Reasoning ────────────────────────────────────────────────────────────
    ratio_text = f"{capacidad_ratio:.2f}" if capacidad_ratio is not None else "sin dato"
    lines = [
        f"Credito: {rating_label} ({score_credito}) → {credit_pts}/25",
        f"Afiliacion: {'categoria ' + cat if cat else 'no afiliado'} → {cat_pts}/15",
        f"Ingreso: {ingreso_slug or 'sin dato'} → {ingreso_pts or 0}/20",
        f"Ahorro: {_get(lead, 'ahorros_o_cesantias') or 'sin dato'} → {ahorro_pts or 0}/15",
        f"Tiempo de compra: {_get(lead, 'tiempo_compra_deseado') or 'sin dato'} → {tiempo_pts or 0}/10",
        f"Capacidad (ingreso-gastos/ingreso={ratio_text}) → {capacidad_pts}/15",
        f"Ajustes: {red:+d}",
        f"Umbral READY aplicado: {READY_THRESHOLD_AFILIADO if is_afiliado else READY_THRESHOLD_NO_AFILIADO} "
        f"({'afiliado' if is_afiliado else 'no afiliado'})",
    ]
    if ha_recibido_subsidio:
        lines.append(SUBSIDIO_PREVIO_REASON)
    if vis_flag:
        lines.append("Alerta: vivienda propia + proyecto VIS recomendado (−15)")
    if pos_subsidio == POS_SUBSIDIO_NO_DISPONIBLE:
        lines.append(POS_SUBSIDIO_ZERO_REASON)
    else:
        lines.append(f"Posibilidad de subsidio Colsubsidio: {pos_subsidio}")
    lines.extend(notes)
    extra = _get(lead, "normalization_notes")
    if extra:
        lines.extend(extra)

    return (score, rating_label, classification, "\n".join(lines))


def classify_lead(
    score: int,
    is_afiliado: bool,
    ha_recibido_subsidio: bool,
) -> str:
    """Map a clamped numeric score to the lead ``status`` domain.

    Returns one of ``{"calificado", "nutrible", "no_calificado"}`` (the
    persisted ``lead.status`` domain, per the ``lead-scoring`` spec). v2
    renames the terminal vocabulary from ``{ready, nurture, nurture_social}``
    to match the flow's three explicit terminal nodes (`Calificado` /
    `Nutrible` / `No calificado`); the thresholds and override rules below are
    unchanged from v1.

    Rules:

    * ``ha_recibido_subsidio=True`` is an **absolute override**: the lead never
      reaches ``calificado`` regardless of the score or affiliation. The
      override splits below/above :data:`NURTURE_FLOOR` into
      ``no_calificado`` / ``nutrible``. It does **not** touch the numeric
      score (compute first, override second).
    * Otherwise the affiliation-dependent READY threshold applies:
      ``afiliado ≥ READY_THRESHOLD_AFILIADO`` (60) or
      ``no-afiliado ≥ READY_THRESHOLD_NO_AFILIADO`` (75) → ``calificado``.
    * ``≥ NURTURE_FLOOR`` (30) below the ready threshold → ``nutrible``.
    * Below the nurture floor → ``no_calificado``.
    """
    if ha_recibido_subsidio:
        # Absolute override — never `calificado`. Score computed upstream
        # untouched.
        return "nutrible" if score >= NURTURE_FLOOR else "no_calificado"
    threshold = (
        READY_THRESHOLD_AFILIADO if is_afiliado else READY_THRESHOLD_NO_AFILIADO
    )
    if score >= threshold:
        return "calificado"
    if score >= NURTURE_FLOOR:
        return "nutrible"
    return "no_calificado"


def build_scoring_result(
    lead: Mapping[str, Any] | None,
    afiliado: Mapping[str, Any] | None = None,
) -> ScoringResult:
    """Return the structured :class:`ScoringResult` view for a lead.

    Convenience over :func:`score_lead`: runs the scorer, then derives a
    per-bucket ``breakdown`` so analytics callers can render the matrix
    alongside the verdict without re-evaluating each bucket.
    """
    score, rating_label, classification, reasoning = score_lead(lead, afiliado)

    cat = (afiliado or {}).get("categoria_afiliado") if afiliado else None
    capacidad_pts, _ = _capacidad_pts(
        _get(lead, "total_ingresos_mensuales"), _get(lead, "gastos_mensuales")
    )

    vis_flag = _vis_preference(lead) and _flag(lead, "tiene_vivienda_propia") is True
    red = 0
    if vis_flag:
        red -= 15
    if _flag(lead, "tiene_creditos_activos") is True:
        red -= 5
    if (_int_field(lead, "numero_pac") or 0) > 0:
        red += 8

    breakdown: dict[str, int] = {
        "credito": band_from_score_credito(
            _as_int(afiliado.get("score_credito"))
            if afiliado
            else simulate_bureau_cedula(_get(lead, "numero_documento", ""))
        )[0],
        "afiliacion": CATEGORIA_PTS.get(cat, 0),
        "ingreso": INGRESO_PTS.get(_get(lead, "rango_salarial")) or 0,
        "ahorro": AHORRO_PTS.get(_get(lead, "ahorros_o_cesantias")) or 0,
        "tiempo": TIEMPO_PTS.get(_get(lead, "tiempo_compra_deseado")) or 0,
        "capacidad": capacidad_pts,
        "ajustes": red,
    }
    return ScoringResult(
        score=score,
        status=classification,
        classification=classification,
        rating_label=rating_label,
        reasoning=reasoning,
        breakdown=breakdown,
    )
