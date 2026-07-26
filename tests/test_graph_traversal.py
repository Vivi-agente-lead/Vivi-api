"""End-to-end traversals of the compiled lead-profiling StateGraph.

One graph invocation is one conversational turn (`app/graph/turn_gate.py`), so a
conversation is driven here by invoking the compiled graph once per user reply
against a shared `MemorySaver` thread — exactly what `AgentService` does per
inbound WhatsApp message.

No LLM and no Postgres: `phrase` falls back to the deterministic question bank
when `OPENAI_API_KEY` is empty, and `conftest.py` swaps the repositories for
in-memory doubles.

v2 migration (``docs/v2-impact-analysis.md``): the four capacity bundles
collapse into `recoger_capacidad`; `antiguedad_laboral` and
`condicion_discapacidad_familiar` are gone; the no-afiliado branch asks
`edad` directly instead of `fecha_nacimiento`; `otra_caja_compensacion`
(v1's caja-name prompt) is replaced by `recoger_interes_afiliacion`, gated to
non-affiliates; and the terminal status vocabulary renames
`ready`/`nurture`/`nurture_social` to `calificado`/`nutrible`/`no_calificado`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.graph.builder import build_lead_profiler
from tests.conftest import World, make_afiliado, make_proyecto, tool_config

# Answers keyed by the field the graph is waiting for. `Conversation.run` replies
# with the matching entry until the graph stops asking, so a test states the
# lead's answers once and the traversal itself decides which ones are reached —
# a bundle that wrongly asked for a removed field would show up as a KeyError
# naming the field, not as a silent pass.
ANSWERS_AFILIADO_CALIFICADO = {
    "menu_opcion": "Quiero saber más de este proyecto",
    "autorizacion_datos": "Sí",
    "tipo_documento": "Cédula de ciudadanía",
    "numero_documento": "1010101010",
    "estado_civil": "Casado",
    "contrato_laboral": "Termino indefinido",
    "total_ingresos_mensuales": "9.000.000",
    "gastos_mensuales": "2.000.000",
    "tiene_vivienda_propia": "No",
    "numero_pac": "2",
    "subsidio_vivienda_anterior": "No",
    "ahorros_o_cesantias": "Más de $40 millones",
    "lugar_eleccion_vivir": "Bogotá norte",
    "descripcion_vivienda_sueno": "Un apartamento con dos habitaciones y balcón.",
    "tiempo_compra_deseado": "3 meses",
}

ANSWERS_NO_AFILIADO = {
    "menu_opcion": "Quiero saber más de este proyecto",
    "autorizacion_datos": "Sí",
    "tipo_documento": "Cédula de ciudadanía",
    "numero_documento": "1234567890",
    "nombre_apellido": "Camilo Restrepo",
    "edad": "36",
    "interes_afiliacion": "Si estoy interesado en afiliarme",
    "estado_civil": "Soltero",
    "contrato_laboral": "Termino indefinido",
    "total_ingresos_mensuales": "5.000.000",
    "gastos_mensuales": "3.000.000",
    "tiene_vivienda_propia": "No",
    "numero_pac": "0",
    "subsidio_vivienda_anterior": "No",
    "ahorros_o_cesantias": "Entre $3 y $10 millones",
    "lugar_eleccion_vivir": "Soacha",
    "descripcion_vivienda_sueno": "Una casa pequeña con patio.",
    "tiempo_compra_deseado": "6 meses",
}

# Chosen so `simulate_bureau_cedula` bands Malo (0 pts) and the subsidio-previo
# override lands well below `NURTURE_FLOOR` (30) — the third terminal.
ANSWERS_NO_CALIFICADO = {
    "menu_opcion": "Quiero saber más de este proyecto",
    "autorizacion_datos": "Sí",
    "tipo_documento": "Cédula de ciudadanía",
    "numero_documento": "5555555555",
    "nombre_apellido": "Laura Gómez",
    "edad": "40",
    "interes_afiliacion": "No, prefiero en otro momento.",
    "estado_civil": "Soltero",
    "contrato_laboral": "Prestacion de servicios",
    "total_ingresos_mensuales": "1.000.000",
    "gastos_mensuales": "900.000",
    "tiene_vivienda_propia": "No",
    "numero_pac": "0",
    "subsidio_vivienda_anterior": "Sí",
    "ahorros_o_cesantias": "No tengo ahorros.",
    "lugar_eleccion_vivir": "Ubaté",
    "descripcion_vivienda_sueno": "Algo sencillo y tranquilo.",
    "tiempo_compra_deseado": "No sé",
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

    assert "opción" in (await chat.say("Hola")).lower()
    assert chat.awaiting == "menu_opcion"

    assert "autorizas" in (
        await chat.say("Quiero saber más de este proyecto")
    ).lower()
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
        "menu_proyecto",
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
    for reply in (
        "Hola",
        "Quiero saber más de este proyecto",
        "Sí",
        "CC",
        "1010101010",
    ):
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
    for reply in (
        "Hola",
        "Quiero saber más de este proyecto",
        "Sí",
        "CC",
        "99887766",
    ):
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
    await chat.say("Quiero saber más de este proyecto")
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
    await chat.say("Quiero saber más de este proyecto")
    await chat.say("Sí")
    await chat.say("Tarjeta de identidad")

    assert chat.awaiting == "tipo_documento"
    assert chat.profile.get("tipo_documento") is None
    assert any(
        "tipo_documento" in note for note in chat.profile.get("normalization_notes", [])
    )


# ── Full traversals — the three terminals ───────────────────────────────────
async def test_afiliado_happy_path_reaches_calificado_and_sees_projects(
    graph_world: World,
) -> None:
    """Spec: *Happy path afiliado reaches Calificado*.

    `status='calificado'`, `score >= 60`, `get_projects` invoked, and the
    closing message routes to a human asesor.
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
    closing = await chat.run(ANSWERS_AFILIADO_CALIFICADO)

    assert chat.profile["status"] == "calificado"
    assert chat.profile["score"] >= 60
    assert "asesor" in closing.lower()
    assert "VIBO ONCE" in closing

    lead = graph_world.lead(chat.conversation_id)
    assert lead.status == "calificado"
    assert lead.score == chat.profile["score"]
    assert lead.municipio_normalizado == "Bogota"
    assert lead.lugar_eleccion_vivir == "Bogotá norte"
    assert graph_world.project_queries, "get_projects was never called"


