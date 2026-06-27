"""Node 2: 视觉智能体 (Visual Processor).

Input:  state["image_url"]  (商家白底图 URL)
Logic:  1. Download the white-bg product image.
        2. Remove background via RMBG-1.4 (local) or ComfyUI API.
        3. Composite the cutout onto a "独居女孩温馨出租屋" style background.
        4. Overlay a big-text banner (e.g. "几十块钱的快乐") near the top.
Output: state["composite_path"]  (本地合成图绝对路径)

Robustness: each external step (download, model call, ComfyUI) is wrapped in
@with_retry. If torch/transformers are absent we fall back to a simple
alpha-threshold cutout so the pipeline still produces an image.
"""
from __future__ import annotations

import io
import logging
import os
import uuid
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..config import settings
from ..retry import with_retry
from ..state import AgentState, append_log, set_error

_log = logging.getLogger("xhs.visual")

OUTPUT_DIR = settings.project_root / "assets" / "output"


def _ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@with_retry(name="download_image")
async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


# ---------------------------------------------------------------------------
# Background removal backends
# ---------------------------------------------------------------------------
_RMBG_MODEL = None  # lazy-loaded singleton


def _load_rmbg():
    """Lazy-load the RMBG-1.4 model. Cached on the module to avoid reloads."""
    global _RMBG_MODEL
    if _RMBG_MODEL is not None:
        return _RMBG_MODEL
    from transformers import AutoModelForImageSegmentation  # type: ignore
    import torch  # type: ignore

    model = AutoModelForImageSegmentation.from_pretrained(
        settings.visual.rmbg_model_id, trust_remote_code=True
    )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()
    _RMBG_MODEL = (model, device)
    return _RMBG_MODEL


