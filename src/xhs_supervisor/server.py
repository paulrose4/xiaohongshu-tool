"""FastAPI server with SSE streaming for the monitoring console.

GET /stream?prompt=...   -> Server-Sent Events stream of every node's log line,
                           compatible with Vercel AI SDK's EventSource usage.
GET /health              -> liveness probe.
POST /run                -> run the full pipeline, return final state JSON.

The SSE format mirrors what Vercel AI SDK expects for a custom stream:
    data: {"type":"log","node":"selector","message":"..."}\n\n
    data: {"type":"done","status":"done"}\n\n
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse

from .supervisor import run_pipeline

app = FastAPI(title="XHS Supervisor Monitor", version="0.1.0")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_pipeline(prompt: str, constraints: dict | None = None) -> AsyncGenerator[str, None]:
    """Run the pipeline, pushing each log line as an SSE event.

    We collect logs by injecting an on_log callback that drops lines into an
    asyncio.Queue, then drain the queue as events.
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def on_log(line: str) -> None:
        # called from the sync graph thread; schedule onto the loop
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(queue.put_nowait, line)
        except RuntimeError:
            queue.put_nowait(line)

    yield _sse({"type": "start", "prompt": prompt})

    # Run the (sync) pipeline in a worker thread so we can stream concurrently.
    def _worker():
        try:
            run_pipeline(prompt, constraints, on_log=on_log)
        except Exception as e:  # noqa: BLE001
            queue.put_nowait(f"[server] fatal: {e}")
        finally:
            queue.put_nowait(None)  # sentinel

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, _worker)

    while True:
        item = await queue.get()
        if item is None:
            break
        yield _sse({"type": "log", "message": item})

    await fut
    yield _sse({"type": "done"})


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/stream")
async def stream(prompt: str = Query(..., description="选品指令")):
    """SSE stream. Point Vercel AI SDK / EventSource at this endpoint."""
    return StreamingResponse(
        _stream_pipeline(prompt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering
        },
    )


@app.post("/run")
async def run(body: dict):
    prompt = body.get("prompt", "")
    constraints = body.get("constraints") or None
    final = await asyncio.get_running_loop().run_in_executor(
        None, lambda: run_pipeline(prompt, constraints)
    )
    # state contains non-serialisable BaseMessage objects; project to JSON-safe.
    safe = {
        k: v
        for k, v in final.items()
        if k not in {"messages"}
    }
    safe["logs"] = final.get("logs", [])
    return JSONResponse(safe)


if __name__ == "__main__":
    import uvicorn

    from .config import settings as _s

    uvicorn.run(app, host=_env_or("API_HOST", "0.0.0.0"), port=int(_env_or("API_PORT", "8000")))


def _env_or(name: str, default: str) -> str:
    import os

    return os.getenv(name, default)
