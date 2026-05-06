import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket('/ws/downloads')
async def download_progress_ws(websocket: WebSocket):
    await websocket.accept()
    queue = websocket.app.state.progress_queue
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass