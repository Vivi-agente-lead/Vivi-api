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
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.graph.builder import build_lead_profiler
from tests.conftest import World, make_afiliado, make_proyecto, tool_config

# Answers keyed by the field the graph is waiting for. `Conversation.run` replies
# with the matching entry until the graph stops asking, so a test states the
# lead's answers once and the traversal itself decides which ones are reached —
# a bundle that wrongly asked for `antiguedad_laboral` would show up as a
# KeyError naming the field, not as a silent pass.
ANSWERS_AFILIADO_READY = {
    "autorizacion_datos": "Sí",
    "tipo_documento": "Cédula de ciudadanía",
    "numero_documento": "1010101010",
    "estado_civil": "Casado",
    "contrato_laboral": "Termino indefinido",
    "total_ingresos_familiares_mensuales": "9.000.000",
    "antiguedad_laboral": "Mas de dos años",
    "tiene_vivienda_propia": "No",
    "ahorros_o_cesantias": "Más de $40 millones",
    "tiene_creditos_activos": "No",
    "numero_pac": "2",
    "condicion_discapacidad_familiar": "No",
    "subsidio_vivienda_anterior": "No",
    "lugar_eleccion_vivir": "Bogotá norte",
    "tiempo_compra_deseado": "3 meses",
    "descripcion_vivienda_sueno": "Un apartamento con dos habitaciones y balcón.",
}

ANSWERS_NO_AFILIADO = {
    "autorizacion_datos": "Sí",
    "tipo_documento": "Cédula de ciudadanía",
    "numero_documento": "1234567890",
    "nombre_apellido": "Camilo Restrepo",
    "fecha_nacimiento": "12/03/1990",
    "estado_civil": "Soltero",
    "otra_caja_compensacion": "Compensar",
    "contrato_laboral": "Termino indefinido",
    "total_ingresos_mensuales": "5.000.000",
    "antiguedad_laboral": "Mas de dos años",
    "rango_salarial": "4 a 8 millones",
    "tiene_vivienda_propia": "No",
    "ahorros_o_cesantias": "Entre $3 y $10 millones",
    "tiene_creditos_activos": "No",
    "numero_pac": "0",
    "condicion_discapacidad_familiar": "No",
    "subsidio_vivienda_anterior": "No",
    "lugar_eleccion_vivir": "Soacha",
    "tiempo_compra_deseado": "6 meses",
    "descripcion_vivienda_sueno": "Una casa pequeña con patio.",
}


class Conversation:
    """Drives one thread of the compiled graph, one user reply per turn."""

    def __init__(self, conversation_id: uuid.UUID | None = None) -> None:
        self.conversation_id = conversation_id or uuid.uuid4()
        self.graph = build_lead_profiler().compile(checkpointer=MemorySaver())
        self.config = tool_config(self.conversation_id)
        self.nodes: list[str] = []
        self.replies: list[str] = []
        self.state: dict[str, Any] = {}
        self._asked: list[str] = []

    async def say(self, text: str, lead_profile: dict[str, Any] | None = None) -> str:
        """Send one user message; return the assistant's reply for that turn.

        `lead_profile` seeds the working copy, which is what `AgentService` does
        after a checkpointer loss.
        """
        before = len(self.state.get("messages") or [])
        payload: dict[str, Any] = {"pending_user_reply": text, "messages": []}
        if lead_profile is not None:
            payload["lead_profile"] = lead_profile
        self.state = await self.graph.ainvoke(payload, config=self.config)
        self.nodes.append(self.state.get("current_node", ""))
        if self.awaiting:
            self._asked.append(self.awaiting)
        new = list(self.state.get("messages") or [])[before:]
        reply = "\n".join(str(getattr(m, "content", "")) for m in new)
        self.replies.append(reply)
        return reply

    async def run(self, answers: dict[str, str], max_turns: int = 60) -> str:
        """Answer whatever the graph asks until it stops asking."""
        reply = await self.say("Hola")
        for _ in range(max_turns):
            field = self.awaiting
            if not field:
                return reply
            if field not in answers:
                raise AssertionError(
                    f"the graph asked for {field!r}, which this lead should "
                    f"never be asked. Trail: {self.nodes}"
                )
            reply = await self.say(answers[field])
        raise AssertionError(f"conversation did not settle. Trail: {self.nodes}")

    @property
    def profile(self) -> dict[str, Any]:
        return self.state.get("lead_profile") or {}

    @property
    def awaiting(self) -> str:
        return self.state.get("awaiting_field") or ""

    @property
    def asked_fields(self) -> list[str]:
        return self._asked

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<Conversation nodes={self.nodes} profile={self.profile}>"


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
        "recoger_estado_civil",
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



