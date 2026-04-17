import logging
from datetime import datetime, timezone

from app.redis_client import get_redis

logger = logging.getLogger(__name__)

NUMERIC_FIELDS = [
    "water_temperature", "temperature", "temperature_bmp580",
    "humidity", "light", "CO2", "VOC", "AQI", "pressure",
]

RESOLUTIONS: dict[str, dict] = {
    "15min": {"seconds": 900,    "maxlen": 2880},  # 30 days
    "1h":    {"seconds": 3600,   "maxlen": 720},   # 30 days
    "1d":    {"seconds": 86400,  "maxlen": 365},   # 1 year
    "1w":    {"seconds": 604800, "maxlen": 104},   # 2 years
}


async def _aggregate(device_id: str, resolution: str) -> None:
    cfg = RESOLUTIONS[resolution]
    window_ms = cfg["seconds"] * 1000
    r = get_redis()

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - window_ms

    entries = await r.xrange(
        f"device:{device_id}:readings",
        min=str(start_ms),
        max=str(now_ms),
    )

    if not entries:
        payload: dict[str, str] = {f: "" for f in NUMERIC_FIELDS}
        payload["missing"] = "1"
        logger.warning(
            "Aggregation %s/%s: no raw data in window — marking missing",
            device_id, resolution,
        )
    else:
        accum: dict[str, list[float]] = {f: [] for f in NUMERIC_FIELDS}
        for _, fields in entries:
            for field in NUMERIC_FIELDS:
                v = fields.get(field)
                if v is not None and v != "":
                    try:
                        accum[field].append(float(v))
                    except ValueError:
                        pass
        payload = {}
        for field in NUMERIC_FIELDS:
            vals = accum[field]
            payload[field] = f"{sum(vals) / len(vals):.2f}" if vals else ""
        payload["missing"] = "0"

    payload["_ts"] = str(now_ms)

    await r.xadd(
        f"device:{device_id}:agg:{resolution}",
        payload,
        maxlen=cfg["maxlen"],
        approximate=True,
    )
    logger.info(
        "Aggregation %s/%s stored — %d raw points, missing=%s",
        device_id, resolution, len(entries), payload["missing"],
    )


async def run_15min(device_id: str = "nodemcu") -> None:
    await _aggregate(device_id, "15min")

async def run_1h(device_id: str = "nodemcu") -> None:
    await _aggregate(device_id, "1h")

async def run_1d(device_id: str = "nodemcu") -> None:
    await _aggregate(device_id, "1d")

async def run_1w(device_id: str = "nodemcu") -> None:
    await _aggregate(device_id, "1w")
