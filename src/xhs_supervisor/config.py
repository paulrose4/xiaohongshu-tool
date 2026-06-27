"""Centralized configuration loading.

Loads secrets/overrides from .env (via python-dotenv) and structural defaults
from config.toml. Exposes a single typed Settings object used across nodes.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # dotenv optional at import time
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"


def _load_toml() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


def _env(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name)
    return val if val is not None else default


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


@dataclass
class SelectionConfig:
    price_min: float = 19.9
    price_max: float = 69.9
    commission_rate_min: float = 0.20
    sales_30d_min: int = 5000
    top_k: int = 5


@dataclass
class VisualConfig:
    backend: str = "rmbg"
    rmbg_model_id: str = "briaai/RMBG-1.4"
    comfyui_host: str = "127.0.0.1"
    comfyui_port: int = 8188
    composite_bg_path: str = "assets/backgrounds/cozy_room.jpg"
    big_text: str = "几十块钱的快乐"
    big_text_font_size: int = 96
    big_text_color: str = "#FFFFFF"
    big_text_stroke_color: str = "#000000"


@dataclass
class CopywriterConfig:
    max_chars: int = 250
    temperature: float = 0.9


@dataclass
class RpaConfig:
    fingerprint_browser_cdp_port: int = 9222
    xhs_creator_url: str = "https://creator.xiaohongshu.com/publish/publish"
    min_delay: float = 1.5
    max_delay: float = 4.5
    headless: bool = False
    human_like_scroll: bool = True


@dataclass
class ContextConfig:
    max_chars: int = 12000
    max_messages: int = 20


@dataclass
class LLMConfig:
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = ""
    model: str = ""


@dataclass
class RetryConfig:
    max_retries: int = 3
    backoff: float = 2.0


@dataclass
class Settings:
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    visual: VisualConfig = field(default_factory=VisualConfig)
    copywriter: CopywriterConfig = field(default_factory=CopywriterConfig)
    rpa: RpaConfig = field(default_factory=RpaConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    pipeline: list[str] = field(default_factory=lambda: ["select", "visual", "copy", "publish"])
    use_mock_api: bool = True
    project_root: Path = PROJECT_ROOT


def _build_llm() -> LLMConfig:
    provider = (_env("LLM_PROVIDER", "deepseek") or "deepseek").lower()
    if provider == "glm":
        return LLMConfig(
            provider="glm",
            api_key=_env("GLM_API_KEY", "") or "",
            base_url=_env("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4") or "",
            model=_env("GLM_MODEL", "glm-5.2") or "glm-5.2",
        )
    return LLMConfig(
        provider="deepseek",
        api_key=_env("DEEPSEEK_API_KEY", "") or "",
        base_url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1") or "",
        model=_env("DEEPSEEK_MODEL", "deepseek-v4-pro") or "deepseek-v4-pro",
    )


def load_settings() -> Settings:
    raw = _load_toml()
    sel = raw.get("selection", {})
    vis = raw.get("visual", {})
    cp = raw.get("copywriter", {})
    rpa = raw.get("rpa", {})
    ctx = raw.get("context", {})
    sup = raw.get("supervisor", {})

    settings = Settings(
        selection=SelectionConfig(
            price_min=float(sel.get("price_min", 19.9)),
            price_max=float(sel.get("price_max", 69.9)),
            commission_rate_min=float(sel.get("commission_rate_min", 0.20)),
            sales_30d_min=int(sel.get("sales_30d_min", 5000)),
            top_k=int(sel.get("top_k", 5)),
        ),
        visual=VisualConfig(
            backend=_env("VISUAL_BACKEND", vis.get("backend", "rmbg")) or "rmbg",
            rmbg_model_id=_env("RMBG_MODEL_ID", vis.get("rmbg_model_id", "briaai/RMBG-1.4")) or "briaai/RMBG-1.4",
            comfyui_host=_env("COMFYUI_HOST", "127.0.0.1") or "127.0.0.1",
            comfyui_port=_env_int("COMFYUI_PORT", int(vis.get("comfyui_port", 8188))),
            composite_bg_path=_env("COMPOSITE_BG_PATH", vis.get("composite_bg_path", "assets/backgrounds/cozy_room.jpg")) or "",
            big_text=_env("BIG_TEXT", vis.get("big_text", "几十块钱的快乐")) or "几十块钱的快乐",
            big_text_font_size=int(vis.get("big_text_font_size", 96)),
            big_text_color=vis.get("big_text_color", "#FFFFFF"),
            big_text_stroke_color=vis.get("big_text_stroke_color", "#000000"),
        ),
        copywriter=CopywriterConfig(
            max_chars=int(cp.get("max_chars", 250)),
            temperature=float(cp.get("temperature", 0.9)),
        ),
        rpa=RpaConfig(
            fingerprint_browser_cdp_port=_env_int("FINGERPRINT_BROWSER_CDP_PORT", int(rpa.get("fingerprint_browser_cdp_port", 9222))),
            xhs_creator_url=_env("XHS_CREATOR_URL", rpa.get("xhs_creator_url", "https://creator.xiaohongshu.com/publish/publish")) or "",
            min_delay=_env_float("RPA_MIN_DELAY", float(rpa.get("min_delay", 1.5))),
            max_delay=_env_float("RPA_MAX_DELAY", float(rpa.get("max_delay", 4.5))),
            headless=_env_bool("RPA_HEADLESS", bool(rpa.get("headless", False))),
            human_like_scroll=bool(rpa.get("human_like_scroll", True)),
        ),
        context=ContextConfig(
            max_chars=_env_int("MAX_CONTEXT_CHARS", int(ctx.get("max_chars", 12000))),
            max_messages=_env_int("MAX_MESSAGES", int(ctx.get("max_messages", 20))),
        ),
        retry=RetryConfig(
            max_retries=_env_int("MAX_RETRIES", 3),
            backoff=_env_float("RETRY_BACKOFF", 2.0),
        ),
        llm=_build_llm(),
        pipeline=list(sup.get("pipeline", ["select", "visual", "copy", "publish"])),
        use_mock_api=_env_bool("USE_MOCK_API", True),
    )
    return settings


# Module-level singleton for convenience import
settings = load_settings()
