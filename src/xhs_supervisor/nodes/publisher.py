"""Node 4: RPA 发布网关 (Publishing Gateway).

Stack:     Playwright.
Browser:   指纹浏览器 (BitBrowser / AdsPower / 类似) 通过 CDP 调试端口接管.
Input:     state["composite_path"] + state["copy"]
Output:    state["publish"] (success/post_url/screenshots/log)

Flow:
  1. Connect Playwright to the fingerprint browser via CDP port.
  2. Open 小红书创作者中心 发布页.
  3. Human-like random delays + scrolling (防风控).
  4. Upload the composite image.
  5. Type the generated copy.
  6. [PLACEHOLDER] 挂载商品卡片 DOM interaction (adapt to current DOM).
  7. Click 发布.

Every navigation/interaction is wrapped with retry + explicit timeouts. The
node never hard-fails the whole pipeline on a soft selector miss: it records
what happened and lets the Supervisor decide.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    ElementHandle,
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    async_playwright,
)

from ..config import settings
from ..retry import with_retry
from ..state import AgentState, PublishResult, append_log, set_error

_log = logging.getLogger("xhs.publisher")


# ---------------------------------------------------------------------------
# Human-like helpers
# ---------------------------------------------------------------------------
async def _human_delay(min_s: float | None = None, max_s: float | None = None) -> None:
    lo = min_s if min_s is not None else settings.rpa.min_delay
    hi = max_s if max_s is not None else settings.rpa.max_delay
    await asyncio.sleep(random.uniform(lo, hi))


async def _human_scroll(page: Page, steps: int = 3) -> None:
    """Randomised scroll bursts to mimic a real user reading the page."""
    for _ in range(steps):
        dy = random.randint(120, 420)
        try:
            await page.mouse.wheel(0, dy)
        except Exception:  # noqa: BLE001
            await page.evaluate(f"window.scrollBy(0, {dy})")
        await _human_delay(0.4, 1.1)


async def _human_type(page: Page, selector: str, text: str) -> None:
    """Type with per-keystroke jitter so keypress timing isn't robotic."""
    el = await page.wait_for_selector(selector, timeout=15000)
    await el.click()
    await _human_delay(0.3, 0.8)
    for ch in text:
        await page.keyboard.type(ch)
        # occasional micro-pause, longer after punctuation
        if ch in "。，！？\n":
            await asyncio.sleep(random.uniform(0.18, 0.45))
        else:
            await asyncio.sleep(random.uniform(0.02, 0.09))


# ---------------------------------------------------------------------------
# Browser connection (fingerprint browser via CDP)
# ---------------------------------------------------------------------------
async def _connect_browser(pw: Playwright) -> tuple[Browser, BrowserContext, bool]:
    """Connect to a running fingerprint browser on CDP port, else launch own.

    Returns (browser, context, is_managed). When is_managed is True we are
    responsible for closing the browser at the end.
    """
    port = settings.rpa.fingerprint_browser_cdp_port
    endpoint = f"http://127.0.0.1:{port}"
    try:
        browser = await pw.chromium.connect_over_cdp(endpoint)
        # fingerprint browsers expose existing contexts; reuse the first.
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        append_log(_state_ref(), "publish", f"connected to fingerprint browser @ {endpoint}")
        return browser, ctx, False
    except Exception as e:  # noqa: BLE001
        _log.warning("CDP connect failed (%s); launching local chromium", e)
        append_log(_state_ref(), "publish", f"CDP unavailable ({e}); launching local chromium")
        browser = await pw.chromium.launch(headless=settings.rpa.headless)
        ctx = await browser.new_context()
        return browser, ctx, True


_state_ref = lambda: None  # noqa: E731


# ---------------------------------------------------------------------------
# Publishing steps (each retryable)
# ---------------------------------------------------------------------------
@with_retry(name="open_creator", exceptions=(PWTimeoutError, OSError))
async def _open_creator(page: Page) -> None:
    await page.goto(settings.rpa.xhs_creator_url, wait_until="domcontentloaded", timeout=30000)
    await _human_delay(2.0, 4.0)
    if settings.rpa.human_like_scroll:
        await _human_scroll(page, steps=2)


@with_retry(name="upload_image", exceptions=(PWTimeoutError,))
async def _upload_image(page: Page, image_path: str) -> None:
    """Click the upload entry and feed the file.

    小红书发布页通常有一个 file input; we target it directly to be robust
    against layout changes, then fall back to clicking an upload trigger.
    """
    # Direct file input path (most robust).
    file_input = await page.query_selector("input[type='file'][accept*='image']")
    if file_input:
        await file_input.set_input_files(image_path)
        await _human_delay(1.5, 2.5)
        return

    # Fallback: click a visible upload button, then handle the chooser.
    async with page.expect_file_chooser(timeout=15000) as fc_info:
        await page.click("text=上传图片", timeout=10000)
    fc = await fc_info.value
    await fc.set_files(image_path)
    await _human_delay(1.5, 2.5)


