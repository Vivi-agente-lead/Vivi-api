"""Build and cache the LangGraph ReAct agent per role.

Uses `langgraph.prebuilt.create_react_agent`. The compiled graph is cached
via `lru_cache` (one per role). Runtime dependency injection (session,
conversation_id) flows through `RunnableConfig.configurable["tool_context"]`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from app.services.checkpointer_factory import build_checkpointer
from app.services.llm_factory import build_llm
from app.tools.tool_registry import get_tools_for_role

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

# Single hackathon role. More roles can be added later without code changes.
DEFAULT_ROLE = "agent"


@lru_cache(maxsize=4)
def _build_graph_cached(role: str) -> "CompiledStateGraph":
    """Construct and cache the compiled graph for a role."""
    from langgraph.prebuilt import create_react_agent

    llm = build_llm()
    tools = get_tools_for_role(role)
    checkpointer = build_checkpointer()

    return create_react_agent(
        model=llm,
        tools=tools,
        checkpointer=checkpointer,
    )


def build_graph(role: str = DEFAULT_ROLE) -> "CompiledStateGraph":
    """Return the compiled graph for the given role."""
    return _build_graph_cached(role)


def reset_graph_cache() -> None:
    """Invalidate the graph cache (tests / credential rotation)."""
    _build_graph_cached.cache_clear()