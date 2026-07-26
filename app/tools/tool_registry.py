"""Tool registry — maps roles to the list of enabled tools.

For the hackathon there is a single role `"agent"`, wired to the five
lead-profiling tools of the `agent-tools` spec delta. The order below is the
order the flow uses them: identify, collect, re-read, recommend, classify.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from app.tools.lead_tools import (
    classify_lead,
    get_lead,
    get_projects,
    lookup_afiliado,
    save_lead,
)

_LEAD_TOOLS: list[BaseTool] = [
    lookup_afiliado,
    save_lead,
    get_lead,
    get_projects,
    classify_lead,
]


def get_tools_for_role(role: str) -> list[BaseTool]:
    """Return the tools allowed for the given role.

    Hackathon: a single `"agent"` role gets all five lead-profiling tools; any
    other role gets none.
    """
    role = (role or "agent").lower()
    if role == "agent":
        return list(_LEAD_TOOLS)
    return []
