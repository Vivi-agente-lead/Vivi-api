"""Block C — the credit-advisor hand-off, end to end through the graph.

`docs/v2-impact-analysis.md` §7-§8. `Calificado` → "Me ha encantado tu
entusiasmo…" → `¿Te conecto con un asesor de crédito?` → notification logged
→ final closing message. `Nutrible` / `No calificado` are unaffected (Block
A's behavior, unchanged).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.graph.nodes import closing
from tests.conftest import World, make_afiliado
from tests.test_graph_traversal import (
    ANSWERS_AFILIADO_CALIFICADO,
    ANSWERS_NO_CALIFICADO,
    Conversation,
)


class _RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, *, subject: str, body: str, context: dict[str, Any]) -> None:
        self.calls.append({"subject": subject, "body": body, "context": context})


@pytest.fixture
def recording_notifier(monkeypatch: pytest.MonkeyPatch) -> _RecordingNotifier:
    """Swap the notification call `closing.notificar_asesor_credito` makes for
    one this test can inspect, instead of the real `LoggingNotifier`."""
    recorder = _RecordingNotifier()

    async def _fake(profile: dict[str, Any], *, quiere_asesor_credito: bool | None) -> None:
        await recorder.send(
            subject=f"Lead calificado: {profile.get('nombre_apellido')}",
            body=str(profile.get("numero_documento")),
            context={"quiere_asesor_credito": quiere_asesor_credito},
        )

    monkeypatch.setattr(closing, "notify_lead_qualified", _fake)
    return recorder


async def test_calificado_lead_is_asked_about_a_credit_advisor_then_notified(
    graph_world: World, recording_notifier: _RecordingNotifier
) -> None:
    graph_world.afiliados.append(
        make_afiliado(
            numero_documento="1010101010",
            categoria_afiliado="A",
            score_credito=880,
            edad=34,
            salario_base_cotizacion=Decimal("7500000"),
        )
    )
    chat = Conversation()
    closing_reply = await chat.run(ANSWERS_AFILIADO_CALIFICADO)

    assert chat.profile["status"] == "calificado"
    assert "interes_asesor_credito" in chat.asked_fields
    assert chat.profile["interes_asesor_credito"] is True
    assert "asesor" in closing_reply.lower()
    assert len(recording_notifier.calls) == 1
    assert recording_notifier.calls[0]["context"]["quiere_asesor_credito"] is True


async def test_no_calificado_lead_is_never_asked_about_a_credit_advisor(
    graph_world: World, recording_notifier: _RecordingNotifier
) -> None:
    """Block A behavior, unchanged: only `Calificado` continues past `handoff`."""
    chat = Conversation()
    await chat.run(ANSWERS_NO_CALIFICADO)

    assert chat.profile["status"] == "no_calificado"
    assert "interes_asesor_credito" not in chat.asked_fields
    assert recording_notifier.calls == []


async def test_credit_advisor_answer_does_not_branch_the_closing_message(
    graph_world: World, recording_notifier: _RecordingNotifier
) -> None:
    """The v2 diagram draws no branch on Sí/No — both proceed the same way."""
    graph_world.afiliados.append(
        make_afiliado(
            numero_documento="1010101010",
            categoria_afiliado="A",
            score_credito=880,
            edad=34,
            salario_base_cotizacion=Decimal("7500000"),
        )
    )
    answers = dict(ANSWERS_AFILIADO_CALIFICADO)
    answers["interes_asesor_credito"] = "No"

    chat = Conversation()
    closing_reply = await chat.run(answers)

    assert chat.profile["interes_asesor_credito"] is False
    assert "próximamente" in closing_reply or "proximamente" in closing_reply
    assert len(recording_notifier.calls) == 1
