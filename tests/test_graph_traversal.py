"""End-to-end traversals of the compiled lead-profiling StateGraph.

One graph invocation is one conversational turn (`app/graph/turn_gate.py`), so a
conversation is driven here by invoking the compiled graph once per user reply
against a shared `MemorySaver` thread — exactly what `AgentService` does per
inbound WhatsApp message.

No LLM and no Postgres: `phrase` falls back to the deterministic question bank
when `OPENAI_API_KEY` is empty, and `conftest.py` swaps the repositories for
in-memory doubles.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.graph.builder import build_lead_profiler
from tests.conftest import World, make_afiliado, tool_config


class Conversation:
    """Drives one thread of the compiled graph, one user reply per turn."""

    def __init__(self, conversation_id: uuid.UUID | None = None) -> None:
        self.conversation_id = conversation_id or uuid.uuid4()
        self.graph = build_lead_profiler().compile(checkpointer=MemorySaver())
        self.config = tool_config(self.conversation_id)
        self.nodes: list[str] = []
        self.replies: list[str] = []
        self.state: dict[str, Any] = {}

    async def say(self, text: str) -> str:
        """Send one user message; return the assistant's reply for that turn."""
        before = len(self.state.get("messages") or [])
        self.state = await self.graph.ainvoke(
            {"pending_user_reply": text, "messages": []}, config=self.config
        )
        self.nodes.append(self.state.get("current_node", ""))
        new = list(self.state.get("messages") or [])[before:]
        reply = "\n".join(str(getattr(m, "content", "")) for m in new)
        self.replies.append(reply)
        return reply

    @property
    def profile(self) -> dict[str, Any]:
        return self.state.get("lead_profile") or {}

    @property
    def awaiting(self) -> str:
        return self.state.get("awaiting_field") or ""


# ── Spine (task 4.4) ────────────────────────────────────────────────────────
async def test_spine_asks_for_consent_then_document_then_looks_the_lead_up(
    graph_world: World,
) -> None:
    """`start → autorizacion_datos → pedir_cedula → afiliado_check → handoff`.

    Each turn ends where the graph is waiting for an answer, and the next turn
    resumes there from the checkpointer without re-asking anything.
    """
    graph_world.afiliados.append(make_afiliado(numero_documento="1010101010", edad=34))
    chat = Conversation()

    assert "autorizas" in (await chat.say("Hola")).lower()
    assert chat.awaiting == "autorizacion_datos"

    assert "documento" in (await chat.say("Sí")).lower()
    assert chat.awaiting == "tipo_documento"
    assert chat.profile["autorizacion_datos"] is True

    await chat.say("Cédula de ciudadanía")
    assert chat.awaiting == "numero_documento"
    assert chat.profile["tipo_documento"] == "CC"

    await chat.say("1010101010")

    assert chat.profile["numero_documento"] == "1010101010"
    assert chat.profile["afiliado_colsubsidio"] is True
    assert chat.profile["categoria"] == "A"
    assert chat.profile["edad"] == 34
    assert chat.nodes == [
        "autorizacion_datos",
        "pedir_cedula",
        "pedir_cedula",
        "handoff",
    ]


async def test_spine_creates_the_lead_row_at_status_profiling(
    graph_world: World,
) -> None:
    """`afiliado_check` is the first persistence point (`design.md` §2)."""
    graph_world.afiliados.append(make_afiliado(numero_documento="1010101010"))
    chat = Conversation()
    for reply in ("Hola", "Sí", "CC", "1010101010"):
        await chat.say(reply)

    lead = graph_world.lead(chat.conversation_id)
    assert lead is not None
    assert lead.status == "profiling"
    assert lead.numero_documento == "1010101010"
    assert lead.afiliado_colsubsidio is True


async def test_spine_marks_an_unknown_document_as_no_afiliado(
    graph_world: World,
) -> None:
    """A cedula absent from `afiliados_colsubsidio` takes the no-afiliado branch."""
    chat = Conversation()
    for reply in ("Hola", "Sí", "CC", "99887766"):
        await chat.say(reply)

    assert chat.profile["afiliado_colsubsidio"] is False
    assert chat.profile.get("categoria") is None
    assert graph_world.lead(chat.conversation_id).afiliado_colsubsidio is False


async def test_consent_refusal_ends_the_conversation_without_a_lead_row(
    graph_world: World,
) -> None:
    """`_route_autorizacion` sends a refusal to `END`; nothing is persisted."""
    chat = Conversation()
    await chat.say("Hola")
    farewell = await chat.say("No")

    assert chat.profile["autorizacion_datos"] is False
    assert "respeto tu decisión" in farewell
    assert graph_world.lead(chat.conversation_id) is None
    assert graph_world.upsert_calls == []


async def test_an_answer_outside_the_domain_is_re_asked_and_recorded(
    graph_world: World,
) -> None:
    """Never guess: an unmapped document type is re-asked and audited."""
    chat = Conversation()
    await chat.say("Hola")
    await chat.say("Sí")
    await chat.say("Tarjeta de identidad")

    assert chat.awaiting == "tipo_documento"
    assert chat.profile.get("tipo_documento") is None
    assert any(
        "tipo_documento" in note for note in chat.profile.get("normalization_notes", [])
    )