# ── Full traversals (task 4.11) ─────────────────────────────────────────────
async def test_afiliado_happy_path_reaches_ready_and_sees_projects(
    graph_world: World,
) -> None:
    """Spec: *Happy path afiliado reaches READY*.

    `status='ready'`, `score >= 60`, `get_projects` invoked, and the closing
    message routes to a human asesor.
    """
    graph_world.afiliados.append(
        make_afiliado(
            numero_documento="1010101010",
            categoria_afiliado="A",
            score_credito=880,
            edad=34,
            salario_base_cotizacion=Decimal("7500000"),
        )
    )
    graph_world.proyectos.append(make_proyecto("VIBO ONCE", "B1", "Bogota", "VIS"))

    chat = Conversation()
    closing = await chat.run(ANSWERS_AFILIADO_READY)

    assert chat.profile["status"] == "ready"
    assert chat.profile["score"] >= 60
    assert "asesor" in closing.lower()
    assert "VIBO ONCE" in closing

    lead = graph_world.lead(chat.conversation_id)
    assert lead.status == "ready"
    assert lead.score == chat.profile["score"]
    assert lead.municipio_normalizado == "Bogota"
    assert lead.lugar_eleccion_vivir == "Bogotá norte"
    assert lead.cabeza_de_hogar is True
    assert graph_world.project_queries, "get_projects was never called"


async def test_afiliado_is_never_asked_identidad_otra_caja_or_rango_salarial(
    graph_world: World,
) -> None:
    """Spec: *Afiliado branch skips identidad, otra_caja, edad* and
    *Rango salarial is asked only where the source permits*."""
    graph_world.afiliados.append(
        make_afiliado(
            numero_documento="1010101010",
            edad=34,
            salario_base_cotizacion=Decimal("7500000"),
        )
    )
    chat = Conversation()
    await chat.run(ANSWERS_AFILIADO_READY)

    for field in (
        "nombre_apellido",
        "fecha_nacimiento",
        "edad",
        "otra_caja_compensacion",
        "rango_salarial",
    ):
        assert field not in chat.asked_fields, f"the graph asked an afiliado for {field}"
    assert chat.profile["rango_salarial"] == "4_8m"  # derived from the record
    assert graph_world.lead(chat.conversation_id).otra_caja_compensacion is None


async def test_no_afiliado_scoring_between_60_and_74_is_nurture(
    graph_world: World,
) -> None:
    """Spec: *Happy path no-afiliado* — READY needs 75, not 60.

    The lead below scores inside [60, 74], so the affiliation-dependent
    threshold is what decides the verdict.
    """
    chat = Conversation()
    await chat.run(ANSWERS_NO_AFILIADO)

    assert chat.profile["afiliado_colsubsidio"] is False
    assert 60 <= chat.profile["score"] <= 74
    assert chat.profile["status"] == "nurture"

    lead = graph_world.lead(chat.conversation_id)
    assert lead.status == "nurture"
    assert lead.categoria is None
    assert lead.afiliado_colsubsidio is False


async def test_no_afiliado_is_asked_identidad_otra_caja_and_rango_salarial(
    graph_world: World,
) -> None:
    """The source condition "solo si es empleado y NO es afiliado"."""
    chat = Conversation()
    await chat.run(ANSWERS_NO_AFILIADO)

    for field in ("nombre_apellido", "fecha_nacimiento", "otra_caja_compensacion",
                  "rango_salarial", "total_ingresos_mensuales"):
        assert field in chat.asked_fields, f"a no-afiliado was not asked for {field}"
    assert "total_ingresos_familiares_mensuales" not in chat.asked_fields


@pytest.mark.parametrize("edad", [17, 1])
async def test_afiliado_under_eighteen_terminates_at_the_afiliado_side_gate(
    graph_world: World, edad: int
) -> None:
    """Spec: *Menor de edad … afiliado path*.

    `afiliado_check` derives the age from the record and `_route_afiliado` sends
    the turn to `END`; no terminal status is ever written.
    """
    graph_world.afiliados.append(
        make_afiliado(numero_documento="1010101010", edad=edad)
    )
    chat = Conversation()
    farewell = await chat.run(ANSWERS_AFILIADO_READY)

    assert chat.profile["edad"] == edad
    assert "mayores de edad" in farewell
    assert chat.nodes[-1] == "afiliado_check"
    assert graph_world.lead(chat.conversation_id).status == "profiling"


async def test_no_afiliado_under_eighteen_terminates_at_the_identity_gate(
    graph_world: World,
) -> None:
    """Spec: *Menor de edad … no-afiliado path*. `edad` is computed server-side."""
    minor = dict(ANSWERS_NO_AFILIADO)
    minor["fecha_nacimiento"] = f"01/01/{date.today().year - 15}"

    chat = Conversation()
    farewell = await chat.run(minor)

    assert chat.profile["edad"] == 15
    assert "mayores de edad" in farewell
    assert chat.nodes[-1] == "recoger_identidad"
    assert graph_world.lead(chat.conversation_id).status == "profiling"


