"""Behaviour tests for the five lead-profiling agent tools.

Covers the ``agent-tools`` spec delta (requirement *Lead-Profiling Tool
Surface*). Every test drives the real ``@tool``-decorated callable through
``ainvoke`` so the ``@tool`` → ``@safe_tool`` → tool-body stack is exercised
end to end.

No Postgres is required. The repository layer is the seam: in-memory doubles
replace ``LeadRepository`` / ``AfiliadoColsubsidioRepository`` /
``ProyectoColsubsidioRepository`` inside ``app.tools.lead_tools``, so the tests
assert what the *tool* does (normalization, note recording, status handling,
``conversation_id`` resolution, catalogue lookup) rather than what SQLAlchemy
does. The proyecto double reuses the production ``repair_catalogo_municipio``
so the ``'VIS'`` repair under test is the real mapping, not a copy.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.models.afiliado_model import AfiliadoColsubsidioEntity
from app.models.constants import STATUS_DOMAIN
from app.models.lead_model import LeadColsubsidioEntity
from app.models.proyecto_model import ProyectoColsubsidioEntity
from app.services.domain_normalizer import repair_catalogo_municipio
from app.services.tool_context import ToolContext
from app.tools import lead_tools
from app.tools.lead_tools import (
    classify_lead,
    compute_edad,
    get_lead,
    get_projects,
    lookup_afiliado,
    save_lead,
)

# ── Test doubles ────────────────────────────────────────────────────────────


class _FakeSession:
    """Stands in for an ``AsyncSession``; the doubles never touch SQL."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@dataclass
class _World:
    """The in-memory world a single test runs against."""

    leads: dict[uuid.UUID, LeadColsubsidioEntity] = field(default_factory=dict)
    afiliados: list[AfiliadoColsubsidioEntity] = field(default_factory=list)
    proyectos: list[ProyectoColsubsidioEntity] = field(default_factory=list)
    upsert_calls: list[tuple[uuid.UUID, dict[str, Any]]] = field(default_factory=list)
    doc_lookups: list[tuple[str, str]] = field(default_factory=list)
    project_queries: list[dict[str, Any]] = field(default_factory=list)


class _FakeLeadRepository:
    """Implements the ``LeadRepository`` contract documented in its docstring.

    Field-merge semantics: only the keys present in ``fields`` are written,
    absent keys keep their previous value, and ``normalization_notes`` is
    appended to rather than replaced.
    """

    world: _World

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
            self.world.leads[conversation_id] = entity
        for key, value in fields.items():
            if key == "normalization_notes":
                merged = list(entity.normalization_notes or [])
                for note in value or []:
                    if note not in merged:
                        merged.append(note)
                entity.normalization_notes = merged
                continue
            if key in {"conversation_id", "id"}:
                continue
            setattr(entity, key, value)
        return entity

    async def commit(self) -> None:
        await self.session.commit()


class _FakeAfiliadoRepository:
    world: _World

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


class _FakeProyectoRepository:
    """Implements ``find_filtered`` over the in-memory catalogue.

    The ``'VIS'`` → ``'Bogota'`` repair is applied by calling the production
    ``repair_catalogo_municipio`` on each *stored* value, so the repair under
    test is the real mapping and the stored rows stay verbatim.
    """

    world: _World

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
            rows = [r for r in rows if repair_catalogo_municipio(r.municipio) == municipio]
        if tipo is not None:
            rows = [r for r in rows if r.tipo == tipo]
        rows.sort(key=lambda r: (r.proyecto, r.modelo))
        return rows[:limit]


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> _World:
    """Install the in-memory repository doubles into the tool module."""
    w = _World()
    for repo in (_FakeLeadRepository, _FakeAfiliadoRepository, _FakeProyectoRepository):
        repo.world = w
    monkeypatch.setattr(lead_tools, "LeadRepository", _FakeLeadRepository)
    monkeypatch.setattr(
        lead_tools, "AfiliadoColsubsidioRepository", _FakeAfiliadoRepository
    )
    monkeypatch.setattr(
        lead_tools, "ProyectoColsubsidioRepository", _FakeProyectoRepository
    )
    return w


CONVERSATION_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_CONVERSATION_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _config(conversation_id: uuid.UUID | None = CONVERSATION_ID) -> dict[str, Any]:
    ctx = ToolContext(session=_FakeSession(), conversation_id=conversation_id)
    return {"configurable": {"tool_context": ctx}}


