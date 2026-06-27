"""AgentState schema and context-trimming utilities.

AgentState is the strict contract that flows between every Node in the
Supervisor graph. check_and_trim_messages enforces a hard ceiling on the
accumulated context so long DOM dumps or RPA logs cannot blow the window.
"""
from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from .config import settings


class ProductInfo(TypedDict, total=False):
    """A single selected product."""

    product_id: str
    title: str
    highlights: list[str]       # core selling points
    price: float                # 客单价 (元)
    commission_rate: float      # 佣金率 0-1
    sales_30d: int              # 30天销量
    white_bg_image_url: str     # 商家白底图 URL
    shop: str
    source: str                 # taobao | pinduoduo | mock


class PublishResult(TypedDict, total=False):
    success: bool
    post_url: str
    error: str
    screenshots: list[str]
    log: list[str]


class AgentState(TypedDict, total=False):
    """Strict state object passed between Supervisor nodes."""

    # --- input ---
    instruction: str
    constraints: dict[str, Any]

    # --- selection ---
    products: list[ProductInfo]
    selected: ProductInfo

    # --- visual ---
    image_url: str
    cutout_path: str
    composite_path: str

    # --- copy ---
    copy: str
    tags: list[str]

    # --- publish ---
    publish: PublishResult

    # --- orchestration ---
    status: str                 # select | visual | copy | publish | done | error
    error: str
    current_node: str

    # --- context / observability ---
    messages: list[BaseMessage]
    logs: list[str]
    meta: dict[str, Any]


def _msg_text(m: BaseMessage) -> str:
    if isinstance(m.content, str):
        return m.content
    parts = []
    for block in m.content if isinstance(m.content, list) else [m.content]:
        if isinstance(block, dict) and "text" in block:
            parts.append(str(block["text"]))
        elif isinstance(block, str):
            parts.append(block)
    return " ".join(parts)


def check_and_trim_messages(
    messages: list[BaseMessage],
    *,
    max_chars: int | None = None,
    max_messages: int | None = None,
) -> list[BaseMessage]:
    """Trim the message list so it never exceeds the context budget.

    1. Always keep leading SystemMessage(s).
    2. Keep the most-recent max_messages non-system messages.
    3. If concatenated text still exceeds max_chars, drop oldest non-system
       messages from the front until under budget.
    4. Insert a short placeholder noting how many were elided.
    """
    cfg = settings.context
    max_chars = max_chars if max_chars is not None else cfg.max_chars
    max_messages = max_messages if max_messages is not None else cfg.max_messages

    if not messages:
        return []

    head_system: list[BaseMessage] = []
    rest: list[BaseMessage] = messages
    while rest and isinstance(rest[0], SystemMessage):
        head_system.append(rest[0])
        rest = rest[1:]

    rest = rest[-max_messages:]

    def total_chars(msgs: list[BaseMessage]) -> int:
        return sum(len(_msg_text(m)) for m in msgs)

    dropped = 0
    while rest and total_chars(head_system + rest) > max_chars:
        rest.pop(0)
        dropped += 1

    trimmed = head_system + rest
    if dropped > 0:
        note = HumanMessage(
            content=f"[context trimmed: {dropped} older message(s) elided to fit {max_chars} chars]"
        )
        trimmed.insert(len(head_system), note)
    return trimmed


def append_log(state: AgentState, node: str, message: str) -> None:
    """Append a human-readable log line and a mirrored message, then trim."""
    line = f"[{node}] {message}"
    logs = list(state.get("logs", []))
    logs.append(line)
    state["logs"] = logs

    msgs = list(state.get("messages", []))
    msgs.append(AIMessage(content=line, name=node))
    state["messages"] = check_and_trim_messages(msgs)


def set_error(state: AgentState, node: str, err: str) -> None:
    state["status"] = "error"
    state["error"] = f"{node}: {err}"
    state["current_node"] = node
    append_log(state, node, f"ERROR: {err}")
