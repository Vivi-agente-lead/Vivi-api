"""Shared machinery for the collection nodes.

Every LLM node in `design.md` §4 does the same three things, so they are written
once here:

1. **Parse** the answer to the field asked for last turn, deterministically —
   `_validators` and `domain_normalizer` own the domains, not the model. The
   design's rule that collection nodes "delegate only question phrasing" is
   enforced structurally: the model never sees a field name and never writes one.
2. **Pick** the next missing field this node owns, honouring its gating
   predicate (`rango_salarial` only for a no-afiliado empleado, and so on).
3. **Ask** it — the model rewrites the question warmly, and the rewrite is
   discarded unless it still carries every source option verbatim, so an
   enumerated answer stays normalizable.

When no LLM is configured the deterministic question from
`app/prompts/slices.py` is sent as-is. That is what makes the whole graph
traversable in tests without a network call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.graph.nodes._validators import fold, note_rejected
from app.prompts.slices import FIELD_OPTIONS, FIELD_QUESTIONS
from app.prompts.system import render_system_prompt, wrap_user_input
from app.services.llm_factory import build_llm, is_llm_configured
from app.tools.lead_tools import save_lead

logger = logging.getLogger(__name__)

__all__ = [
    "Field",
    "profile_of",
    "reply_of",
    "collect",
    "say",
    "persist",
    "phrase",
    "SAVE_LEAD_FIELDS",
]

# The named parameters of `save_lead`. A profile key outside this set is graph
# bookkeeping (`afiliado_record`, `tiene_pareja`, `es_empleado`, …) and is never
# mirrored to the `leads` row.
SAVE_LEAD_FIELDS: frozenset[str] = frozenset(
    {
        "tipo_documento",
        "numero_documento",
        "afiliado_colsubsidio",
        "nombre_apellido",
        "categoria",
        "otra_caja_compensacion",
        "estado_civil",
        "edad",
        "contrato_laboral",
        "rango_salarial",
        "total_ingresos_mensuales",
        "total_ingresos_familiares_mensuales",
        "antiguedad_laboral",
        "tiene_vivienda_propia",
        "ahorros_o_cesantias",
        "condicion_discapacidad_familiar",
        "numero_pac",
        "tiene_creditos_activos",
        "subsidio_vivienda_anterior",
        "cabeza_de_hogar",
        "lugar_eleccion_vivir",
        "municipio_normalizado",
        "tiempo_compra_deseado",
        "descripcion_vivienda_sueno",
        "vis_recommended",
        "score_credito",
    }
)


def _always(profile: dict[str, Any]) -> bool:
    """Default gate: every lead is asked this field."""
    return True


@dataclass(frozen=True)
class Field:
    """One field a collection node owns.

    Attributes:
        name: the `lead_profile` key.
        parse: raw answer → stored value, or `None` when the answer is outside
            the domain (the node then re-asks and records the raw value).
        question_key: the `FIELD_QUESTIONS` entry, when it differs from `name`
            (`subsidio_vivienda_anterior` has a partner-aware phrasing).
        applies: gate deciding whether this lead is asked at all.
        options_key: the `FIELD_OPTIONS` entry whose labels the model's rewrite
            must preserve verbatim.
    """

    name: str
    parse: Callable[[str | None], Any]
    question_key: str | None = None
    applies: Callable[[dict[str, Any]], bool] = _always
    options_key: str | None = None

    def question_for(self, profile: dict[str, Any]) -> str:
        return FIELD_QUESTIONS[self.question_key or self.name]

    def options(self) -> tuple[str, ...]:
        return FIELD_OPTIONS.get(self.options_key or self.name, ())


def profile_of(state: Any) -> dict[str, Any]:
    """A mutable copy of the lead working copy."""
    return dict(state.get("lead_profile") or {})


def reply_of(state: Any) -> str:
    """This turn's raw user answer, or `""` when it was already consumed."""
    return (state.get("pending_user_reply") or "").strip()


