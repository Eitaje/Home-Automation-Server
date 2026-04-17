from typing import Literal
from fastapi import APIRouter, HTTPException, Query

from app.redis_client import get_redis
from app.config import settings

router = APIRouter()

KNOWN_DEVICES = ["nodemcu", "irrigation"]


@router.get("/devices")
async def list_devices():
    r = get_redis()
    result = []
    for device_id in KNOWN_DEVICES:
        online_raw = await r.get(f"device:{device_id}:online")
        result.append({"id": device_id, "online": online_raw == "1"})
    return result


@router.get("/devices/{device_id}/latest")
async def get_latest(device_id: str):
    if device_id not in KNOWN_DEVICES:
        raise HTTPException(status_code=404, detail="Device not found")
    r = get_redis()
    data = await r.hgetall(f"device:{device_id}:latest")
    if not data:
        raise HTTPException(status_code=404, detail="No data available yet")
    return data


@router.get("/devices/{device_id}/history")
async def get_history(
    device_id: str,
    count: int = Query(default=100, ge=1, le=2000),
    start: str = Query(default="-", description="Redis Stream ID or '-' for oldest"),
    end: str = Query(default="+", description="Redis Stream ID or '+' for newest"),
):
    if device_id not in KNOWN_DEVICES:
        raise HTTPException(status_code=404, detail="Device not found")
    r = get_redis()
    # XREVRANGE returns newest-first; we reverse so the result is oldest→newest for charts
    entries = await r.xrevrange(
        f"device:{device_id}:readings", max=end, min=start, count=count
    )
    return [{"id": entry_id, **fields} for entry_id, fields in reversed(entries)]


@router.post("/devices/{device_id}/bulk_readings")
async def post_bulk_readings(device_id: str, readings: list[dict]):
    """Accept an array of timestamped readings from the NodeMCU offline buffer."""
    if device_id not in KNOWN_DEVICES:
        raise HTTPException(status_code=404, detail="Device not found")
    r = get_redis()
    stored = 0
    skipped = 0
    for reading in readings:
        ts = reading.get("timestamp")
        if ts is None:
            continue
        ts_ms = int(float(ts)) * 1000
        payload = {k: str(v) for k, v in reading.items() if k != "timestamp"}
        payload["_ts"]      = str(ts_ms)
        payload["_offline"] = "1"   # mark as backfilled from offline buffer
        try:
            await r.xadd(
                f"device:{device_id}:readings",
                payload,
                id=f"{ts_ms}-0",
                maxlen=settings.stream_max_len,
                approximate=True,
            )
            stored += 1
        except Exception:
            # Redis rejects IDs <= the stream's current tip (e.g. device rebooted
            # while online readings were still being written, leaving the offline
            # buffer with timestamps older than the live stream).  Skip these
            # rather than crashing — the live data already covers that window.
            skipped += 1
    return {"stored": stored, "skipped": skipped}


@router.get("/devices/{device_id}/aggregations")
async def get_aggregations(
    device_id: str,
    resolution: Literal["15min", "1h", "1d", "1w"] = Query(default="1h"),
    count: int = Query(default=48, ge=1, le=2880),
):
    if device_id not in KNOWN_DEVICES:
        raise HTTPException(status_code=404, detail="Device not found")
    r = get_redis()
    entries = await r.xrevrange(
        f"device:{device_id}:agg:{resolution}", max="+", min="-", count=count
    )
    return [{"id": entry_id, **fields} for entry_id, fields in reversed(entries)]


@router.get("/devices/{device_id}/sensor_status")
async def get_sensor_status(device_id: str):
    if device_id not in KNOWN_DEVICES:
        raise HTTPException(status_code=404, detail="Device not found")
    r = get_redis()
    data = await r.hgetall(f"device:{device_id}:sensor_status")
    return data
