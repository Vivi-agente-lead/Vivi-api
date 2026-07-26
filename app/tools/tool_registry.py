"""Tool registry — maps roles to the list of enabled tools.

For the hackathon there is a single role `"agent"` that gets all lead tools.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from app.tools.lead_tools import (
    get_lead,
    save_lead,
    score_lead,
    search_leads,
)

_LEAD_TOOLS: list[BaseTool] = [search_leads, get_lead, save_lead, score_lead]


def get_tools_for_role(role: str) -> list[BaseTool]:
    """Return the tools allowed for the given role.

    Hackathon: a single `"agent"` role gets all lead tools.
    """
    role = (role or "agent").lower()
    if role == "agent":
        return list(_LEAD_TOOLS)
    return []