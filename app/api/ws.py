import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.poller import subscribe, unsubscribe

router = APIRouter()

_PING_INTERVAL = 25  # seconds — keeps the connection alive


@router.websocket("/ws/live")
async def live_feed(ws: WebSocket):
    await ws.accept()
    q = subscribe()
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=_PING_INTERVAL)
                await ws.send_text(json.dumps(msg))
            except asyncio.TimeoutError:
                # Send a keepalive ping so idle connections don't drop
                await ws.send_text(json.dumps({"type": "ping"}))
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        unsubscribe(q)
