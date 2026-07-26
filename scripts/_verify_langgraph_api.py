"""Throwaway verification of the LangGraph 1.2.9 API surface that design.md §3 depends on.

Phase 0, task 0.2 of the `colsubsidio-lead-profiling` change. The previous design
revision took the API from docs without the package installed, which is how the
`return "END"` (literal) defect survived. This script re-verifies the surface
against the pinned `langgraph==1.2.9` declared in `pyproject.toml` and recorded
in `requirements.lock`, and is the evidence backing any later edit of §3.

Underscore-prefixed so it is clearly not production code. It is intentionally
self-contained and makes no network calls. Run: `python scripts/_verify_langgraph_api.py`.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


def _section(title: str) -> None:
    logger.info("")
    logger.info("=" * 72)
    logger.info(title)
    logger.info("=" * 72)


def check_imports() -> dict[str, Any]:
    """(1) END sentinel value and (5) create_react_agent resolution."""
    out: dict[str, Any] = {}
    from langgraph.graph import END, START, StateGraph  # noqa: F401

    out["END_repr"] = repr(END)
    out["END_type"] = type(END).__name__
    out["END_value"] = END
    assert END == "__end__", f"END sentinel is {END!r}, design.md §3 expects '__end__'"
    assert END != "END", "END resolves to the literal 'END' — the original defect is back"

    try:
        from langgraph.prebuilt import create_react_agent  # noqa: F401

        out["create_react_agent"] = "resolves"
        out["create_react_agent_ok"] = True
    except Exception as exc:  # noqa: BLE001
        out["create_react_agent"] = f"FAIL: {type(exc).__name__}: {exc}"
        out["create_react_agent_ok"] = False
        # Phase 4 retires create_react_agent; Phase 0 only flags a break, does not remove it.
        logger.warning(
            "create_react_agent no longer resolves in langgraph==1.2.9 — "
            "app/graph/builder.py:27 needs a minimal compat shim (do NOT remove it)."
        )
    return out


def check_state_graph_signature() -> dict[str, Any]:
    """(2) StateGraph constructor + add_node(async) + add_conditional_edges(path_map)."""
    import inspect
    from collections.abc import Awaitable, Callable, Hashable, Sequence
    from typing import Any as _Any

    from langgraph.graph import StateGraph

    out: dict[str, Any] = {}

    class _Schema(TypedDict, total=False):
        messages: list
        counter: int

    # Constructor accepts a TypedDict-like schema.
    builder = StateGraph(_Schema)
    out["constructor_typeddict"] = "accepts"

    # add_node accepts an async callable.
    async def _node(state: _Schema) -> dict[str, Any]:
        return {"counter": state.get("counter", 0) + 1}

    builder.add_node("n", _node)
    out["add_node_async"] = "accepts"

    sig = inspect.signature(StateGraph.add_conditional_edges)
    out["add_conditional_edges_sig"] = str(sig)
    params = set(sig.parameters)
    assert "path_map" in params, (
        f"add_conditional_edges has no `path_map` parameter — design.md §3 modern form "
        f"`add_conditional_edges(src, router_fn, {{label: dst}})` is unsupported. sig={sig}"
    )

    def _router(state: dict) -> str:
        return "dst" if state.get("counter", 0) > 0 else "dst_alt"

    builder.add_conditional_edges("n", _router, {"dst": "dst", "dst_alt": "dst_alt"})
    out["add_conditional_edges_with_path_map"] = "accepts dict path_map"
    return out


def check_compile_and_run() -> dict[str, Any]:
    """(3) async partial-state merge + (4) compile(checkpointer=...) -> runnable."""
    from typing import Any as _Any, TypedDict as _TD

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    class _S(_TD, total=False):
        messages: list
        counter: int

    async def _inc(state: _S) -> dict[str, _Any]:
        # Partial state delta — langgraph merges into the full state.
        return {"counter": state.get("counter", 0) + 1}

    builder = StateGraph(_S)
    builder.add_node("inc", _inc)
    builder.add_edge(START, "inc")
    builder.add_edge("inc", END)

    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    out: dict[str, Any] = {
        "compile_with_checkpointer": "returns runnable",
        "has_ainvoke": hasattr(graph, "ainvoke"),
        "has_astream": hasattr(graph, "astream"),
    }
    assert out["has_ainvoke"] and out["has_astream"], (
        "compiled graph lacks ainvoke/astream — design.md §3 async contract is broken"
    )
    return out


async def _run_async_checks() -> dict[str, Any]:
    """Drive the compiled graph end to end to prove the async-merge contract."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import RunnableConfig  # noqa: F401 — provenance of config

    class _S(TypedDict, total=False):
        messages: list
        counter: int

    async def _inc(state: _S) -> dict[str, Any]:
        return {"counter": state.get("counter", 0) + 1}

    builder = StateGraph(_S)
    builder.add_node("inc", _inc)
    builder.add_edge(START, "inc")
    builder.add_edge("inc", END)

    graph = builder.compile(checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "verify-1"}}
    result = await graph.ainvoke({"counter": 41}, config=config)
    return {
        "ainvoke_result": dict(result),
        "partial_state_merged": result.get("counter") == 42,
    }


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stdout,
    )
    results: dict[str, Any] = {}

    _section("(1) END sentinel + (5) create_react_agent")
    results["imports"] = check_imports()

    _section("(2) StateGraph + add_node + add_conditional_edges(path_map)")
    results["signature"] = check_state_graph_signature()

    _section("(4) compile(checkpointer=...) -> runnable")
    results["compile"] = check_compile_and_run()

    _section("(3) async node: partial state delta merges")
    import asyncio

    results["async_merge"] = asyncio.run(_run_async_checks())

    _section("VERDICT")
    failures: list[str] = []
    if not results["imports"].get("create_react_agent_ok"):
        failures.append("create_react_agent needs a compat shim in app/graph/builder.py")
    if not results["async_merge"].get("partial_state_merged"):
        failures.append("partial state delta was not merged by langgraph")
    if not results["imports"]["END_value"] == "__end__":
        failures.append("END sentinel value mismatch")

    if failures:
        logger.error("FAIL: %s", failures)
        return 1

    logger.info("ALL ASSERTIONS PASSED against langgraph==1.2.9.")
    logger.info("design.md §3 (END sentinel, async delta merge, compile(checkpointer=...), ")
    logger.info("add_conditional_edges path_map) is consistent with the installed package.")
    logger.info("create_react_agent still resolves — no builder.py shim needed before Phase 4.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())