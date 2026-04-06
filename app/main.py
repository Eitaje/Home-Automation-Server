import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.poller import start_scheduler, stop_scheduler
from app.redis_client import close_redis
from app.api import readings, control, ws

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()
    await close_redis()


app = FastAPI(
    title="Home Automation Server",
    description="Polls home automation devices, stores readings in Redis, exposes REST + WebSocket API.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(readings.router)
app.include_router(control.router)
app.include_router(ws.router)
