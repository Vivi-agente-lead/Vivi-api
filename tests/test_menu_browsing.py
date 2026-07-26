"""Block B — entry inversion and catalogue-browsing traversals.

`docs/v2-impact-analysis.md` §1, §8. One traversal per menu branch, plus the
back-navigation loop — proportional coverage, not an exhaustive matrix (the
field-level machinery each branch reuses is already covered by
`test_graph_traversal.py` and `test_router.py`).
"""

from __future__ import annotations

import pytest

from tests.conftest import World, make_afiliado, make_proyecto
from tests.test_graph_traversal import ANSWERS_AFILIADO_CALIFICADO, Conversation


async def test_welcome_message_interpolates_a_real_catalogue_project(
    graph_world: World,
) -> None:
    """The welcome line names an actual `proyectos_colsubsidio` row, not a
    hardcoded example — sourced through the existing `get_projects` tool."""
    graph_world.proyectos.append(make_proyecto("VIBO ONCE", "A", "Bogota", "VIS"))
    chat = Conversation()

    greeting = await chat.say("Hola")

    assert "VIBO ONCE" in greeting
    assert chat.awaiting == "menu_opcion"


async def test_welcome_message_degrades_gracefully_with_an_empty_catalogue(
    graph_world: World,
) -> None:
    """No project seeded yet: a generic welcome, never a crash or invented name."""
    chat = Conversation()

    greeting = await chat.say("Hola")

    assert "Vivi" in greeting
    assert chat.awaiting == "menu_opcion"


async def test_salir_branch_ends_the_conversation_with_no_lead_row(
    graph_world: World,
) -> None:
    """`Salir` — farewell without ever entering qualification."""
    chat = Conversation()
    await chat.say("Hola")
    farewell = await chat.say("Salir")

    assert "buen día" in farewell.lower()
    assert chat.awaiting == ""
    assert graph_world.lead(chat.conversation_id) is None
    assert graph_world.upsert_calls == []


async def test_ver_detalle_branch_enters_the_existing_qualification_flow(
    graph_world: World,
) -> None:
    """`Quiero saber más de este proyecto` converges on `autorizacion_datos`,
    exactly like Block A's linear flow."""
    chat = Conversation()
    await chat.say("Hola")
    reply = await chat.say("Quiero saber más de este proyecto")

    assert "autorizas" in reply.lower()
    assert chat.awaiting == "autorizacion_datos"


async def test_browsing_branch_collects_preferencia_and_municipio_up_front(
    graph_world: World,
) -> None:
    """`Quiero ver otro proyecto.` collects `preferencia_vis` and
    `lugar_eleccion_vivir` / `municipio_normalizado` *before* qualification,
    then converges on `autorizacion_datos` without ever asking either field
    again in `recoger_intencion`."""
    graph_world.afiliados.append(make_afiliado(numero_documento="1010101010"))
    chat = Conversation()
    await chat.say("Hola")
    await chat.say("Quiero ver otro proyecto.")
    assert chat.awaiting == "preferencia_vis"

    await chat.say("VIS")
    assert chat.awaiting == "lugar_eleccion_vivir"

    await chat.say("Bogotá norte")
    assert chat.awaiting == "volver_menu_anterior"
    assert chat.profile["preferencia_vis"] == "vis"
    assert chat.profile["municipio_normalizado"] == "Bogota"

    reply = await chat.say("No")
    assert "autorizas" in reply.lower()
    assert chat.awaiting == "autorizacion_datos"

    # Finish the qualification flow and confirm neither field is re-asked.
    answers = dict(ANSWERS_AFILIADO_CALIFICADO)
    answers.pop("menu_opcion")
    for reply_text in (
        "Sí",
        "Cédula de ciudadanía",
        "1010101010",
        "Casado",
        "Termino indefinido",
        "9.000.000",
        "2.000.000",
        "No",
        "2",
        "No",
        "Más de $40 millones",
        "Un apartamento con dos habitaciones y balcón.",
        "3 meses",
    ):
        await chat.say(reply_text)

    assert chat.asked_fields.count("lugar_eleccion_vivir") == 1
    assert chat.asked_fields.count("preferencia_vis") == 1
    assert chat.profile["lugar_eleccion_vivir"] == "Bogotá norte"


async def test_back_navigation_loops_to_the_municipio_question(
    graph_world: World,
) -> None:
    """`El usuario selecciona volver al menu anterior` (Sí) loops back to the
    municipio question, not to the top-level menu — `preferencia_vis` is
    never re-asked."""
    chat = Conversation()
    await chat.say("Hola")
    await chat.say("Quiero ver otro proyecto.")
    await chat.say("Ambas")
    await chat.say("Soacha")
    assert chat.awaiting == "volver_menu_anterior"

    await chat.say("Sí")
    assert chat.awaiting == "lugar_eleccion_vivir", (
        "going back must re-ask the municipio question, not the top menu"
    )

    await chat.say("Chía")
    assert chat.awaiting == "volver_menu_anterior"
    assert chat.profile["municipio_normalizado"] == "Chía"

    reply = await chat.say("No")
    assert "autorizas" in reply.lower()

    assert chat.asked_fields.count("lugar_eleccion_vivir") == 2
    assert chat.asked_fields.count("preferencia_vis") == 1
    assert chat.asked_fields.count("menu_opcion") == 1
