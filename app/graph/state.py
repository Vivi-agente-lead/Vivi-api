"""AgentState — the state that flows between graph nodes.

For a simple ReAct agent the message list is enough; LangGraph merges it
with `add_messages`. Optional lead_profile draft fields are reserved for
future structured profiling, unused in this iteration.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """State for the Vivi agent graph."""

    messages: Annotated[list[AnyMessage], add_messages]
    # Reserved for next iteration: structured lead draft the LLM can fill.
    lead_profile_draft: dict