"""AgentState — the state that flows between Vivi lead-profiling graph nodes.

`design.md` §2. The reserved `lead_profile_draft` slot of the ReAct iteration is
retired in favour of a first-class `lead_profile` working copy that the
checkpointer persists across the multi-turn WhatsApp conversation.

`awaiting_field` is an addition to the four fields listed in `design.md` §2 and
is load-bearing: the design rules out `interrupt_before`, so the graph has no
other way to yield a turn boundary. One graph invocation is one conversational
turn — a collection node parses the answer to the field named here, asks for the
next missing one, and the turn-gate router then routes to `END` so the process
returns to the user. See `app/graph/turn_gate.py`.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """State that flows between Vivi lead-profiling graph nodes."""

    messages: Annotated[list[AnyMessage], add_messages]
    lead_profile: dict
    """Working copy of the lead — mirrored to the `leads` row by `save_lead`."""

    current_node: str
    """Diagnostic tag of the last-entered node."""

    pending_user_reply: str
    """The user's raw reply for this turn, consumed by exactly one node."""

    awaiting_field: str
    """Name of the field whose answer this turn is waiting for; `""` when none."""
