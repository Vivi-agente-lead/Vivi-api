"""Build and cache the compiled lead-profiling graph.

`build_graph(role)` returns the Colsubsidio `StateGraph` when
`settings.lead_profiler_enabled` is on, and the legacy prebuilt ReAct agent
otherwise. The cache and the `build_graph` / `reset_graph_cache` API are
unchanged from the ReAct iteration, so `AgentService` needs no knowledge of
which graph it is driving.

Every outgoing edge goes through `turn_gated` (`app/graph/turn_gate.py`): the
design rules out interrupts, so a node that has just asked a question routes to
`END` and the process replies to the user. See that module for why.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.graph.nodes.closing import handoff
from app.graph.nodes.spine import (
    afiliado_check,
    autorizacion_datos,
    pedir_cedula,
    start,
)
from app.graph.router import _route_autorizacion
from app.graph.state import AgentState
from app.graph.turn_gate import turn_gated
from app.services.checkpointer_factory import build_checkpointer
from app.services.llm_factory import build_llm
from app.tools.tool_registry import get_tools_for_role

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

# Single hackathon role. More roles can be added later without code changes.
DEFAULT_ROLE = "agent"


def build_lead_profiler() -> StateGraph:
    """Assemble the Colsubsidio lead-profiling topology (`design.md` §3).

    Returns the uncompiled graph so tests can compile it with their own
    checkpointer.
    """
    graph = StateGraph(AgentState)

    graph.add_node("start", start)
    graph.add_node("autorizacion_datos", autorizacion_datos)
    graph.add_node("pedir_cedula", pedir_cedula)
    graph.add_node("afiliado_check", afiliado_check)
    graph.add_node("handoff", handoff)

    graph.add_edge(START, "start")
    graph.add_conditional_edges("start", turn_gated("autorizacion_datos"))
    graph.add_conditional_edges("autorizacion_datos", turn_gated(_route_autorizacion))
    graph.add_conditional_edges("pedir_cedula", turn_gated("afiliado_check"))
    graph.add_conditional_edges("afiliado_check", turn_gated("handoff"))
    graph.add_edge("handoff", END)

    return graph


@lru_cache(maxsize=4)
def _build_graph_cached(role: str) -> "CompiledStateGraph":
    """Construct and cache the compiled graph for a role."""
    checkpointer = build_checkpointer()

    if settings.lead_profiler_enabled:
        logger.info("graph.build.lead_profiler")
        return build_lead_profiler().compile(checkpointer=checkpointer)

    from langgraph.prebuilt import create_react_agent

    logger.info("graph.build.react_fallback", extra={"role": role})
    return create_react_agent(
        model=build_llm(),
        tools=get_tools_for_role(role),
        checkpointer=checkpointer,
    )


def build_graph(role: str = DEFAULT_ROLE) -> "CompiledStateGraph":
    """Return the compiled graph for the given role."""
    return _build_graph_cached(role)


def reset_graph_cache() -> None:
    """Invalidate the graph cache (tests / credential rotation)."""
    _build_graph_cached.cache_clear()
