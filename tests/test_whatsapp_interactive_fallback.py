"""A failed interactive send must never lose the turn — it falls back to
`send_text` with the exact same reply the person would otherwise have missed.

Follows the same in-memory-double pattern as `test_inbound_idempotency.py`:
`AgentService` is replaced with a fake that returns a `lead_profile` question
plus its option metadata (what `AgentService._persist_turn` produces once a
pending field carries options), and `WhatsAppClient` is replaced with a fake
whose interactive methods raise, so only the degrade-to-text path is under
test.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import app.services.inbound_handler as inbound_handler_module
from app.services.inbound_handler import InboundMessageHandler


class _FakeMessageRepository:
    def __init__(self, session) -> None:
        self.session = session

    async def find_by_external_id(self, external_id: str) -> object | None:
        return None


class _FakeConversationService:
    def __init__(self, session) -> None:
        self.session = session
        self._conv_id = uuid.uuid4()

    async def get_or_create_by_wa_id(self, wa_id: str, title: str | None = None):
        return SimpleNamespace(id=self._conv_id)


class _FakeAgentServiceWithOptions:
    """Simulates a turn that just asked an enumerated question."""

    def __init__(self, session) -> None:
        self.session = session

    async def send_message(self, conversation_id, payload, *, external_id: str | None = None) -> dict:
        return {
            "assistant_message": SimpleNamespace(content="¿Cuál es tu estado civil?\n- Soltero\n- Casado"),
            "interactive": {
                "field": "estado_civil",
                "options": ["Soltero", "Casado"],
                "stem": "¿Cuál es tu estado civil?",
            },
        }


class _RaisingWhatsAppClient:
    """`send_interactive_*` always raises; `send_text` records its calls."""

    def __init__(self) -> None:
        self.text_calls: list[tuple[str, str]] = []

    async def send_interactive_buttons(self, to, body, buttons):
        raise RuntimeError("no open 24h customer-service window")

    async def send_interactive_list(self, to, body, sections, *, button_text="Ver opciones"):
        raise RuntimeError("no open 24h customer-service window")

    async def send_text(self, to: str, body: str) -> dict:
        self.text_calls.append((to, body))
        return {"status": "ok", "data": {}}


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        inbound_handler_module, "MessageRepository", lambda session: _FakeMessageRepository(session)
    )
    monkeypatch.setattr(
        inbound_handler_module, "ConversationService", lambda session: _FakeConversationService(session)
    )
    monkeypatch.setattr(inbound_handler_module, "AgentService", _FakeAgentServiceWithOptions)
    fake_client = _RaisingWhatsAppClient()
    monkeypatch.setattr(inbound_handler_module, "get_whatsapp_client", lambda: fake_client)
    return fake_client


async def test_interactive_send_failure_falls_back_to_text(wired: _RaisingWhatsAppClient) -> None:
    handler = InboundMessageHandler(session=object())

    await handler.handle(
        wa_id="+573000000000",
        text="Hola",
        external_id="wamid.FALLBACK1",
        dry_run=False,
    )

    assert wired.text_calls == [
        ("+573000000000", "¿Cuál es tu estado civil?\n- Soltero\n- Casado")
    ]


async def test_simulator_channel_never_attempts_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    """The simulator can't tap anything, so it must always get plain text —
    the interactive client methods are never even called."""
    monkeypatch.setattr(
        inbound_handler_module, "MessageRepository", lambda session: _FakeMessageRepository(session)
    )
    monkeypatch.setattr(
        inbound_handler_module, "ConversationService", lambda session: _FakeConversationService(session)
    )
    monkeypatch.setattr(inbound_handler_module, "AgentService", _FakeAgentServiceWithOptions)

    calls = {"interactive": 0}

    class _TrackingClient(_RaisingWhatsAppClient):
        async def send_interactive_buttons(self, to, body, buttons):
            calls["interactive"] += 1
            return await super().send_interactive_buttons(to, body, buttons)

        async def send_interactive_list(self, to, body, sections, *, button_text="Ver opciones"):
            calls["interactive"] += 1
            return await super().send_interactive_list(to, body, sections, button_text=button_text)

    fake_client = _TrackingClient()
    monkeypatch.setattr(inbound_handler_module, "get_whatsapp_client", lambda: fake_client)

    handler = InboundMessageHandler(session=object())
    await handler.handle(
        wa_id="+573000000000",
        text="Hola",
        external_id="wamid.SIM1",
        dry_run=False,
        channel="simulator",
    )

    assert calls["interactive"] == 0
    assert len(fake_client.text_calls) == 1