def _afiliado(
    *,
    tipo_documento: str = "CC",
    numero_documento: str = "12345678",
    categoria_afiliado: str = "A",
    score_credito: int = 820,
    fecha_nacimiento: date | None = None,
    ha_recibido_subsidio: bool = False,
) -> AfiliadoColsubsidioEntity:
    row = AfiliadoColsubsidioEntity(
        tipo_documento=tipo_documento,
        numero_documento=numero_documento,
        nombre_apellido="Andrea Marín",
        fecha_nacimiento=fecha_nacimiento or date(date.today().year - 30, 1, 1),
        categoria_afiliado=categoria_afiliado,
        score_credito=score_credito,
        ha_recibido_subsidio=ha_recibido_subsidio,
    )
    row.id = uuid.uuid4()
    return row


def _proyecto(
    proyecto: str, modelo: str, municipio: str | None, tipo: str | None = "VIS"
) -> ProyectoColsubsidioEntity:
    row = ProyectoColsubsidioEntity(
        proyecto=proyecto, modelo=modelo, municipio=municipio, tipo=tipo
    )
    row.id = uuid.uuid4()
    return row


# ── compute_edad (pure) ─────────────────────────────────────────────────────


def test_compute_edad_counts_a_birthday_already_passed_this_year() -> None:
    """A birthday on or before `today` has already been celebrated."""
    assert compute_edad(date(2000, 7, 26), today=date(2026, 7, 26)) == 26


def test_compute_edad_does_not_count_a_birthday_still_ahead_this_year() -> None:
    """A birthday later this year has not been celebrated yet."""
    assert compute_edad(date(2000, 7, 27), today=date(2026, 7, 26)) == 25


def test_compute_edad_returns_none_without_a_birth_date() -> None:
    """No `fecha_nacimiento` means no derivable age (never a default)."""
    assert compute_edad(None, today=date(2026, 7, 26)) is None


# ── lookup_afiliado ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("slug", ["CC", "CE", "PA", "PEP", "PPT"])
async def test_lookup_afiliado_accepts_every_source_document_slug(
    world: _World, slug: str
) -> None:
    """All five source document types reach the composite-key lookup."""
    result = await lookup_afiliado.ainvoke(
        {"tipo_documento": slug, "numero_documento": "12345678"}, config=_config()
    )

    assert world.doc_lookups == [(slug, "12345678")], (
        f"{slug} must reach the afiliado lookup"
    )
    assert json.loads(result) == {"afiliado": None}


async def test_lookup_afiliado_rejects_tipo_documento_ti(world: _World) -> None:
    """`TI` appears nowhere in the source domain and must not be accepted."""
    result = await lookup_afiliado.ainvoke(
        {"tipo_documento": "TI", "numero_documento": "12345678"}, config=_config()
    )

    payload = json.loads(result)
    assert payload["error"] is True
    assert payload["code"] == "invalid_tipo_documento"
    assert world.doc_lookups == [], "a rejected document type must not hit the database"


async def test_lookup_afiliado_returns_null_afiliado_for_an_unknown_cedula(
    world: _World,
) -> None:
    """An unknown cedula yields `{afiliado: null}` — never an exception."""
    world.afiliados.append(_afiliado(numero_documento="12345678"))

    result = await lookup_afiliado.ainvoke(
        {"tipo_documento": "CC", "numero_documento": "99999999"}, config=_config()
    )

    assert json.loads(result) == {"afiliado": None}


async def test_lookup_afiliado_returns_the_derived_edad_and_score_rating(
    world: _World,
) -> None:
    """A hit carries `categoria_afiliado`, derived `edad`, `score_rating`, subsidy flag."""
    world.afiliados.append(
        _afiliado(
            numero_documento="12345678",
            categoria_afiliado="A",
            score_credito=820,
            fecha_nacimiento=date(date.today().year - 30, 1, 1),
            ha_recibido_subsidio=True,
        )
    )

    result = await lookup_afiliado.ainvoke(
        {"tipo_documento": "CC", "numero_documento": "12345678"}, config=_config()
    )

    afiliado = json.loads(result)["afiliado"]
    assert afiliado["categoria_afiliado"] == "A"
    assert afiliado["score_credito"] == 820
    assert afiliado["score_rating"] == "Excelente"
    assert afiliado["edad"] == 30
    assert afiliado["ha_recibido_subsidio"] is True


# ── save_lead ───────────────────────────────────────────────────────────────


async def test_save_lead_writes_only_the_supplied_fields(world: _World) -> None:
    """The upsert carries the supplied field and nothing the caller omitted."""
    await save_lead.ainvoke({"total_ingresos_mensuales": 3500000}, config=_config())

    conversation_id, fields = world.upsert_calls[-1]
    assert conversation_id == CONVERSATION_ID
    assert fields["total_ingresos_mensuales"] == Decimal("3500000")
    assert "estado_civil" not in fields, (
        "an omitted field must not be sent, or the merge would NULL it"
    )


