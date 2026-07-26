"""Shared in-memory doubles for the tests that drive the graph.

The repository layer is the seam: `LeadRepository`,
`AfiliadoColsubsidioRepository` and `ProyectoColsubsidioRepository` are replaced
inside `app.tools.lead_tools`, so a whole conversation can be driven through the
compiled StateGraph with no Postgres and no network. The doubles implement the
contracts documented on the real repositories — field-merge upsert, the
terminal-status guard, and the catalogue lookup that reuses the production
`repair_catalogo_municipio`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest

from app.models.afiliado_model import AfiliadoColsubsidioEntity
from app.models.constants import TERMINAL_STATUSES
from app.models.lead_model import LeadColsubsidioEntity
from app.models.proyecto_model import ProyectoColsubsidioEntity
from app.models.repositories.lead_repository import LeadStatusTransitionError
from app.services.domain_normalizer import repair_catalogo_municipio
from app.services.tool_context import ToolContext
from app.tools import lead_tools


class FakeSession:
    """Stands in for an `AsyncSession`; the doubles never touch SQL."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@dataclass
class World:
    """The in-memory world a single test runs against."""

    leads: dict[uuid.UUID, LeadColsubsidioEntity] = field(default_factory=dict)
    afiliados: list[AfiliadoColsubsidioEntity] = field(default_factory=list)
    proyectos: list[ProyectoColsubsidioEntity] = field(default_factory=list)
    upsert_calls: list[tuple[uuid.UUID, dict[str, Any]]] = field(default_factory=list)
    doc_lookups: list[tuple[str, str]] = field(default_factory=list)
    project_queries: list[dict[str, Any]] = field(default_factory=list)

    def lead(self, conversation_id: uuid.UUID) -> LeadColsubsidioEntity | None:
        return self.leads.get(conversation_id)


class FakeLeadRepository:
    """Field-merge upsert plus the terminal-status guard."""

    world: World

    def __init__(self, session: Any) -> None:
        self.session = session

    async def find_by_conversation_id(
        self, conversation_id: uuid.UUID
    ) -> LeadColsubsidioEntity | None:
        return self.world.leads.get(conversation_id)

    async def upsert_by_conversation_id(
        self, conversation_id: uuid.UUID, fields: dict[str, Any]
    ) -> LeadColsubsidioEntity:
        self.world.upsert_calls.append((conversation_id, dict(fields)))
        entity = self.world.leads.get(conversation_id)
        if entity is None:
            entity = LeadColsubsidioEntity(conversation_id=conversation_id)
            entity.id = uuid.uuid4()
            entity.status = "profiling"
            entity.numero_pac = 0
            self.world.leads[conversation_id] = entity

        incoming_status = fields.get("status")
        if (
            incoming_status is not None
            and entity.status in TERMINAL_STATUSES
            and incoming_status != entity.status
        ):
            raise LeadStatusTransitionError(
                f"Lead already terminal at {entity.status!r}."
            )

        for key, value in fields.items():
            if key in {"conversation_id", "id"}:
                continue
            if key == "normalization_notes":
                merged = list(entity.normalization_notes or [])
                for note in value or []:
                    if note not in merged:
                        merged.append(note)
                entity.normalization_notes = merged
                continue
            setattr(entity, key, value)
        return entity

    async def commit(self) -> None:
        await self.session.commit()


class FakeAfiliadoRepository:
    world: World

    def __init__(self, session: Any) -> None:
        self.session = session

    async def find_by_doc(
        self, tipo_documento: str, numero_documento: str
    ) -> AfiliadoColsubsidioEntity | None:
        self.world.doc_lookups.append((tipo_documento, numero_documento))
        for row in self.world.afiliados:
            if (
                row.tipo_documento == tipo_documento
                and row.numero_documento == numero_documento
            ):
                return row
        return None


class FakeProyectoRepository:
    """`find_filtered` over the in-memory catalogue, with the real VIS repair."""

    world: World

    def __init__(self, session: Any) -> None:
        self.session = session

    async def find_filtered(
        self,
        *,
        municipio: str | None = None,
        tipo: str | None = None,
        limit: int = 5,
    ) -> list[ProyectoColsubsidioEntity]:
        self.world.project_queries.append(
            {"municipio": municipio, "tipo": tipo, "limit": limit}
        )
        rows = list(self.world.proyectos)
        if municipio is not None:
            rows = [
                r for r in rows if repair_catalogo_municipio(r.municipio) == municipio
            ]
        if tipo is not None:
            rows = [r for r in rows if r.tipo == tipo]
        rows.sort(key=lambda r: (r.proyecto, r.modelo))
        return rows[:limit]


@pytest.fixture
def graph_world(monkeypatch: pytest.MonkeyPatch) -> World:
    """Install the in-memory repository doubles into the tool module."""
    world = World()
    for repo in (FakeLeadRepository, FakeAfiliadoRepository, FakeProyectoRepository):
        repo.world = world
    monkeypatch.setattr(lead_tools, "LeadRepository", FakeLeadRepository)
    monkeypatch.setattr(
        lead_tools, "AfiliadoColsubsidioRepository", FakeAfiliadoRepository
    )
    monkeypatch.setattr(
        lead_tools, "ProyectoColsubsidioRepository", FakeProyectoRepository
    )
    return world


def make_afiliado(
    *,
    tipo_documento: str = "CC",
    numero_documento: str = "1010101010",
    nombre_apellido: str = "Andrea Marín",
    categoria_afiliado: str = "A",
    score_credito: int = 880,
    edad: int = 34,
    estado_civil: str | None = None,
    ha_recibido_subsidio: bool = False,
) -> AfiliadoColsubsidioEntity:
    """An affiliate whose stored `fecha_nacimiento` yields exactly `edad` today."""
    today = date.today()
    birth = date(today.year - edad, 1, 1)
    row = AfiliadoColsubsidioEntity(
        tipo_documento=tipo_documento,
        numero_documento=numero_documento,
        nombre_apellido=nombre_apellido,
        fecha_nacimiento=birth,
        estado_civil=estado_civil,
        categoria_afiliado=categoria_afiliado,
        score_credito=score_credito,
        ha_recibido_subsidio=ha_recibido_subsidio,
    )
    row.id = uuid.uuid4()
    return row


def make_proyecto(
    proyecto: str,
    modelo: str = "A",
    municipio: str | None = "Bogota",
    tipo: str | None = "VIS",
) -> ProyectoColsubsidioEntity:
    row = ProyectoColsubsidioEntity(
        proyecto=proyecto, modelo=modelo, municipio=municipio, tipo=tipo
    )
    row.id = uuid.uuid4()
    return row


def tool_config(conversation_id: uuid.UUID, thread: str | None = None) -> dict[str, Any]:
    """A `RunnableConfig` carrying the ToolContext and a checkpointer thread."""
    ctx = ToolContext(session=FakeSession(), conversation_id=conversation_id)
    return {
        "configurable": {
            "tool_context": ctx,
            "thread_id": thread or str(conversation_id),
        }
    }
