"""Node 3: 文案智能体 (Copywriter).

Model:  DeepSeek-v4-pro or GLM-5.2 via OpenAI-compatible Chat Completions.
Input:  state["selected"]  (商品参数: title/highlights/price/...)
Output: state["copy"]  (小红书种草文案) + state["tags"] (SEO 话题标签)

The System Prompt is hard-coded per spec (23岁深圳独居女孩人设). The node
includes retry, temperature control, and a 250-char guard.
"""
from __future__ import annotations

import logging
import re

from openai import OpenAI

from ..config import settings
from ..retry import with_retry
from ..state import AgentState, append_log, set_error

_log = logging.getLogger("xhs.copywriter")

# ---- Hard-coded persona / system prompt (per spec, do not soften) ----------
SYSTEM_PROMPT = (
    "你现在是一个23岁、刚毕业在深圳租房的独居女孩。你喜欢挖宝平价好物。"
    "请根据提供的商品参数，写一篇小红书种草文案。要求："
    "1. 悬念或情绪化标题（如‘穷鬼女孩请焊死这件好物’）；"
    "2. 首段直击痛点（如租房空间小/工资低）；"
    "3. 次段口语化转化卖点；"
    "4. 全文多用 Emoji（✨、😭、🛒）；"
    "5. 结尾加 5 个相关的 SEO 话题标签（#独居女孩提升幸福感好物 #平价好物）。"
    "字数 250 字内。"
)


def _build_user_prompt(product: dict) -> str:
    """Render the selected product into a compact spec for the model."""
    highlights = product.get("highlights") or []
    hl = "、".join(highlights) if highlights else "无"
    return (
        "商品参数如下，请据此写文案：\n"
        f"- 标题：{product.get('title', '')}\n"
        f"- 核心卖点：{hl}\n"
        f"- 客单价：{product.get('price', '')} 元\n"
        f"- 佣金率：{product.get('commission_rate', '')}\n"
        f"- 30天销量：{product.get('sales_30d', '')}\n"
        f"- 店铺：{product.get('shop', '')}\n"
    )


def _client() -> OpenAI:
    """Build an OpenAI-compatible client pointed at the configured provider."""
    llm = settings.llm
    if not llm.api_key:
        # Allow a no-key dry-run by pointing at a stub; otherwise this is a
        # real misconfiguration we surface as a clear error.
        append_log(_state_ref(), "copy", "WARNING: no LLM api key configured")
    return OpenAI(api_key=llm.api_key or "missing", base_url=llm.base_url)


# A tiny module-level holder so helper functions can log without threading
# state through every call. Set at the top of the node entry.
_state_ref = lambda: None  # noqa: E731


@with_retry(name="llm_chat", exceptions=(Exception,))
def _chat(client: OpenAI, product: dict) -> str:
    resp = client.chat.completions.create(
        model=settings.llm.model,
        temperature=settings.copywriter.temperature,
        max_tokens=512,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(product)},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def _extract_tags(text: str) -> list[str]:
    """Pull out #话题标签 from the generated copy for downstream use."""
    return re.findall(r"#[^\s#]+", text)


def _enforce_length(text: str, max_chars: int) -> str:
    """Hard guard: if the model ran long, trim to the last完整 line under limit."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # try to cut at a newline so we don't split a tag
    nl = cut.rfind("\n")
    if nl > max_chars * 0.6:
        cut = cut[:nl]
    return cut.rstrip() + "…"


def copy_node(state: AgentState) -> AgentState:
    """文案节点: 用配置的 LLM 生成小红书种草文案, 写入 state."""
    global _state_ref
    _state_ref = lambda: state  # noqa: E731

    product = state.get("selected")
    if not product:
        set_error(state, "copy", "no selected product in state")
        return state

    append_log(state, "copy", f"generating copy via {settings.llm.provider}/{settings.llm.model}")

    try:
        client = _client()
        raw = _chat(client, product)
    except Exception as e:  # noqa: BLE001
        set_error(state, "copy", f"LLM call failed: {e}")
        return state

    copy = _enforce_length(raw, settings.copywriter.max_chars)
    tags = _extract_tags(copy)

    state["copy"] = copy
    state["tags"] = tags
    state["status"] = "publish"
    state["current_node"] = "copy"
    append_log(state, "copy", f"copy generated ({len(copy)} chars, {len(tags)} tags)")
    return state


__all__ = ["copy_node", "SYSTEM_PROMPT"]