async def collect(
    state: Any,
    config: RunnableConfig,
    *,
    node: str,
    fields: Sequence[Field],
    finalize: Callable[[dict[str, Any]], None] | None = None,
    persist_fields: Iterable[str] | None = None,
    intro: str | None = None,
) -> dict[str, Any]:
    """Run one turn of a collection node and return the state delta.

    Returns a delta whose `awaiting_field` is non-empty when a question was just
    asked — `turn_gated` reads it and ends the turn.
    """
    profile = profile_of(state)
    notes: list[str] = []
    awaiting = state.get("awaiting_field") or ""
    reply = reply_of(state)
    owned = {item.name for item in fields}
    consumed = False

    if awaiting in owned and reply:
        consumed = True
        target = next(item for item in fields if item.name == awaiting)
        value = target.parse(reply)
        if value is None:
            notes.append(note_rejected(target.name, reply))
            logger.info(
                "graph.answer_rejected", extra={"node": node, "field": target.name}
            )
        else:
            profile[target.name] = value

    if notes:
        profile["normalization_notes"] = (
            list(profile.get("normalization_notes") or []) + notes
        )
    if finalize is not None:
        finalize(profile)

    pending = _next_missing(profile, fields)
    delta: dict[str, Any] = {"current_node": node, "lead_profile": profile}
    if consumed:
        delta["pending_user_reply"] = ""

    if pending is not None:
        if consumed and persist_fields is not None:
            # Mirror after every accepted answer, not only when the bundle
            # completes. A capacity bundle holds 11 fields; persisting only at
            # the end meant a lead who dropped out mid-bundle left a `leads`
            # row with those columns NULL, losing the auditable artifact this
            # change exists to produce. `save_lead` upserts and merges, so
            # writing the partial profile repeatedly is safe and idempotent.
            await persist(profile, config, persist_fields)
        question = pending.question_for(profile)
        if intro and not any(profile.get(item.name) is not None for item in fields):
            # The source flow's reassurance message before the capacity block.
            # It rides on the bundle's first question rather than on a node of
            # its own, so it costs no extra turn.
            question = f"{intro}\n\n{question}"
        text = await phrase(
            state,
            node=node,
            profile=profile,
            question=question,
            options=pending.options(),
        )
        delta["awaiting_field"] = pending.name
        delta["asked_this_turn"] = True
        delta["messages"] = [AIMessage(content=text, additional_kwargs=_interactive_kwargs(pending, text))]
        return delta

    if awaiting in owned:
        # Only the node that owns the awaited field may clear it. A pass-through
        # upstream node writing `""` here would strip the marker before the node
        # that actually asked the question got to parse the answer.
        delta["awaiting_field"] = ""
    if persist_fields is not None:
        await persist(profile, config, persist_fields)
    return delta


def _next_missing(profile: dict[str, Any], fields: Sequence[Field]) -> Field | None:
    """The first field this lead still owes an answer for."""
    for item in fields:
        if not item.applies(profile):
            continue
        if profile.get(item.name) is None:
            return item
    return None


async def say(
    state: Any,
    *,
    node: str,
    text: str,
    profile: dict[str, Any] | None = None,
) -> AIMessage:
    """A closing/farewell message, rephrased by the model when one is available."""
    rendered = await phrase(
        state, node=node, profile=profile or profile_of(state), question=text, options=()
    )
    return AIMessage(content=rendered)


