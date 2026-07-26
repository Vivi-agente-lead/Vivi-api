"""Pure-Python lead scorer for Colsubsidio profiling.

Implements the scoring matrix in ``design.md`` §7.3 and the ``lead-scoring``
spec. Six additive buckets summing to exactly 100, then additive red-flag
adjustments, then a clamp to ``[0, 100]``. Classification is a deterministic
function of the clamped score, the affiliation flag, and the
``subsidio_vivienda_anterior`` absolute override.

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
``classification`` from the single domain ``{"ready", "nurture",
"nurture_social"}``.
"""

from __future__ import annotations

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
    "ESTABILIDAD_PTS",
    "ESTABILIDAD_INDEPENDIENTE",
    "CATEGORIA_PTS",
    "ScoringResult",
    "score_lead",
    "classify_lead",
    "build_scoring_result",
]

# ── READY / NURTURE thresholds (design §7.3 + §13.3) ─────────────────────────
# Afiliado reaches READY at 60; no-afiliado needs 75. Subsidio previo overrides
# both thresholds absolutely. NURTURE_FLOOR (30) splits nurture from
# nurture_social when the override fires or when READY is not reached.
READY_THRESHOLD_AFILIADO: int = 60
READY_THRESHOLD_NO_AFILIADO: int = 75
NURTURE_FLOOR: int = 30

# ── Bucket lookups (design §7.3) ────────────────────────────────────────────
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
ESTABILIDAD_PTS: dict[str, dict[str, int]] = {
    "termino_indefinido": {"mas_2a": 15, "1_2a": 11, "menos_1a": 7},
    "termino_fijo":       {"mas_2a": 12, "1_2a": 9,  "menos_1a": 5},
}
ESTABILIDAD_INDEPENDIENTE: int = 6  # contrato_laboral == "prestacion_servicios"
CATEGORIA_PTS: dict[str, int] = {"A": 15, "B": 11, "C": 7}

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
    status: str                # one of {"ready", "nurture", "nurture_social"}
    classification: str        # alias of status (single source of truth)
    rating_label: str          # credit-band label of score_credito
    reasoning: str             # multi-line audit text
    breakdown: dict[str, int]  # per-bucket points (plus the "ajustes" red flags)


def _get(profile: Mapping[str, Any] | None, key: str, default: Any = None) -> Any:
    """Dict-style ``.get`` tolerant of ``None`` profiles."""
    if profile is None:
        return default
    return profile.get(key, default)


