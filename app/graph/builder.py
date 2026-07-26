"""Build and cache the compiled lead-profiling graph.

`build_graph(role)` returns the compiled Colsubsidio `StateGraph`. The cache and
the `build_graph` / `reset_graph_cache` API are unchanged from the ReAct
iteration, so `AgentService` needs no knowledge of which graph it is driving.

`langgraph.prebuilt.create_react_agent` is no longer used anywhere: a single
loose tool loop cannot enforce the eligibility gates 100% of the time, which is
the whole reason this graph exists.

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
from app.core.exceptions import ServiceUnavailableError
from app.graph.nodes.capacity import recoger_capacidad, recoger_empleo
from app.graph.nodes.closing import handoff, recoger_intencion, scoring
from app.graph.nodes.collect import (
    recoger_estado_civil,
    recoger_identidad,
    recoger_interes_afiliacion,
)
from app.graph.nodes.spine import (
    afiliado_check,
    autorizacion_datos,
    pedir_cedula,
    start,
)
from app.graph.router import _route_afiliado, _route_autorizacion, _route_edad
from app.graph.state import AgentState
from app.graph.turn_gate import turn_gated
from app.services.checkpointer_factory import build_checkpointer

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

# Single hackathon role. More roles can be added later without code changes.
DEFAULT_ROLE = "agent"

# The v2 linear topology (`docs/v2-impact-analysis.md`; Block A of the
# graph-topology migration). The four v1 capacity bundles and
# `recoger_otra_caja` collapse into `recoger_capacidad` and
# `recoger_interes_afiliacion` respectively — see those modules' docstrings.
NODES: dict[str, Any] = {
    "start": start,
    "autorizacion_datos": autorizacion_datos,
    "pedir_cedula": pedir_cedula,
    "afiliado_check": afiliado_check,
    "recoger_identidad": recoger_identidad,
    "recoger_interes_afiliacion": recoger_interes_afiliacion,
    "recoger_estado_civil": recoger_estado_civil,
    "recoger_empleo": recoger_empleo,
    "recoger_capacidad": recoger_capacidad,
    "recoger_intencion": recoger_intencion,
    "scoring": scoring,
    "handoff": handoff,
}


def build_lead_profiler() -> StateGraph:
    """Assemble the Colsubsidio lead-profiling topology.

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
    # No-afiliado only: `_route_edad` routes an adult straight to
    # `recoger_interes_afiliacion`, a node only this branch ever reaches — the
    # affiliation question is gated to non-affiliates by topology, not by a
    # separate predicate.
    graph.add_conditional_edges("recoger_identidad", turn_gated(_route_edad))
    graph.add_conditional_edges(
        "recoger_interes_afiliacion", turn_gated("recoger_estado_civil")
    )
    graph.add_conditional_edges("recoger_estado_civil", turn_gated("recoger_empleo"))
    graph.add_conditional_edges("recoger_empleo", turn_gated("recoger_capacidad"))
    graph.add_conditional_edges("recoger_capacidad", turn_gated("recoger_intencion"))
    graph.add_conditional_edges("recoger_intencion", turn_gated("scoring"))
    graph.add_edge("scoring", "handoff")
    graph.add_edge("handoff", END)

    return graph


@lru_cache(maxsize=4)
def _build_graph_cached(role: str) -> "CompiledStateGraph":
    """Construct and cache the compiled graph for a role."""
    if not settings.lead_profiler_enabled:
        # The prebuilt ReAct agent this flag used to fall back to is gone: one
        # loose tool loop cannot enforce the Colsubsidio eligibility gates, and
        # keeping a second, unverified conversational path alive was the larger
        # risk. Turning the flag off is now a configuration error, stated
        # loudly rather than silently degrading the demo.
        raise ServiceUnavailableError(
            message=(
                "LEAD_PROFILER_ENABLED is off and there is no alternative graph. "
                "Set it to true."
            ),
            error_code="lead_profiler_disabled",
        )

    logger.info("graph.build.lead_profiler", extra={"role": role})
    return build_lead_profiler().compile(checkpointer=build_checkpointer())


def build_graph(role: str = DEFAULT_ROLE) -> "CompiledStateGraph":
    """Return the compiled graph for the given role."""
    return _build_graph_cached(role)


def reset_graph_cache() -> None:
    """Invalidate the graph cache (tests / credential rotation)."""
    _build_graph_cached.cache_clear()
