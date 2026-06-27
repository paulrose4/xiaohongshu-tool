"""Tests for AgentState and the context-trimming utility."""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from xhs_supervisor.state import (
    AgentState,
    append_log,
    check_and_trim_messages,
)


def _make_messages(n: int, chars_each: int = 200) -> list:
    msgs = [SystemMessage(content="你是小红书运营 Supervisor。")]
    for i in range(n):
        msgs.append(HumanMessage(content=f"msg-{i}-" + "x" * chars_each))
    return msgs


def test_trim_keeps_system_message():
    msgs = _make_messages(30)
    trimmed = check_and_trim_messages(msgs, max_chars=2000, max_messages=5)
    assert isinstance(trimmed[0], SystemMessage)
    # system + placeholder + at most 5 recent
    assert len(trimmed) <= 7


def test_trim_inserts_elision_note_when_dropped():
    msgs = _make_messages(50, chars_each=500)
    trimmed = check_and_trim_messages(msgs, max_chars=1500, max_messages=20)
    texts = [m.content if isinstance(m.content, str) else "" for m in trimmed]
    assert any("context trimmed" in t for t in texts)


def test_trim_no_op_when_under_budget():
    msgs = _make_messages(2, chars_each=50)
    trimmed = check_and_trim_messages(msgs, max_chars=10000, max_messages=20)
    assert len(trimmed) == 3  # system + 2


def test_append_log_grows_and_trims():
    state: AgentState = {"messages": [], "logs": [], "status": "select"}
    for i in range(100):
        append_log(state, "selector", "x" * 300 + str(i))
    # Should be capped, not 100 entries.
    assert len(state["messages"]) < 100
    assert len(state["logs"]) == 100