async def test_afiliado_is_never_asked_identidad_interes_afiliacion_or_rango_salarial(
    graph_world: World,
) -> None:
    """Spec: *Afiliado branch skips identidad, interes_afiliacion, edad* and
    *rango_salarial is always derived, never asked*."""
    graph_world.afiliados.append(
        make_afiliado(
            numero_documento="1010101010",
            edad=34,
            salario_base_cotizacion=Decimal("7500000"),
        )
    )
    chat = Conversation()
    await chat.run(ANSWERS_AFILIADO_CALIFICADO)

    for field in (
        "nombre_apellido",
        "edad",
        "interes_afiliacion",
        "rango_salarial",
    ):
        assert field not in chat.asked_fields, f"the graph asked an afiliado for {field}"
    assert chat.profile["rango_salarial"] == "4_8m"  # derived from the record
    assert graph_world.lead(chat.conversation_id).otra_caja_compensacion is None
    assert graph_world.lead(chat.conversation_id).interes_afiliacion is None


async def test_no_afiliado_gets_the_seventy_five_threshold_and_lands_on_nutrible(
    graph_world: World,
) -> None:
    """Spec: *Happy path no-afiliado* — Calificado needs 75 for a no-afiliado,
    not 60.

    The assertion is the **threshold that was applied**, not a hard-coded score.
    A no-afiliado's credit band comes from `simulate_bureau_cedula`, which lives
    in `credit_bands.py`; pinning the exact number here would make this
    traversal test fail whenever that simulation is retuned, for a reason that
    has nothing to do with the graph. What the graph owes the spec is that the
    affiliation-dependent threshold reached the scorer at all.
    """
    chat = Conversation()
    await chat.run(ANSWERS_NO_AFILIADO)

    assert chat.profile["afiliado_colsubsidio"] is False
    assert (
        "Umbral READY aplicado: 75 (no afiliado)"
        in chat.profile["classification_reasoning"]
    )
    assert 30 <= chat.profile["score"] < 75
    assert chat.profile["status"] == "nutrible"

    lead = graph_world.lead(chat.conversation_id)
    assert lead.status == "nutrible"
    assert lead.categoria is None
    assert lead.afiliado_colsubsidio is False


async def test_no_afiliado_is_asked_identidad_and_interes_afiliacion_never_rango(
    graph_world: World,
) -> None:
    """The affiliation question is gated to non-affiliates; rango_salarial is
    always derived, never asked directly, on either branch."""
    chat = Conversation()
    await chat.run(ANSWERS_NO_AFILIADO)

    for field in ("nombre_apellido", "edad", "interes_afiliacion", "total_ingresos_mensuales"):
        assert field in chat.asked_fields, f"a no-afiliado was not asked for {field}"
    assert "rango_salarial" not in chat.asked_fields
    assert chat.profile["rango_salarial"] == "4_8m"  # derived from total_ingresos_mensuales
    lead = graph_world.lead(chat.conversation_id)
    assert lead.interes_afiliacion == "interesado_afiliarse"
    assert lead.otra_caja_compensacion is False