async def test_subsidio_previo_forces_nurture_for_a_soltero_lead(
    graph_world: World,
) -> None:
    """Spec: *Subsidio previo forces nurture* and *… is collected on every path*.

    A `soltero` afiliado reaches the `sin_pareja` bundle, is asked the question,
    and the absolute override fires — the regression the previous topology had,
    where the field was gated to casado/union_libre and never collected here.
    """
    graph_world.afiliados.append(
        make_afiliado(
            numero_documento="1010101010",
            categoria_afiliado="A",
            score_credito=880,
            edad=34,
            salario_base_cotizacion=Decimal("9000000"),
        )
    )
    answers = dict(ANSWERS_AFILIADO_READY)
    answers["estado_civil"] = "Soltero"
    answers["total_ingresos_mensuales"] = "6.000.000"
    answers["subsidio_vivienda_anterior"] = "Sí"

    chat = Conversation()
    await chat.run(answers)

    assert chat.profile["tiene_pareja"] is False
    assert chat.profile["subsidio_vivienda_anterior"] is True
    assert "subsidio_vivienda_anterior" in chat.asked_fields
    assert chat.profile["status"] == "nurture"
    assert (
        "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"
        in chat.profile["classification_reasoning"]
    )


async def test_pac_and_discapacidad_are_collected_on_a_soltero_afiliado_path(
    graph_world: World,
) -> None:
    """Spec: *PAC and discapacidad are collected on every path* — the `+8` bonus."""
    graph_world.afiliados.append(
        make_afiliado(numero_documento="1010101010", edad=34)
    )
    answers = dict(ANSWERS_AFILIADO_READY)
    answers["estado_civil"] = "Soltero"
    answers["total_ingresos_mensuales"] = "6.000.000"
    answers["condicion_discapacidad_familiar"] = "Sí"

    chat = Conversation()
    await chat.run(answers)

    assert "numero_pac" in chat.asked_fields
    assert "condicion_discapacidad_familiar" in chat.asked_fields
    assert chat.profile["numero_pac"] == 2
    assert chat.profile["condicion_discapacidad_familiar"] is True
    assert chat.profile["cabeza_de_hogar"] is True


async def test_independiente_is_never_asked_antiguedad(graph_world: World) -> None:
    """Spec: *Empleado vs independiente antiguedad*."""
    graph_world.afiliados.append(
        make_afiliado(numero_documento="1010101010", edad=34)
    )
    answers = dict(ANSWERS_AFILIADO_READY)
    answers["contrato_laboral"] = "Prestacion de servicios"

    chat = Conversation()
    await chat.run(answers)

    assert chat.profile["contrato_laboral"] == "prestacion_servicios"
    assert chat.profile["es_empleado"] is False
    assert "antiguedad_laboral" not in chat.asked_fields
    assert chat.nodes.count("cap_ind_con_pareja") > 0


@pytest.mark.parametrize("estado_civil", ["Divorciado", "Separado", "Viudo"])
async def test_partnerless_states_reach_the_sin_pareja_bundle(
    graph_world: World, estado_civil: str
) -> None:
    """Spec: *Pareja vs sin-pareja income fields* for the three non-soltero states."""
    graph_world.afiliados.append(
        make_afiliado(numero_documento="1010101010", edad=34)
    )
    answers = dict(ANSWERS_AFILIADO_READY)
    answers["estado_civil"] = estado_civil
    answers["total_ingresos_mensuales"] = "6.000.000"

    chat = Conversation()
    await chat.run(answers)

    assert chat.profile["tiene_pareja"] is False
    assert "total_ingresos_mensuales" in chat.asked_fields
    assert "total_ingresos_familiares_mensuales" not in chat.asked_fields
    assert chat.nodes.count("cap_emp_sin_pareja") > 0


async def test_a_ready_lead_gets_the_catalogue_and_a_nurture_lead_does_not(
    graph_world: World,
) -> None:
    """`get_projects` runs only for `status=='ready'` — no commercial noise."""
    graph_world.proyectos.append(make_proyecto("VIBO ONCE", "B1", "Soacha", "VIS"))
    chat = Conversation()
    closing = await chat.run(ANSWERS_NO_AFILIADO)

    assert chat.profile["status"] == "nurture"
    assert "VIBO ONCE" not in closing
    assert "más adelante" in closing


async def test_the_conversation_resumes_from_the_checkpointer(
    graph_world: World,
) -> None:
    """Spec: *Conversational resume across 10-minute gap*.

    Nothing about the gap is time-based — resumption is the checkpointer
    replaying `awaiting_field`, so a later turn lands on the same node with the
    profile intact and no field re-asked.
    """
    graph_world.afiliados.append(
        make_afiliado(numero_documento="1010101010", edad=34)
    )
    chat = Conversation()
    await chat.say("Hola")
    await chat.say("Sí")
    await chat.say("Cédula de ciudadanía")
    await chat.say("1010101010")
    await chat.say("Casado")

    assert chat.awaiting == "contrato_laboral"
    before = dict(chat.profile)

    # The "10 minutes later" turn: same thread, same compiled graph.
    await chat.say("Termino indefinido")

    assert chat.profile["estado_civil"] == "casado"
    assert chat.profile["numero_documento"] == before["numero_documento"]
    assert chat.asked_fields.count("estado_civil") == 1
    assert chat.asked_fields.count("tipo_documento") == 1
