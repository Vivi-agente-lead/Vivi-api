"""Lead tools for the Vivi agent.

All tools are `@tool @safe_tool` async, accept `config: RunnableConfig`, and
extract the `ToolContext` to obtain a DB session. `save_lead` writes a
`LeadEntity`; the rest are read/search stubs returning placeholder JSON
when no data source is connected.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.models.lead_model import LeadEntity
from app.models.repositories.lead_repository import LeadRepository
from app.services.tool_context import get_tool_context
from app.tools.base import json_dumps, safe_tool

logger = logging.getLogger(__name__)


def _to_lead_dict(lead: LeadEntity) -> dict[str, Any]:
    return {
        "id": str(lead.id),
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "budget_min": lead.budget_min,
        "budget_max": lead.budget_max,
        "preferred_locations": lead.preferred_locations,
        "property_type": lead.property_type,
        "status": lead.status,
        "score": lead.score,
        "conversation_id": str(lead.conversation_id) if lead.conversation_id else None,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
    }


@tool
@safe_tool
async def search_leads(query: str, *, config: RunnableConfig) -> str:
    """Search previously-saved leads by name, phone or email.

    Args:
        query: free-text search over name/phone/email.

    Returns:
        JSON string with a list of matching leads (placeholder shape if no
        data source is connected yet).
    """
    ctx = get_tool_context(config)
    repo = LeadRepository(ctx.session)
    results = await repo.search(query)
    if not results:
        return json_dumps({"leads": [], "note": "data source not connected"})
    return json_dumps({"leads": [_to_lead_dict(l) for l in results], "total": len(results)})


@tool
@safe_tool
async def get_lead(lead_id: str, *, config: RunnableConfig) -> str:
    """Get the full detail of a lead by its UUID id.

    Args:
        lead_id: UUID string of the lead.
    """
    ctx = get_tool_context(config)
    repo = LeadRepository(ctx.session)
    try:
        uid = UUID(lead_id)
    except ValueError:
        return json_dumps({"error": True, "message": f"Invalid lead_id: {lead_id!r}"})
    lead = await repo.get(uid)
    if lead is None:
        return json_dumps({"error": True, "message": f"Lead {lead_id} not found"})
    return json_dumps(_to_lead_dict(lead))


@tool
@safe_tool
async def save_lead(
    name: str,
    *,
    config: RunnableConfig,
    phone: str | None = None,
    email: str | None = None,
    budget_min: float | None = None,
    budget_max: float | None = None,
    preferred_locations: list[str] | None = None,
    property_type: str | None = None,
    notes: str | None = None,
) -> str:
    """Persist a new lead. Only call after confirming with the user.

    Requires at least a name and one contact channel (phone or email), plus
    at least one search criterion (budget, location, or property type).

    # TODO: HITL via LangGraph interrupts in next iteration — currently
    # executes the write directly.
    """
    ctx = get_tool_context(config)
    if not name or not name.strip():
        return json_dumps({"error": True, "message": "name is required"})
    if not phone and not email:
        return json_dumps(
            {"error": True, "message": "at least one contact channel (phone or email) is required"}
        )
    if budget_min is None and budget_max is None and not preferred_locations and not property_type:
        return json_dumps(
            {"error": True, "message": "at least one search criterion is required"}
        )

    lead = LeadEntity(
        conversation_id=ctx.conversation_id,
        name=name.strip(),
        phone=phone,
        email=email,
        budget_min=budget_min,
        budget_max=budget_max,
        preferred_locations=preferred_locations,
        property_type=property_type,
        notes=notes,
        status="new",
    )
    repo = LeadRepository(ctx.session)
    await repo.add(lead)
    await repo.commit()
    logger.info("save_lead.created", extra={"lead_id": str(lead.id), "name": lead.name})
    return json_dumps({"id": str(lead.id), "name": lead.name, "status": "saved"})


@tool
@safe_tool
async def score_lead(lead_id: str, *, config: RunnableConfig) -> str:
    """Compute a qualification score for a lead.

    Heuristic not yet defined — returns null score.
    """
    return json_dumps({"score": None, "note": "scoring heuristic not yet defined"})