async def test_no_afiliado_reaches_no_calificado(graph_world: World) -> None:
    """The third terminal: `Calificar lead` → `No calificado`.

    The subsidio-previo override forces `no_calificado` when the raw score is
    below `NURTURE_FLOOR`, and no follow-up is drawn.
    """
    chat = Conversation()
    closing = await chat.run(ANSWERS_NO_CALIFICADO)

    assert chat.profile["status"] == "no_calificado"
    assert chat.profile["score"] < 30
    assert (
        "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"
        in chat.profile["classification_reasoning"]
    )
    assert "VIBO" not in closing


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
    farewell = await chat.run(ANSWERS_AFILIADO_CALIFICADO)

    assert chat.profile["edad"] == edad
    assert "mayores de edad" in farewell
    assert chat.nodes[-1] == "afiliado_check"
    assert graph_world.lead(chat.conversation_id).status == "profiling"


async def test_no_afiliado_under_eighteen_terminates_at_the_identity_gate(
    graph_world: World,
) -> None:
    """Spec: *Menor de edad … no-afiliado path*. v2 asks `edad` directly."""
    minor = dict(ANSWERS_NO_AFILIADO)
    minor["edad"] = "15"

    chat = Conversation()
    farewell = await chat.run(minor)

    assert chat.profile["edad"] == 15
    assert "mayores de edad" in farewell
    assert chat.nodes[-1] == "recoger_identidad"
    assert graph_world.lead(chat.conversation_id).status == "profiling"


async def test_subsidio_previo_forces_nutrible_regardless_of_estado_civil(
    graph_world: World,
) -> None:
    """Spec: *Subsidio previo forces nutrible* and *… is collected on every
    path* — the household capacity block asks every lead, soltero included,
    now that the four bundles collapsed into one."""
    graph_world.afiliados.append(
        make_afiliado(
            numero_documento="1010101010",
            categoria_afiliado="A",
            score_credito=880,
            edad=34,
            salario_base_cotizacion=Decimal("9000000"),
        )
    )
    answers = dict(ANSWERS_AFILIADO_CALIFICADO)
    answers["estado_civil"] = "Soltero"
    answers["subsidio_vivienda_anterior"] = "Sí"

    chat = Conversation()
    await chat.run(answers)

    assert chat.profile["subsidio_vivienda_anterior"] is True
    assert "subsidio_vivienda_anterior" in chat.asked_fields
    assert chat.profile["status"] == "nutrible"
    assert (
        "Subsidio de vivienda previo otorgado — no califica para nuevo subsidio"
        in chat.profile["classification_reasoning"]
    )


async def test_pac_bonus_is_collected_regardless_of_estado_civil(
    graph_world: World,
) -> None:
    """Spec: *PAC is collected on every path* — the `+8` bonus."""
    graph_world.afiliados.append(
        make_afiliado(numero_documento="1010101010", edad=34)
    )
    answers = dict(ANSWERS_AFILIADO_CALIFICADO)
    answers["estado_civil"] = "Soltero"

    chat = Conversation()
    await chat.run(answers)

    assert "numero_pac" in chat.asked_fields
    assert chat.profile["numero_pac"] == 2
    assert "+8" in chat.profile["classification_reasoning"]


async def test_contrato_laboral_supports_the_new_independiente_slug(
    graph_world: World,
) -> None:
    """Spec: v2 column O splits `Independiente` from `Prestacion de servicios`."""
    graph_world.afiliados.append(
        make_afiliado(numero_documento="1010101010", edad=34)
    )
    answers = dict(ANSWERS_AFILIADO_CALIFICADO)
    answers["contrato_laboral"] = "Independiente"

    chat = Conversation()
    await chat.run(answers)

    assert chat.profile["contrato_laboral"] == "independiente"
    assert chat.profile["es_empleado"] is False
    assert "antiguedad_laboral" not in chat.asked_fields


@pytest.mark.parametrize("estado_civil", ["Divorciado", "Union libre"])
async def test_every_estado_civil_reaches_the_same_household_capacity_node(
    graph_world: World, estado_civil: str
) -> None:
    """The four v1 bundles collapse into one: every estado_civil converges on
    `recoger_capacidad` and asks the single `total_ingresos_mensuales` field —
    there is no more familiar-income variant to switch on."""
    graph_world.afiliados.append(
        make_afiliado(numero_documento="1010101010", edad=34)
    )
    answers = dict(ANSWERS_AFILIADO_CALIFICADO)
    answers["estado_civil"] = estado_civil

    chat = Conversation()
    await chat.run(answers)

    assert "total_ingresos_mensuales" in chat.asked_fields
    assert chat.nodes.count("recoger_capacidad") > 0


async def test_a_calificado_lead_gets_the_catalogue_and_a_nutrible_lead_does_not(
    graph_world: World,
) -> None:
    """`get_projects` runs only for `status=='calificado'` — no commercial noise."""
    graph_world.proyectos.append(make_proyecto("VIBO ONCE", "B1", "Soacha", "VIS"))
    chat = Conversation()
    closing = await chat.run(ANSWERS_NO_AFILIADO)

    assert chat.profile["status"] == "nutrible"
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
    await chat.say("Quiero saber más de este proyecto")
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
