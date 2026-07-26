"""ToolContext — the runtime context injected into every tool via RunnableConfig.

Tools never accept session/conversation_id as LLM arguments (that would be a
"confused deputy"). Instead the orchestrator injects a ToolContext into
`RunnableConfig.configurable["tool_context"]`, and tools extract it via
`get_tool_context(config)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ToolContext:
    """Secure context used by tools to run queries for the current request.

    Attributes:
        session: active async DB session bound to the HTTP request.
        conversation_id: UUID of the current conversation (for audit + lead link).
    """

    session: AsyncSession
    conversation_id: UUID | None


def get_tool_context(config: dict) -> ToolContext:
    """Extract the ToolContext from a RunnableConfig.

    Raises ValueError if missing — an orchestrator bug, not user input.
    """
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    ctx = configurable.get("tool_context")
    if ctx is None:
        raise ValueError(
            "ToolContext missing in RunnableConfig. "
            "This is an orchestrator bug — tools cannot run without context."
        )
    return ctx