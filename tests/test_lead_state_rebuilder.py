"""Crash recovery: rebuilding `lead_profile` from the `leads` row.

With `LLM_CHECKPOINTER=memory` a process restart drops every thread. The DB row
survives, so the conversation must resume from it instead of restarting at
`autorizacion_datos` and re-asking a lead everything they already answered.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.graph.builder import build_lead_profiler
from app.services import lead_state_rebuilder
from app.services.lead_state_rebuilder import rebuild_lead_profile
from tests.conftest import (
    FakeAfiliadoRepository,
    FakeLeadRepository,
    FakeSession,
    World,
    make_afiliado,
    tool_config,
)
from tests.test_graph_traversal import Conversation


@pytest.fixture
def rebuilder_world(graph_world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    """Point the rebuilder at the same in-memory world as the tools."""
    monkeypatch.setattr(lead_state_rebuilder, "LeadRepository", FakeLeadRepository)
    monkeypatch.setattr(
        lead_state_rebuilder, "AfiliadoColsubsidioRepository", FakeAfiliadoRepository
    )
    return graph_world


async def test_rebuild_returns_empty_for_a_conversation_with_no_lead_row(
    rebuilder_world: World,
) -> None:
    assert await rebuild_lead_profile(FakeSession(), uuid.uuid4()) == {}


async def test_rebuild_restores_the_answers_and_re_derives_the_predicates(
    rebuilder_world: World,
) -> None:
    """The two derived predicates are recomputed, never read from the row."""
    conversation_id = uuid.uuid4()
    repo = FakeLeadRepository(FakeSession())
    await repo.upsert_by_conversation_id(
        conversation_id,
        {
            "tipo_documento": "CC",
            "numero_documento": "99887766",
            "afiliado_colsubsidio": False,
            "estado_civil": "union_libre",
            "contrato_laboral": "prestacion_servicios",
            "numero_pac": 0,
            "total_ingresos_mensuales": Decimal("6000000"),
        },
    )

    profile = await rebuild_lead_profile(FakeSession(), conversation_id)

    assert profile["numero_documento"] == "99887766"
    assert profile["autorizacion_datos"] is True
    assert profile["tiene_pareja"] is True
    assert profile["es_empleado"] is False
    # `rango_salarial` was never stored — re-derived from the household income.
    assert profile["rango_salarial"] == "4_8m"


async def test_rebuild_recomputes_edad_from_the_affiliate_record(
    rebuilder_world: World,
) -> None:
    """A stored `edad` is a snapshot; a birthday may have passed since."""
    rebuilder_world.afiliados.append(
        make_afiliado(numero_documento="1010101010", edad=40)
    )
    conversation_id = uuid.uuid4()
    repo = FakeLeadRepository(FakeSession())
    await repo.upsert_by_conversation_id(
        conversation_id,
        {
            "tipo_documento": "CC",
            "numero_documento": "1010101010",
            "afiliado_colsubsidio": True,
            "edad": 12,  # stale
        },
    )

    profile = await rebuild_lead_profile(FakeSession(), conversation_id)

    assert profile["edad"] == 40
    assert profile["afiliado_record"]["categoria_afiliado"] == "A"


async def test_a_rebuilt_profile_resumes_the_graph_without_re_asking(
    rebuilder_world: World,
) -> None:
    """The end-to-end recovery: new process, new checkpointer, same lead row."""
    rebuilder_world.afiliados.append(
        make_afiliado(
            numero_documento="1010101010",
            edad=34,
            salario_base_cotizacion=Decimal("7500000"),
        )
    )

    first = Conversation()
    for reply in ("Hola", "Sí", "Cédula de ciudadanía", "1010101010", "Casado"):
        await first.say(reply)
    assert first.awaiting == "contrato_laboral"

    # The process restarts: a brand-new compiled graph with an empty saver.
    restored = await rebuild_lead_profile(FakeSession(), first.conversation_id)
    resumed = Conversation(conversation_id=first.conversation_id)
    reply = await resumed.say("Termino indefinido", lead_profile=restored)

    assert resumed.profile["estado_civil"] == "casado"
    assert resumed.profile["numero_documento"] == "1010101010"
    assert resumed.profile["afiliado_colsubsidio"] is True
    # It resumes at the question that was open, not at the top of the flow.
    assert resumed.nodes == ["recoger_empleo"]
    assert resumed.awaiting == "contrato_laboral"
    assert "contrato de trabajo" in reply
    # The in-flight answer is lost with the checkpointer — that one question is
    # asked again — but nothing already stored in the `leads` row is.
    for answered in ("autorizas", "documento", "estado civil"):
        assert answered not in reply.lower()

    await resumed.say("Termino indefinido")
    assert resumed.profile["contrato_laboral"] == "termino_indefinido"
    assert resumed.nodes[-1] == "recoger_capacidad"
    assert resumed.awaiting == "total_ingresos_mensuales"
