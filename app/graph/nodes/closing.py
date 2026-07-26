"""Closing nodes: `recoger_intencion`, `scoring`, `handoff` (`design.md` §4).

Task 4.4 lands `handoff` as a stub so the spine is traversable end to end before
any branch exists; tasks 4.8 fills in the rest.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.graph.nodes._common import profile_of, say

logger = logging.getLogger(__name__)

__all__ = ["handoff"]

_FALLBACK_CLOSING = (
    "Gracias por tus respuestas. Un asesor de vivienda de Colsubsidio revisará "
    "tu caso y te contactará para acompañarte en el siguiente paso."
)


async def handoff(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Close the conversation with the next step this lead has earned."""
    profile = profile_of(state)
    message = await say(
        state, node="handoff", profile=profile, text=_FALLBACK_CLOSING
    )
    logger.info("graph.handoff", extra={"status": profile.get("status")})
    return {
        "current_node": "handoff",
        "lead_profile": profile,
        "messages": [message],
    }