@with_retry(name="type_copy", exceptions=(PWTimeoutError,))
async def _type_copy(page: Page, copy: str) -> None:
    """Locate the title + body editors and type the copy.

    The creator center uses contenteditable divs. We try a few common selectors
    and write the full copy (title + body) into the body editor when a separate
    title field isn't found.
    """
    # Title (optional): first line of copy if it looks like a title.
    lines = copy.split("\n", 1)
    title = lines[0] if lines else ""
    body = lines[1] if len(lines) > 1 else copy

    title_sel = 'div[contenteditable="true"][data-placeholder*="标题"], input[placeholder*="标题"]'
    try:
        await _human_type(page, title_sel, title)
    except PWTimeoutError:
        # No separate title field -> put everything in the body.
        body = copy

    body_sel = 'div[contenteditable="true"][data-placeholder*="正文"], div[contenteditable="true"]'
    await _human_type(page, body_sel, body)


async def _attach_product_card(page: Page, product: dict) -> None:
    """[PLACEHOLDER] 挂载商品卡片.

    小红书发布页的"添加商品/挂车"入口 DOM 会随版本变化，这里给出占位交互
    流程：点击「添加商品」-> 搜索商品 -> 选中 -> 确认。请按当前页面 DOM
    适配具体 selector。当前为占位实现，仅记录日志不阻断发布。
    """
    append_log(_state_ref(), "publish", "[placeholder] attach_product_card: searching " + str(product.get("title", "")))
    try:
        # Example placeholder flow (commented to avoid clicking wrong elements):
        # await page.click("text=添加商品", timeout=5000)
        # await _human_delay(0.8, 1.6)
        # await page.fill('input[placeholder*="搜索商品"]', product.get("title", ""))
        # await _human_delay(1.5, 2.5)
        # await page.click(".product-item >> nth=0", timeout=5000)
        # await page.click("text=确认", timeout=5000)
        append_log(_state_ref(), "publish", "[placeholder] attach_product_card: skipped (DOM adapters not configured)")
    except Exception as e:  # noqa: BLE001
        append_log(_state_ref(), "publish", f"[placeholder] attach_product_card failed (non-fatal): {e}")


@with_retry(name="click_publish", exceptions=(PWTimeoutError,))
async def _click_publish(page: Page) -> str:
    """Click the publish button and return the resulting post URL if visible."""
    # 小红书发布按钮文案常见为"发布"。
    candidates = ['button:has-text("发布")', 'div:has-text("发布发布")', '[role="button"]:has-text("发布")']
    clicked = False
    for sel in candidates:
        try:
            await page.click(sel, timeout=5000)
            clicked = True
            break
        except PWTimeoutError:
            continue
    if not clicked:
        raise PWTimeoutError("publish button not found")

    await _human_delay(3.0, 5.0)
    # Try to capture the published post URL from the address bar / a success link.
    post_url = page.url
    return post_url


# ---------------------------------------------------------------------------
# Node entry
# ---------------------------------------------------------------------------
async def _publish_async(state: AgentState) -> AgentState:
    global _state_ref
    _state_ref = lambda: state  # noqa: E731

    image_path = state.get("composite_path", "")
    copy = state.get("copy", "")
    product = state.get("selected", {})
    result: PublishResult = {"success": False, "log": [], "screenshots": []}

    if not image_path or not copy:
        result["error"] = "missing composite_path or copy in state"
        state["publish"] = result
        set_error(state, "publish", result["error"])
        return state

    async with async_playwright() as pw:
        browser, ctx, is_managed = await _connect_browser(pw)
        page = await ctx.new_page()
        try:
            await _open_creator(page)
            await _human_delay()

            append_log(state, "publish", f"uploading image: {image_path}")
            await _upload_image(page, image_path)
            await _human_delay()

            append_log(state, "publish", "typing copy into editor")
            await _type_copy(page, copy)
            await _human_delay()

            # [PLACEHOLDER] 商品挂车
            await _attach_product_card(page, product)
            await _human_delay()

            # Pre-publish screenshot for audit.
            try:
                shot = image_path.replace(".jpg", "_preflight.png").replace(".jpeg", "_preflight.png")
                await page.screenshot(path=shot, full_page=False)
                result["screenshots"].append(shot)
            except Exception:  # noqa: BLE001
                pass

            append_log(state, "publish", "clicking publish")
            post_url = await _click_publish(page)
            result["success"] = True
            result["post_url"] = post_url
            append_log(state, "publish", f"published: {post_url}")

            state["status"] = "done"
            state["current_node"] = "publish"
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)
            result["success"] = False
            set_error(state, "publish", str(e))
            try:
                err_shot = image_path.replace(".jpg", "_error.png")
                await page.screenshot(path=err_shot, full_page=False)
                result["screenshots"].append(err_shot)
            except Exception:  # noqa: BLE001
                pass
        finally:
            result["log"] = list(state.get("logs", []))
            state["publish"] = result
            await page.close()
            if is_managed:
                await ctx.close()
                await browser.close()
            else:
                # For CDP-attached browsers we only close the context we made,
                # never the fingerprint browser itself.
                pass
    return state


def publish_node(state: AgentState) -> AgentState:
    """同步入口: 跑 async Playwright 流程."""
    try:
        return asyncio.run(_publish_async(state))
    except Exception as e:  # noqa: BLE001
        set_error(state, "publish", f"playwright runtime error: {e}")
        return state


__all__ = ["publish_node"]