def _flag(profile: Mapping[str, Any] | None, key: str) -> bool | None:
    """Read a boolean lead field through the domain normalizer.

    The workbook stores its yes/no columns as the literals ``SI`` / ``NO``, and
    an LLM may echo either those or a real ``bool``. Routing every boolean read
    through :func:`normalize_bool` keeps the scorer's ``is True`` tests keyed
    off one vocabulary. An unrecognized value yields ``None`` (fail closed) —
    it is treated as absent, never as a silent ``False``.
    """
    return normalize_bool(_get(profile, key))


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
        score_credito = afiliado.get("score_credito")
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
    ingreso_pts = INGRESO_PTS.get(_get(lead, "rango_salarial"))

    # ── Bucket 4: Ahorro (max 15) — exact slug lookup, never substring ───────
    # Audit DATA-003: the previous revision tested `"no" not in ahorro`, which
    # scored `"menos_3m"` as 0 because `"menos"` contains `"no"`. Exact lookup
    # makes `"menos_3m"` score 5.
    ahorro_pts = AHORRO_PTS.get(_get(lead, "ahorros_o_cesantias"))

    # ── Bucket 5: Tiempo de compra (max 10) ──────────────────────────────────
    tiempo_pts = TIEMPO_PTS.get(_get(lead, "tiempo_compra_deseado"))

    # ── Bucket 6: Estabilidad (max 15) ───────────────────────────────────────
    contrato = _get(lead, "contrato_laboral")
    if contrato == "prestacion_servicios":
        est_pts = ESTABILIDAD_INDEPENDIENTE
    else:
        est_pts = ESTABILIDAD_PTS.get(contrato, {}).get(
            _get(lead, "antiguedad_laboral"), 0
        )

    # ── Red flags (additive, applied to the sum, then clamped) ───────────────
    # Every lead-supplied boolean is read through the normalizer (`_flag`), so
    # the workbook's `SI`/`NO` literals drive these rules. `vis_recommended` is
    # derived by the scoring node's project lookup, never collected, so it is
    # already a real bool.
    vis_flag = (
        _get(lead, "vis_recommended") is True
        and _flag(lead, "tiene_vivienda_propia") is True
    )
    red = 0
    if vis_flag:
        red -= 15
    if _flag(lead, "tiene_creditos_activos") is True:
        red -= 5
    if (
        _flag(lead, "condicion_discapacidad_familiar") is True
        or (_get(lead, "numero_pac") or 0) > 0
    ):
        red += 8
    # USER-LOCKED: subsidio_vivienda_anterior never subtracts from the score —
    # it is an absolute classification override applied below.

    raw = (
        credit_pts
        + cat_pts
        + (ingreso_pts or 0)
        + (ahorro_pts or 0)
        + (tiempo_pts or 0)
        + (est_pts or 0)
        + red
    )
    score = max(0, min(100, raw))

    # ── Classification ───────────────────────────────────────────────────────
    is_afiliado = bool(afiliado)
    ha_recibido_subsidio = _flag(lead, "subsidio_vivienda_anterior") is True
    classification = classify_lead(score, is_afiliado, ha_recibido_subsidio)

    # ── Reasoning ────────────────────────────────────────────────────────────
    lines = [
        f"Credito: {rating_label} ({score_credito}) → {credit_pts}/25",
        f"Afiliacion: {'categoria ' + cat if cat else 'no afiliado'} → {cat_pts}/15",
        f"Ingreso: {_get(lead, 'rango_salarial') or 'sin dato'} → {ingreso_pts or 0}/20",
        f"Ahorro: {_get(lead, 'ahorros_o_cesantias') or 'sin dato'} → {ahorro_pts or 0}/15",
        f"Tiempo de compra: {_get(lead, 'tiempo_compra_deseado') or 'sin dato'} → {tiempo_pts or 0}/10",
        f"Estabilidad: {contrato or 'sin dato'} / {_get(lead, 'antiguedad_laboral') or '—'} → {est_pts or 0}/15",
        f"Ajustes: {red:+d}",
        f"Umbral READY aplicado: {READY_THRESHOLD_AFILIADO if is_afiliado else READY_THRESHOLD_NO_AFILIADO} "
        f"({'afiliado' if is_afiliado else 'no afiliado'})",
    ]
    if ha_recibido_subsidio:
        lines.append(SUBSIDIO_PREVIO_REASON)
    if vis_flag:
        lines.append("Alerta: vivienda propia + proyecto VIS recomendado (−15)")
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

    Returns one of ``{"ready", "nurture", "nurture_social"}`` (the persisted
    ``lead.status`` domain, per the ``lead-scoring`` spec).

    Rules:

    * ``ha_recibido_subsidio=True`` is an **absolute override**: the lead never
      reaches ``ready`` regardless of the score or affiliation. The override
      splits below/above :data:`NURTURE_FLOOR` into ``nurture_social`` /
      ``nurture``. It does **not** touch the numeric score (compute first,
      override second).
    * Otherwise the affiliation-dependent READY threshold applies:
      ``afiliado ≥ READY_THRESHOLD_AFILIADO`` (60) or
      ``no-afiliado ≥ READY_THRESHOLD_NO_AFILIADO`` (75) → ``ready``.
    * ``≥ NURTURE_FLOOR`` (30) below the ready threshold → ``nurture``.
    * Below the nurture floor → ``nurture_social``.
    """
    if ha_recibido_subsidio:
        # Absolute override — never `ready`. Score computed upstream untouched.
        return "nurture" if score >= NURTURE_FLOOR else "nurture_social"
    threshold = (
        READY_THRESHOLD_AFILIADO if is_afiliado else READY_THRESHOLD_NO_AFILIADO
    )
    if score >= threshold:
        return "ready"
    if score >= NURTURE_FLOOR:
        return "nurture"
    return "nurture_social"


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
    contrato = _get(lead, "contrato_laboral")
    if contrato == "prestacion_servicios":
        est_pts = ESTABILIDAD_INDEPENDIENTE
    else:
        est_pts = ESTABILIDAD_PTS.get(contrato, {}).get(
            _get(lead, "antiguedad_laboral"), 0
        )

    vis_flag = (
        _get(lead, "vis_recommended") is True
        and _flag(lead, "tiene_vivienda_propia") is True
    )
    red = 0
    if vis_flag:
        red -= 15
    if _flag(lead, "tiene_creditos_activos") is True:
        red -= 5
    if (
        _flag(lead, "condicion_discapacidad_familiar") is True
        or (_get(lead, "numero_pac") or 0) > 0
    ):
        red += 8

    breakdown: dict[str, int] = {
        "credito": band_from_score_credito(
            afiliado.get("score_credito")
            if afiliado
            else simulate_bureau_cedula(_get(lead, "numero_documento", ""))
        )[0],
        "afiliacion": CATEGORIA_PTS.get(cat, 0),
        "ingreso": INGRESO_PTS.get(_get(lead, "rango_salarial")) or 0,
        "ahorro": AHORRO_PTS.get(_get(lead, "ahorros_o_cesantias")) or 0,
        "tiempo": TIEMPO_PTS.get(_get(lead, "tiempo_compra_deseado")) or 0,
        "estabilidad": est_pts or 0,
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