def _rmbg_remove(image: Image.Image) -> Image.Image:
    """Run RMBG-1.4 and return an RGBA image with alpha mask."""
    import torch  # type: ignore
    from torchvision import transforms  # type: ignore

    model, device = _load_rmbg()
    transform = transforms.Compose(
        [
            transforms.Resize((1024, 1024)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]
    )
    inp = transform(image.convert("RGB")).unsqueeze(0).to(device)
    with torch.no_grad():
        preds = model(inp)[-1].sigmoid().cpu()
    mask = preds[0].squeeze().numpy()
    mask = (mask * 255).astype(np.uint8)
    mask_img = Image.fromarray(mask).resize(image.size, Image.LANCZOS)

    rgba = image.convert("RGBA")
    rgba.putalpha(mask_img)
    return rgba


@with_retry(name="comfyui_remove", exceptions=(httpx.HTTPError, TimeoutError))
async def _comfyui_remove(image_bytes: bytes) -> bytes:
    """Call a local ComfyUI workflow to remove the background.

    This posts the image to ComfyUI's /upload/image, queues a basic
    RMBG/rembg workflow, and polls /history until the result PNG is ready.
    The workflow JSON is intentionally minimal; point COMFYUI_WORKFLOW at your
    saved API-format workflow for production use.
    """
    host = settings.visual.comfyui_host
    port = settings.visual.comfyui_port
    base = f"http://{host}:{port}"

    async with httpx.AsyncClient(timeout=60) as client:
        # 1. upload
        files = {"image": ("product.png", image_bytes, "image/png")}
        up = await client.post(f"{base}/upload/image", files=files)
        up.raise_for_status()
        img_name = up.json().get("name")

        # 2. queue prompt (minimal placeholder workflow)
        workflow = {
            "3": {"class_type": "LoadImage", "inputs": {"image": img_name}},
            "4": {"class_type": "ImageRemoveBackground", "inputs": {"image": ["3", 0]}},
            "5": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": "cutout"}},
        }
        q = await client.post(f"{base}/prompt", json={"prompt": workflow})
        q.raise_for_status()
        prompt_id = q.json().get("prompt_id")

        # 3. poll history
        for _ in range(60):
            h = await client.get(f"{base}/history/{prompt_id}")
            h.raise_for_status()
            hist = h.json().get(prompt_id)
            if hist and hist.get("outputs"):
                for node_out in hist["outputs"].values():
                    if "images" in node_out:
                        fname = node_out["images"][0]["filename"]
                        sub = node_out["images"][0].get("subfolder", "")
                        img_resp = await client.get(
                            f"{base}/view", params={"filename": fname, "subfolder": sub, "type": "output"}
                        )
                        img_resp.raise_for_status()
                        return img_resp.content
            import asyncio

            await asyncio.sleep(1.0)
    raise TimeoutError("ComfyUI result not ready in time")


def _fallback_cutout(image: Image.Image) -> Image.Image:
    """Naive cutout when no ML backend is available.

    Treats near-white pixels as background and makes them transparent. Good
    enough for white-bg product shots and keeps the pipeline runnable.
    """
    rgba = image.convert("RGBA")
    arr = np.array(rgba.convert("RGB")).astype(int)
    # white-ish => background
    is_bg = (arr[:, :, 0] > 235) & (arr[:, :, 1] > 235) & (arr[:, :, 2] > 235)
    alpha = np.where(is_bg, 0, 255).astype(np.uint8)
    rgba.putalpha(Image.fromarray(alpha, mode="L"))
    return rgba


async def _remove_background(image: Image.Image, raw_bytes: bytes) -> Image.Image:
    backend = settings.visual.backend.lower()
    if backend == "comfyui":
        try:
            out_bytes = await _comfyui_remove(raw_bytes)
            return Image.open(io.BytesIO(out_bytes)).convert("RGBA")
        except Exception as e:  # noqa: BLE001
            append_log(None, "visual", f"comfyui failed, falling back: {e}") if False else None
            _log.warning("comfyui failed, falling back to naive: %s", e)
            return _fallback_cutout(image)
    if backend == "rmbg":
        try:
            return _rmbg_remove(image)
        except Exception as e:  # noqa: BLE001
            _log.warning("rmbg failed, falling back to naive: %s", e)
            return _fallback_cutout(image)
    return _fallback_cutout(image)


# ---------------------------------------------------------------------------
# Compositing
# ---------------------------------------------------------------------------
def _load_bg() -> Image.Image:
    bg_path = settings.project_root / settings.visual.composite_bg_path
    if not bg_path.exists():
        # Procedural fallback: a warm gradient so the pipeline always works.
        bg = Image.new("RGB", (1080, 1350), (245, 235, 220))
        draw = ImageDraw.Draw(bg)
        for y in range(bg.height):
            t = y / bg.height
            r = int(245 - t * 30)
            g = int(230 - t * 35)
            b = int(220 - t * 45)
            draw.line([(0, y), (bg.width, y)], fill=(r, g, b))
        return bg
    return Image.open(bg_path).convert("RGB")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc",      # 微软雅黑 Bold (Windows)
        "C:/Windows/Fonts/simhei.ttf",      # 黑体
        "/System/Library/Fonts/PingFang.ttc",  # macOS
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def _composite(cutout: Image.Image, bg: Image.Image) -> Image.Image:
    """Center the cutout on the bg, scaled to ~70% of bg width."""
    target_w = int(bg.width * 0.7)
    ratio = target_w / cutout.width
    target_h = int(cutout.height * ratio)
    cutout_resized = cutout.resize((target_w, target_h), Image.LANCZOS)

    canvas = bg.convert("RGBA").copy()
    # paste slightly below vertical center to leave room for the banner.
    x = (canvas.width - target_w) // 2
    y = int(canvas.height * 0.30)
    canvas.alpha_composite(cutout_resized, (x, y))

    # Big-text banner near the top, centered.
    draw = ImageDraw.Draw(canvas)
    text = settings.visual.big_text
    font = _font(settings.visual.big_text_font_size)
    # measure
    try:
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=4)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:  # very old Pillow
        tw, th = font.getsize(text)  # type: ignore[attr-defined]
    tx = (canvas.width - tw) // 2
    ty = int(canvas.height * 0.06)
    draw.text(
        (tx, ty),
        text,
        font=font,
        fill=settings.visual.big_text_color,
        stroke_width=4,
        stroke_fill=settings.visual.big_text_stroke_color,
    )
    return canvas.convert("RGB")


# ---------------------------------------------------------------------------
# Node entry
# ---------------------------------------------------------------------------
async def _visual_async(state: AgentState) -> AgentState:
    url = state.get("image_url", "")
    if not url:
        set_error(state, "visual", "no image_url in state")
        return state

    append_log(state, "visual", f"downloading white-bg image: {url}")
    raw = await _download(url)
    src_img = Image.open(io.BytesIO(raw)).convert("RGB")

    append_log(state, "visual", f"removing background via {settings.visual.backend}")
    cutout = await _remove_background(src_img, raw)

    cutout_path = OUTPUT_DIR / f"cutout_{uuid.uuid4().hex[:8]}.png"
    cutout.save(cutout_path)
    state["cutout_path"] = str(cutout_path.resolve())

    append_log(state, "visual", "compositing onto cozy-room background + big text banner")
    bg = _load_bg()
    final_img = _composite(cutout, bg)

    composite_path = OUTPUT_DIR / f"composite_{uuid.uuid4().hex[:8]}.jpg"
    final_img.save(composite_path, quality=92)
    state["composite_path"] = str(composite_path.resolve())
    state["status"] = "copy"
    state["current_node"] = "visual"
    append_log(state, "visual", f"composite saved: {state['composite_path']}")
    return state


def visual_node(state: AgentState) -> AgentState:
    """同步入口 (LangGraph 节点): 内部跑 async 逻辑."""
    _ensure_dirs()
    import asyncio

    try:
        return asyncio.run(_visual_async(state))
    except Exception as e:  # noqa: BLE001
        set_error(state, "visual", str(e))
        return state


__all__ = ["visual_node"]
