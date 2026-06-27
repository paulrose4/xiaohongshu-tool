import sys
import json
import asyncio
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# Add project root to path so we can import the pipeline
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhs_supervisor.supervisor import run_pipeline  # noqa: E402

router = APIRouter()

tasks = {}
logs = {}


@router.get("/status")
async def get_status():
    return {"tasks": tasks, "logs": logs}


@router.post("/start")
async def start_task(data: dict):
    instruction = data.get("instruction", "测试选品")
    task_id = len(tasks) + 1
    tasks[task_id] = {
        "id": task_id,
        "instruction": instruction,
        "status": "running",
        "progress": 0,
    }
    logs[task_id] = []

    def on_log(line: str) -> None:
        logs[task_id].append(line)

    # Run pipeline in a thread to not block
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: run_pipeline(instruction, {}, on_log=on_log))
    tasks[task_id]["status"] = "done"
    tasks[task_id]["progress"] = 100
    return {"task_id": task_id, "status": "done"}


@router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: int):
    await websocket.accept()
    try:
        while True:
            if task_id in logs:
                await websocket.send_json({"type": "logs", "logs": logs[task_id]})
            await asyncio.sleep(1)
            if task_id in tasks and tasks[task_id]["status"] == "done":
                await websocket.send_json({"type": "complete", "task_id": task_id})
                break
    except WebSocketDisconnect:
        pass


@router.get("/stream")
async def stream_logs():
    from fastapi.responses import StreamingResponse
    async def event_generator():
        while True:
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            await asyncio.sleep(5)
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/config")
async def get_config():
    from xhs_supervisor.config import settings
    return {
        "selection": {
            "price_min": settings.selection.price_min,
            "price_max": settings.selection.price_max,
            "commission_rate_min": settings.selection.commission_rate_min,
            "sales_30d_min": settings.selection.sales_30d_min,
        },
        "visual": {
            "backend": settings.visual.backend,
            "big_text": settings.visual.big_text,
        },
        "copywriter": {
            "max_chars": 250,
            "temperature": 0.9,
            "provider": settings.llm.provider,
            "model": settings.llm.model,
        },
    }