async def test_save_lead_never_promotes_status(world: _World) -> None:
    """`save_lead` must not write `status` — only `classify_lead` may."""
    await save_lead.ainvoke(
        {"total_ingresos_mensuales": 3500000, "status": "ready"}, config=_config()
    )

    _, fields = world.upsert_calls[-1]
    assert "status" not in fields
    assert world.leads[CONVERSATION_ID].status == "profiling"


async def test_save_lead_upsert_preserves_previously_set_fields(world: _World) -> None:
    """A later save merges onto the row; earlier answers survive."""
    await save_lead.ainvoke({"estado_civil": "soltero"}, config=_config())

    await save_lead.ainvoke({"total_ingresos_mensuales": 3500000}, config=_config())

    row = world.leads[CONVERSATION_ID]
    assert row.estado_civil == "soltero"
    assert row.total_ingresos_mensuales == Decimal("3500000")


async def test_save_lead_normalizes_a_verbatim_source_label(world: _World) -> None:
    """A verbatim workbook label is stored as its canonical slug."""
    await save_lead.ainvoke(
        {"ahorros_o_cesantias": "Menos de $3 millones"}, config=_config()
    )

    _, fields = world.upsert_calls[-1]
    assert fields["ahorros_o_cesantias"] == "menos_3m"


async def test_save_lead_nulls_an_unrecognized_value_and_records_it(
    world: _World,
) -> None:
    """An unmappable value is written NULL and appended to the notes."""
    await save_lead.ainvoke(
        {"ahorros_o_cesantias": "unos pesitos guardados"}, config=_config()
    )

    _, fields = world.upsert_calls[-1]
    assert fields["ahorros_o_cesantias"] is None
    notes = fields["normalization_notes"]
    assert any("unos pesitos guardados" in note for note in notes), notes
    assert any("ahorros_o_cesantias" in note for note in notes), notes


async def test_save_lead_normalizes_the_municipio_join_key(world: _World) -> None:
    """`municipio_normalizado` lands on the catalogue vocabulary, not the raw option."""
    await save_lead.ainvoke(
        {"lugar_eleccion_vivir": "Bogotá norte"}, config=_config()
    )

    _, fields = world.upsert_calls[-1]
    assert fields["lugar_eleccion_vivir"] == "Bogotá norte", "the raw option is the audit trail"
    assert fields["municipio_normalizado"] == "Bogota"


async def test_save_lead_ignores_an_llm_supplied_conversation_id(
    world: _World,
) -> None:
    """The LLM cannot forge a cross-conversation write."""
    await save_lead.ainvoke(
        {
            "estado_civil": "soltero",
            "conversation_id": str(OTHER_CONVERSATION_ID),
        },
        config=_config(CONVERSATION_ID),
    )

    assert list(world.leads) == [CONVERSATION_ID]
    _, fields = world.upsert_calls[-1]
    assert "conversation_id" not in fields


# ── get_lead ────────────────────────────────────────────────────────────────


async def test_get_lead_returns_null_when_no_row_exists(world: _World) -> None:
    """Asking for context before any save yields `null`, not an exception."""
    result = await get_lead.ainvoke({}, config=_config())

    assert json.loads(result) is None


async def test_get_lead_returns_the_current_row(world: _World) -> None:
    """Once a row exists, `get_lead` returns it as a `leads`-shaped dict."""
    await save_lead.ainvoke(
        {"estado_civil": "soltero", "numero_pac": 2}, config=_config()
    )

    payload = json.loads(await get_lead.ainvoke({}, config=_config()))

    assert payload["estado_civil"] == "soltero"
    assert payload["numero_pac"] == 2
    assert payload["status"] == "profiling"


# ── get_projects ────────────────────────────────────────────────────────────


async def test_get_projects_returns_the_bogota_rows_including_the_repaired_vis_row(
    world: _World,
) -> None:
    """`municipio='VIS'` is repaired to `Bogota` at lookup time; the row stays `'VIS'`."""
    world.proyectos.extend(
        [
            _proyecto("ALAMEDA", "A1", "Bogota"),
            _proyecto("VIBO ONCE", "B2", "VIS", tipo="VIS"),
            _proyecto("SABANA", "C1", "Soacha"),
        ]
    )

    payload = json.loads(
        await get_projects.ainvoke({"municipio": "Bogota"}, config=_config())
    )

    nombres = [p["proyecto"] for p in payload["proyectos"]]
    assert nombres == ["ALAMEDA", "VIBO ONCE"], "Soacha must not match Bogota"
    vibo = next(p for p in payload["proyectos"] if p["proyecto"] == "VIBO ONCE")
    assert vibo["municipio"] == "VIS", "the stored row keeps the source value verbatim"


