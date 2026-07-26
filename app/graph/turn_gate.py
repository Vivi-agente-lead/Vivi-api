"""The turn boundary of the lead-profiling graph.

`design.md` §3 rules out `interrupt_before`, and LangGraph has no other built-in
way to hand control back to the user mid-graph. So **one graph invocation is one
conversational turn**: a node parses the answer to the field it asked for last
turn, asks for the next missing one, and then the graph must stop so the process
can reply over WhatsApp and wait.

`turn_gated` is the single mechanism that implements it. It wraps every outgoing
edge — the static ones from `design.md` §4 and the five predicates from §3 — so
that a node which just asked a question routes to `END`, and otherwise the
design's own destination applies. The predicates in `app/graph/router.py` stay
pure and unaware of turns, which is what keeps them testable in isolation.

Resumption is the checkpointer's job: `awaiting_field` is part of `AgentState`,
so the next invocation replays the spine (every already-answered node is a
pass-through) and lands on the node that owns the awaited field.
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END

__all__ = ["turn_gated"]


def turn_gated(destination: str | Callable[[Any], str]) -> Callable[[Any], str]:
    """Wrap an edge so an unanswered question ends the turn.

    Args:
        destination: a node id (a static `design.md` §4 edge) or a router
            predicate from `app/graph/router.py`.

    Returns:
        A predicate returning the `END` sentinel once some node has asked a
        question in this invocation, and the wrapped destination otherwise.
    """

    def _gated(state: Any) -> str:
        if state.get("asked_this_turn"):
            return END
        if callable(destination):
            return destination(state)
        return destination

    _gated.__name__ = (
        f"turn_gated_{destination.__name__ if callable(destination) else destination}"
    )
    return _gated
