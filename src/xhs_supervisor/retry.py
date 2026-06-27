"""Retry utilities built on tenacity with exponential backoff.

Every node wraps its network/IO calls with @with_retry so transient failures
(API rate limits, ComfyUI hiccups, Playwright navigation flakes) are retried
with exponential backoff instead of aborting the whole pipeline.
"""
from __future__ import annotations

import inspect
import logging
from functools import wraps
from typing import Callable, TypeVar

from tenacity import (
    AsyncRetrying,
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T")
_log = logging.getLogger("xhs.retry")


def _build_kwargs(max_retries: int, backoff: float, exceptions) -> dict:
    return dict(
        reraise=True,
        stop=stop_after_attempt(max_retries + 1),
        wait=wait_exponential(multiplier=backoff, min=backoff, max=backoff * 10),
        retry=retry_if_exception_type(exceptions),
        before_sleep=before_sleep_log(_log, logging.WARNING),
    )


def with_retry(
    *,
    max_retries: int | None = None,
    backoff: float | None = None,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    name: str = "call",
):
    """Decorator: exponential backoff retry over configurable exceptions.

    Defaults are pulled from Settings.retry when not overridden. Supports both
    sync and async callables.
    """
    from .config import settings

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def async_wrapper(*args, **kwargs):
                mr = max_retries if max_retries is not None else settings.retry.max_retries
                bf = backoff if backoff is not None else settings.retry.backoff
                async for attempt in AsyncRetrying(**_build_kwargs(mr, bf, exceptions)):
                    with attempt:
                        return await fn(*args, **kwargs)

            return async_wrapper  # type: ignore

        @wraps(fn)
        def sync_wrapper(*args, **kwargs):
            mr = max_retries if max_retries is not None else settings.retry.max_retries
            bf = backoff if backoff is not None else settings.retry.backoff
            for attempt in Retrying(**_build_kwargs(mr, bf, exceptions)):
                with attempt:
                    return fn(*args, **kwargs)

        return sync_wrapper

    return decorator


__all__ = ["with_retry"]