async def test_get_projects_orders_by_proyecto_then_modelo_and_caps_at_five(
    world: _World,
) -> None:
    """Deterministic order and a hard cap of 5 candidates."""
    world.proyectos.extend(
        [
            _proyecto("ZAFIRO", "A", "Bogota"),
            _proyecto("ALAMEDA", "B", "Bogota"),
            _proyecto("ALAMEDA", "A", "Bogota"),
            _proyecto("MIRADOR", "A", "Bogota"),
            _proyecto("NOGAL", "A", "Bogota"),
            _proyecto("PORTAL", "A", "Bogota"),
        ]
    )

    payload = json.loads(
        await get_projects.ainvoke({"municipio": "Bogota"}, config=_config())
    )

    keys = [(p["proyecto"], p["modelo"]) for p in payload["proyectos"]]
    assert keys == [
        ("ALAMEDA", "A"),
        ("ALAMEDA", "B"),
        ("MIRADOR", "A"),
        ("NOGAL", "A"),
        ("PORTAL", "A"),
    ]
    assert world.project_queries[-1]["limit"] == 5


# ── classify_lead ───────────────────────────────────────────────────────────


async def test_classify_lead_returns_a_verdict_whose_classification_is_the_status(
    world: _World,
) -> None:
    """`classification == status`, drawn from the single shared domain."""
    world.afiliados.append(_afiliado(numero_documento="1010101010", score_credito=880))
    await save_lead.ainvoke(
        {
            "tipo_documento": "CC",
            "numero_documento": "1010101010",
            "afiliado_colsubsidio": True,
            "categoria": "A",
            "score_credito": 880,
            "rango_salarial": "mas_10m",
            "ahorros_o_cesantias": "mas_40m",
            "tiempo_compra_deseado": "3_meses",
            "contrato_laboral": "termino_indefinido",
        },
        config=_config(),
    )

    verdict = json.loads(await classify_lead.ainvoke({}, config=_config()))

    # v2 renames the terminal status vocabulary: ready → calificado
    # (docs/v2-impact-analysis.md §7).
    assert verdict["status"] == "calificado"
    assert verdict["classification"] == verdict["status"]
    assert verdict["status"] in STATUS_DOMAIN
    assert verdict["score_rating"] == "Excelente"
    assert verdict["score"] >= 60
    assert "Umbral READY aplicado: 60" in verdict["reasoning"]


async def test_classify_lead_persists_the_verdict_on_the_lead_row(
    world: _World,
) -> None:
    """The verdict is written back: status, score, score_rating, reasoning."""
    await save_lead.ainvoke(
        {
            "tipo_documento": "CC",
            "numero_documento": "3030303030",
            "afiliado_colsubsidio": False,
            "tiempo_compra_deseado": "no_se",
        },
        config=_config(),
    )

    verdict = json.loads(await classify_lead.ainvoke({}, config=_config()))

    row = world.leads[CONVERSATION_ID]
    assert row.status == verdict["status"]
    assert row.score == verdict["score"]
    assert row.score_rating == verdict["score_rating"]
    assert row.classification_reasoning == verdict["reasoning"]


async def test_classify_lead_reports_a_missing_row_instead_of_raising(
    world: _World,
) -> None:
    """Classifying a conversation with no lead row returns a structured error."""
    payload = json.loads(await classify_lead.ainvoke({}, config=_config()))

    assert payload["error"] is True
    assert payload["code"] == "lead_not_found"


# ── Module invariances ──────────────────────────────────────────────────────


def test_lead_tools_does_not_import_langgraph() -> None:
    """The tool layer is a stateless service layer — no graph runtime import."""
    source = Path(lead_tools.__file__).read_text(encoding="utf-8")
    offenders = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and "langgraph" in line
    ]
    assert offenders == [], f"langgraph must not be imported here: {offenders}"


def test_tool_registry_exposes_exactly_the_five_agent_tools() -> None:
    """The agent role is wired to the five lead-profiling tools, in order."""
    from app.tools.tool_registry import get_tools_for_role

    names = [t.name for t in get_tools_for_role("agent")]
    assert names == [
        "lookup_afiliado",
        "save_lead",
        "get_lead",
        "get_projects",
        "classify_lead",
    ]


def test_tool_registry_returns_nothing_for_an_unknown_role() -> None:
    """An unrecognized role gets no tools."""
    from app.tools.tool_registry import get_tools_for_role

    assert get_tools_for_role("auditor") == []
