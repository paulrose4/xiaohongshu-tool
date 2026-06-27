"""Supervisor: state-driven router for the multi-agent pipeline.

The Supervisor does not call an LLM to decide routing (that would be flaky and
expensive for a fixed pipeline). Instead it reads AgentState.status and maps it
to the next node deterministically. This keeps the graph fast, testable, and
fully reproducible while still being a true Supervisor pattern: it owns the
transition function and can short-circuit to error/done at any time.
"""
from __future__ import annotations

from typing import Callable

from langgraph.graph import END, StateGraph

from .state import AgentState, append_log, set_error
from .nodes import select_node, visual_node, copy_node, publish_node

# Canonical transition table: current status -> next node function.
# Each node is expected to set state["status"] to one of these keys on success.
TRANSITIONS: dict[str, Callable[[AgentState], AgentState]] = {
    "select": select_node,
    "visual": visual_node,
    "copy": copy_node,
    "publish": publish_node,
}

# status values that mean "stop here"
TERMINAL = {"done", "error"}


def supervisor_route(state: AgentState) -> str:
    """Return the next node key based on state.status, or a terminal marker."""
    status = state.get("status", "select")
    if status in TERMINAL:
        return END
    if status in TRANSITIONS:
        return status
    # Unknown status -> error out rather than spin
    set_error(state, "supervisor", f"unknown status: {status!r}")
    return END


def build_graph():
    """Compile the LangGraph StateGraph with a Supervisor-style router."""
    g = StateGraph(AgentState)

    # Register every node by its status key.
    for key, fn in TRANSITIONS.items():
        g.add_node(key, fn)

    # Supervisor entry: route from a virtual start based on initial status.
    g.set_conditional_entry_point(
        supervisor_route,
        path_map={**{k: k for k in TRANSITIONS}, END: END},
    )

    # After each node finishes, route again based on the (possibly updated) status.
    for key in TRANSITIONS:
        g.add_conditional_edges(
            key,
            supervisor_route,
            path_map={**{k: k for k in TRANSITIONS}, END: END},
        )

    return g.compile()


def run_pipeline(instruction: str, constraints: dict | None = None, *, on_log=None) -> AgentState:
    """Execute the full pipeline from a single instruction string.

    on_log: optional callback(str) invoked for every log line, used by the SSE
    server to stream progress to the monitoring console.
    """
    initial: AgentState = {
        "instruction": instruction,
        "constraints": constraints or {},
        "status": "select",
        "current_node": "supervisor",
        "messages": [],
        "logs": [],
        "meta": {},
    }
    append_log(initial, "supervisor", f"start pipeline: {instruction!r}")

    graph = build_graph()
    final = graph.invoke(initial)

    # Mirror logs to the optional callback for SSE streaming.
    if on_log is not None:
        for line in final.get("logs", []):
            try:
                on_log(line)
            except Exception:
                pass
    return final


__all__ = ["build_graph", "run_pipeline", "supervisor_route", "TRANSITIONS"]
