"""Closing nodes: `recoger_intencion`, `scoring`, `handoff` (`design.md` §4).

`scoring` is the only node with no LLM at all and no discretion: it looks the
catalogue up to decide `vis_recommended`, then delegates the verdict to
`classify_lead`, which runs the pure `lead_scorer`. That is what makes the score
reproducible across two process invocations, which is half of what the juror
rubric measures.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.graph.nodes._common import Field, collect, profile_of, say
from app.graph.nodes._validators import (
    parse_free_text,
    validate_enumerated,
    validate_municipio,
)
from app.tools.lead_tools import classify_lead, get_projects, save_lead

logger = logging.getLogger(__name__)

__all__ = ["recoger_intencion", "scoring", "handoff"]

_INTENCION_FIELDS = (
    Field(
        name="lugar_eleccion_vivir",
        parse=lambda raw: raw if validate_municipio(raw) else None,
        options_key="lugar_eleccion_vivir",
    ),
    Field(name="descripcion_vivienda_sueno", parse=parse_free_text),
    Field(
        name="tiempo_compra_deseado",
        parse=lambda raw: validate_enumerated("tiempo_compra_deseado", raw),
        options_key="tiempo_compra_deseado",
    ),
)

_INTENCION_PERSIST = (
    "lugar_eleccion_vivir",
    "municipio_normalizado",
    "descripcion_vivienda_sueno",
    "tiempo_compra_deseado",
)

# v2 renames the terminal status vocabulary (docs/v2-impact-analysis.md §7):
# ready → calificado, nurture → nutrible, nurture_social → no_calificado.
_HANDOFF_SLICES = {
    "calificado": "handoff_calificado",
    "nutrible": "handoff_nutrible",
    "no_calificado": "handoff_no_calificado",
}

_HANDOFF_FALLBACK = {
    "calificado": (
        "Me ha encantado tu entusiasmo en la búsqueda de tu hogar ideal. Un "
        "asesor de vivienda de Colsubsidio te va a contactar para acompañarte "
        "en el siguiente paso."
    ),
    "nutrible": (
        "Gracias por tus respuestas. Voy a guardar tu información y te vamos a "
        "contactar más adelante con opciones que se ajusten a tu situación."
    ),
    "no_calificado": (
        "Gracias por tu tiempo y por la confianza. Un asistente social de "
        "Colsubsidio puede orientarte sobre los programas de apoyo a los que "
        "puedes acceder hoy; con gusto te ponemos en contacto."
    ),
}


def _derive_municipio(profile: dict[str, Any]) -> None:
    """Persist both the verbatim option and the catalogue join key.

    `lugar_eleccion_vivir` keeps what the lead actually chose, for the audit
    trail; `municipio_normalizado` is the only value `get_projects` and the
    `vis_recommended` lookup may be queried with — the two vocabularies differ
    for four of the nine options, including all three Bogotá variants.
    """
    raw = profile.get("lugar_eleccion_vivir")
    if raw is not None:
        profile["municipio_normalizado"] = validate_municipio(raw)


async def recoger_intencion(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Where, when, and what kind of home the lead wants."""
    return await collect(
        state,
        config,
        node="recoger_intencion",
        fields=_INTENCION_FIELDS,
        finalize=_derive_municipio,
        persist_fields=_INTENCION_PERSIST,
    )


async def scoring(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Pure verdict: `vis_recommended`, then `classify_lead`.

    Idempotent — a lead whose row already carries a terminal status keeps it,
    because the guard lives in `LeadRepository.upsert_by_conversation_id` and
    `classify_lead` returns the stored verdict instead of raising.
    """
    profile = profile_of(state)

    municipio = profile.get("municipio_normalizado")
    if municipio is not None and profile.get("vis_recommended") is None:
        raw = await get_projects.ainvoke(
            {"municipio": municipio, "tipo": "VIS"}, config=config
        )
        payload = _json_or_none(raw) or {}
        profile["vis_recommended"] = bool(payload.get("total"))
        await save_lead.ainvoke(
            {"vis_recommended": profile["vis_recommended"]}, config=config
        )

    verdict = _json_or_none(await classify_lead.ainvoke({}, config=config)) or {}
    if verdict.get("error"):
        logger.warning("graph.scoring_failed", extra={"payload": str(verdict)[:200]})
    else:
        profile["status"] = verdict.get("status")
        profile["score"] = verdict.get("score")
        profile["score_rating"] = verdict.get("score_rating")
        profile["classification_reasoning"] = verdict.get("reasoning")
        logger.info(
            "graph.scored",
            extra={"status": profile.get("status"), "score": profile.get("score")},
        )

    return {"current_node": "scoring", "lead_profile": profile}


async def handoff(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Close the conversation with the next step this lead has earned.

    `get_projects` runs **only** for a `calificado` lead: showing a catalogue
    to a lead who does not qualify is precisely the commercial noise the
    change exists to remove. Only `Calificado` continues in the v2 diagram —
    `Nutrible` and `No calificado` are terminal with no follow-up drawn.
    """
    profile = profile_of(state)
    status = profile.get("status") or "nutrible"
    text = _HANDOFF_FALLBACK.get(status, _HANDOFF_FALLBACK["nutrible"])

    if status == "calificado":
        proyectos = await _ready_projects(profile, config)
        if proyectos:
            listing = "\n".join(f"- {name}" for name in proyectos)
            text = f"{text}\n\nAlgunos proyectos en tu zona:\n{listing}"

    message = await say(
        state,
        node=_HANDOFF_SLICES.get(status, "handoff_nutrible"),
        profile=profile,
        text=text,
    )
    logger.info("graph.handoff", extra={"status": status})
    return {
        "current_node": "handoff",
        "lead_profile": profile,
        "messages": [message],
    }


async def _ready_projects(
    profile: dict[str, Any], config: RunnableConfig
) -> list[str]:
    """Catalogue names for a READY lead's municipio, or an empty list."""
    municipio = profile.get("municipio_normalizado")
    if municipio is None:
        return []
    payload = _json_or_none(
        await get_projects.ainvoke({"municipio": municipio}, config=config)
    )
    if not payload or payload.get("error"):
        return []
    names: list[str] = []
    for row in payload.get("proyectos") or []:
        name = row.get("proyecto")
        if name and name not in names:
            names.append(name)
    return names


def _json_or_none(raw: str) -> dict[str, Any] | None:
    """Parse a tool response; `None` when it is not a JSON object."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("graph.tool_response_unparseable")
        return None
    return payload if isinstance(payload, dict) else None
