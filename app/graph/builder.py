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
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.graph.nodes.capacity import (
    cap_emp_con_pareja,
    cap_emp_sin_pareja,
    cap_ind_con_pareja,
    cap_ind_sin_pareja,
    recoger_empleo,
)
from app.graph.nodes.closing import handoff, recoger_intencion, scoring
from app.graph.nodes.collect import (
    recoger_estado_civil,
    recoger_identidad,
    recoger_otra_caja,
)
from app.graph.nodes.spine import (
    afiliado_check,
    autorizacion_datos,
    pedir_cedula,
    start,
)
from app.graph.router import (
    _route_afiliado,
    _route_autorizacion,
    _route_capacity,
    _route_edad,
    _route_otra_caja,
)
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

# The 15 nodes of `design.md` §3, in flow order. `recoger_subsidio_pareja` and
# `recoger_otra_caja_y_pac` of the previous design revision are collapsed into a
# single `recoger_otra_caja`: their only remaining exclusive field is
# `otra_caja_compensacion`, because `subsidio_vivienda_anterior`, `numero_pac`
# and `condicion_discapacidad_familiar` moved into the capacity bundles, where
# every branch reaches them.
NODES: dict[str, Any] = {
    "start": start,
    "autorizacion_datos": autorizacion_datos,
    "pedir_cedula": pedir_cedula,
    "afiliado_check": afiliado_check,
    "recoger_identidad": recoger_identidad,
    "recoger_estado_civil": recoger_estado_civil,
    "recoger_otra_caja": recoger_otra_caja,
    "recoger_empleo": recoger_empleo,
    "cap_emp_con_pareja": cap_emp_con_pareja,
    "cap_emp_sin_pareja": cap_emp_sin_pareja,
    "cap_ind_con_pareja": cap_ind_con_pareja,
    "cap_ind_sin_pareja": cap_ind_sin_pareja,
    "recoger_intencion": recoger_intencion,
    "scoring": scoring,
    "handoff": handoff,
}


def build_lead_profiler() -> StateGraph:
    """Assemble the Colsubsidio lead-profiling topology (`design.md` §3).

    Returns the uncompiled graph so tests can compile it with their own
    checkpointer.
    """
    graph = StateGraph(AgentState)

    for name, fn in NODES.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "start")
    graph.add_conditional_edges("start", turn_gated("autorizacion_datos"))
    graph.add_conditional_edges("autorizacion_datos", turn_gated(_route_autorizacion))
    graph.add_conditional_edges("pedir_cedula", turn_gated("afiliado_check"))
    graph.add_conditional_edges("afiliado_check", turn_gated(_route_afiliado))
    graph.add_conditional_edges("recoger_identidad", turn_gated(_route_edad))
    graph.add_conditional_edges("recoger_estado_civil", turn_gated(_route_otra_caja))
    graph.add_conditional_edges("recoger_otra_caja", turn_gated("recoger_empleo"))
    graph.add_conditional_edges("recoger_empleo", turn_gated(_route_capacity))
    for bundle in (
        "cap_emp_con_pareja",
        "cap_emp_sin_pareja",
        "cap_ind_con_pareja",
        "cap_ind_sin_pareja",
    ):
        graph.add_conditional_edges(bundle, turn_gated("recoger_intencion"))
    graph.add_conditional_edges("recoger_intencion", turn_gated("scoring"))
    graph.add_edge("scoring", "handoff")
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
