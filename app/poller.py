import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.redis_client import get_redis
from app.devices.nodemcu import NodeMCUDevice
from app.aggregator import run_15min, run_1h, run_1d, run_1w

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_nodemcu = NodeMCUDevice()

# WebSocket subscribers: list of asyncio Queues
_subscribers: list[asyncio.Queue] = []


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=20)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    try:
        _subscribers.remove(q)
    except ValueError:
        pass


async def _broadcast(device_id: str, data: dict[str, Any]) -> None:
    msg = {"type": "reading", "device_id": device_id, "data": data}
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass  # slow consumer — drop rather than block


async def _store(device_id: str, readings: dict[str, Any]) -> None:
    r = get_redis()
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)  # epoch ms
    payload = {**readings, "_ts": str(ts)}

    await r.hset(f"device:{device_id}:latest", mapping=payload)
    await r.xadd(
        f"device:{device_id}:readings",
        payload,
        maxlen=settings.stream_max_len,
        approximate=True,
    )


async def _poll_nodemcu() -> None:
    r = get_redis()

    readings = await _nodemcu.fetch_readings()
    if readings is None:
        logger.warning("NodeMCU poll failed — device unreachable")
        await r.set("device:nodemcu:online", "0")
        return

    await r.set("device:nodemcu:online", "1")
    await _store("nodemcu", readings)
    await _broadcast("nodemcu", readings)

    status = await _nodemcu.fetch_sensor_status()
    if status:
        await r.hset("device:nodemcu:sensor_status", mapping=status)


def start_scheduler() -> None:
    _scheduler.add_job(
        _poll_nodemcu,
        trigger="interval",
        seconds=settings.nodemcu_poll_interval,
        id="poll_nodemcu",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(run_15min, trigger="cron", minute="0,15,30,45",
                       id="agg_15min", max_instances=1, coalesce=True)
    _scheduler.add_job(run_1h,    trigger="cron", minute=0,
                       id="agg_1h",    max_instances=1, coalesce=True)
    _scheduler.add_job(run_1d,    trigger="cron", hour=0, minute=5,
                       id="agg_1d",    max_instances=1, coalesce=True)
    _scheduler.add_job(run_1w,    trigger="cron", day_of_week=0, hour=0, minute=10,
                       id="agg_1w",    max_instances=1, coalesce=True)
    _scheduler.start()
    logger.info("Poller started — NodeMCU every %ds", settings.nodemcu_poll_interval)


def stop_scheduler() -> None:
    _scheduler.shutdown(wait=False)
    logger.info("Poller stopped")