async def phrase(
    state: Any,
    *,
    node: str,
    profile: dict[str, Any],
    question: str,
    options: Sequence[str] = (),
) -> str:
    """Let the model write the human part; the code owns the option list.

    The question is split into a stem and its option lines. Only the stem goes
    to the model, and the options are appended verbatim afterwards. That is what
    makes a natural tone possible: the previous revision asked the model to
    rewrite the whole message and then **rejected any rewrite that did not
    reproduce every option label verbatim**, so the only rewrites that survived
    were the ones that kept the bullet list intact. The result read like a form.

    Splitting the two removes the conflict. The model is free on the sentence
    that carries the tone, and the person still sees an exact, complete menu —
    which the normalizer needs and `_tolerance` widens rather than replaces.

    Falls back to the deterministic text when the model is unavailable, errors,
    or returns nothing.
    """
    if not is_llm_configured():
        return question

    stem, option_block = _split_question(question)
    system = render_system_prompt(node, lead_profile=profile)
    instruction = (
        "Escribe el siguiente turno de la conversación en español colombiano "
        "neutro y cercano, tuteando.\n"
        "- Si la persona acaba de darte un dato, reconócelo en pocas palabras "
        "antes de seguir (por ejemplo: «Listo, quedaste como casado.»).\n"
        "- Formula UNA sola pregunta, la que va abajo. Puedes cambiar las "
        "palabras; no cambies lo que se pregunta.\n"
        "- No enumeres las opciones: se agregan automáticamente después de tu "
        "mensaje.\n"
        "- Máximo dos frases. Sin emojis, sin saludos repetidos.\n\n"
        f"--- PREGUNTA ---\n{stem}\n--- FIN PREGUNTA ---"
    )
    history = _recent_messages(state)
    try:
        result = await build_llm().ainvoke(
            [SystemMessage(content=system), *history, HumanMessage(content=instruction)]
        )
    except Exception as exc:  # noqa: BLE001 — any model failure falls back
        logger.warning("graph.phrase_failed", extra={"node": node, "error": str(exc)})
        return question

    text = (getattr(result, "content", "") or "").strip()
    if not text:
        return question
    if option_block:
        text = f"{text}\n{option_block}"
    return text


def _split_question(question: str) -> tuple[str, str]:
    """Separate a question's stem from its `- option` lines.

    The option block is reattached verbatim after the model has spoken, so the
    person always sees the exact source labels even when the phrasing around
    them changes turn to turn.
    """
    stem: list[str] = []
    block: list[str] = []
    for line in question.splitlines():
        (block if line.lstrip().startswith("-") else stem).append(line)
    return "\n".join(stem).strip(), "\n".join(block).strip()


def _interactive_kwargs(pending: Field, phrased_text: str) -> dict[str, Any]:
    """Channel-agnostic option metadata for the outbound question, or `{}`.

    This is the seam `design.md`'s Channel-Agnostic Boundary requires: the
    graph knows a pending field's option list (`Field.options()` already
    carries it) but must never know a WhatsApp button or list exists. It
    hands the raw data — field name, option labels, question stem without the
    bullet block — to whichever adapter reads `AIMessage.additional_kwargs`
    downstream (`AgentService._persist_turn`, then `InboundMessageHandler`),
    which alone decides how (or whether) to render it tactilely.
    """
    options = pending.options()
    if not options:
        return {}
    stem, _ = _split_question(phrased_text)
    return {
        "pending_field": pending.name,
        "pending_options": list(options),
        "pending_stem": stem,
    }


def _recent_messages(state: Any, limit: int = 6) -> list[Any]:
    """The tail of the conversation, for tone continuity only."""
    messages = state.get("messages") or []
    return list(messages)[-limit:]


async def persist(
    profile: dict[str, Any],
    config: RunnableConfig,
    fields: Iterable[str],
) -> None:
    """Mirror the named profile fields onto the `leads` row via `save_lead`.

    `save_lead` is `@safe_tool`-wrapped, so a persistence failure is logged and
    returned as JSON rather than raised: losing the DB mirror must not drop the
    conversation, whose working copy lives in the checkpointer.
    """
    payload = {
        name: profile[name]
        for name in fields
        if name in SAVE_LEAD_FIELDS and profile.get(name) is not None
    }
    if not payload:
        return
    result = await save_lead.ainvoke(payload, config=config)
    logger.debug("graph.save_lead", extra={"fields": sorted(payload)})
    return result


def wrapped_reply(reply: str) -> str:
    """Anti-injection wrapper, re-exported for the nodes that build prompts."""
    return wrap_user_input(reply)
