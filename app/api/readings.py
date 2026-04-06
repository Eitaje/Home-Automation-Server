from fastapi import APIRouter, HTTPException, Query

from app.redis_client import get_redis

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
    count: int = Query(default=100, ge=1, le=1000),
    start: str = Query(default="-", description="Redis Stream ID or '-' for oldest"),
    end: str = Query(default="+", description="Redis Stream ID or '+' for newest"),
):
    if device_id not in KNOWN_DEVICES:
        raise HTTPException(status_code=404, detail="Device not found")
    r = get_redis()
    entries = await r.xrange(
        f"device:{device_id}:readings", min=start, max=end, count=count
    )
    return [{"id": entry_id, **fields} for entry_id, fields in entries]


@router.get("/devices/{device_id}/sensor_status")
async def get_sensor_status(device_id: str):
    if device_id not in KNOWN_DEVICES:
        raise HTTPException(status_code=404, detail="Device not found")
    r = get_redis()
    data = await r.hgetall(f"device:{device_id}:sensor_status")
    return data
