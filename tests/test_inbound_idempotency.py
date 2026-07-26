"""Wamid idempotency — a Meta retry of the same webhook must not re-run the
agent turn or send a second reply.

No Postgres: `InboundMessageHandler`'s collaborators (`MessageRepository`,
`ConversationService`, `AgentService`) are replaced with in-memory doubles
that model exactly the contract the handler depends on:
  * `MessageRepository.find_by_external_id` returns a hit once the id has
    been "persisted" (simulating `AgentService.send_message` forwarding
    `external_id` into `MessageService.persist_user_message`).
  * `AgentService.send_message` records how many times it actually ran.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import app.services.inbound_handler as inbound_handler_module
from app.services.inbound_handler import InboundMessageHandler


class _World:
    def __init__(self) -> None:
        self.persisted_external_ids: set[str] = set()
        self.send_message_calls: int = 0


class _FakeMessageRepository:
    """Mirrors `MessageRepository.find_by_external_id` against `_World`."""

    def __init__(self, session, world: _World) -> None:
        self.session = session
        self.world = world

    async def find_by_external_id(self, external_id: str) -> object | None:
        return object() if external_id in self.world.persisted_external_ids else None


class _FakeConversationService:
    def __init__(self, session, world: _World) -> None:
        self.session = session
        self.world = world
        self._conv_id = uuid.uuid4()

    async def get_or_create_by_wa_id(self, wa_id: str, title: str | None = None):
        return SimpleNamespace(id=self._conv_id)


class _FakeAgentService:
    """Stands in for `AgentService`; only `send_message` is exercised.

    Records the call and simulates persisting the `external_id` — the exact
    behavior task 5.1 wires up in the real `AgentService.send_message`.
    """

    def __init__(self, session, world: _World) -> None:
        self.session = session
        self.world = world

    async def send_message(self, conversation_id, payload, *, external_id: str | None = None) -> dict:
        self.world.send_message_calls += 1
        if external_id:
            self.world.persisted_external_ids.add(external_id)
        return {"assistant_message": SimpleNamespace(content="Respuesta del agente.")}


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> _World:
    w = _World()

    monkeypatch.setattr(
        inbound_handler_module,
        "MessageRepository",
        lambda session: _FakeMessageRepository(session, w),
    )
    monkeypatch.setattr(
        inbound_handler_module,
        "ConversationService",
        lambda session: _FakeConversationService(session, w),
    )
    monkeypatch.setattr(
        inbound_handler_module,
        "AgentService",
        lambda session: _FakeAgentService(session, w),
    )
    return w


async def test_duplicate_external_id_runs_the_agent_exactly_once(world: _World) -> None:
    handler = InboundMessageHandler(session=object())
    external_id = "wamid.HASHABC123"

    await handler.handle(
        wa_id="+573000000000", text="Hola", external_id=external_id, dry_run=True,
    )
    await handler.handle(
        wa_id="+573000000000", text="Hola", external_id=external_id, dry_run=True,
    )

    assert world.send_message_calls == 1


async def test_distinct_external_ids_each_run_the_agent(world: _World) -> None:
    handler = InboundMessageHandler(session=object())

    await handler.handle(
        wa_id="+573000000000", text="Hola", external_id="wamid.ONE", dry_run=True,
    )
    await handler.handle(
        wa_id="+573000000000", text="Y ahora?", external_id="wamid.TWO", dry_run=True,
    )

    assert world.send_message_calls == 2
