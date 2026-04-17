# Home Automation Server

A FastAPI server that polls home automation devices, stores readings in Redis, and exposes a REST + WebSocket API for a future UI.

## Features

- Polls the NodeMCU sensor node on a configurable interval
- Stores time-series data in Redis Streams (full history) and Redis Hashes (latest snapshot)
- REST API for reading device data and controlling the boiler
- WebSocket endpoint for real-time push to UI clients
- Extensible device abstraction — the irrigation Arduino is a stub ready to implement

## Architecture

```
Poller (APScheduler)
  └─ every N seconds → GET /curr_readings from each device
                     → write to Redis Stream (history)
                     → write to Redis Hash  (latest snapshot)
                     → broadcast to WebSocket subscribers

FastAPI
  ├─ GET  /devices
  ├─ GET  /devices/{id}/latest
  ├─ GET  /devices/{id}/history
  ├─ GET  /devices/{id}/sensor_status
  ├─ GET  /devices/nodemcu/boiler
  ├─ POST /devices/nodemcu/boiler
  └─ WS   /ws/live
```

Interactive API docs are available at `http://<host>:8000/docs` when the server is running.

## Project Structure

```
.
├── app/
│   ├── main.py            # FastAPI app + lifespan (start/stop poller)
│   ├── config.py          # Settings loaded from .env
│   ├── redis_client.py    # Redis connection singleton
│   ├── poller.py          # APScheduler polling loop + WebSocket broadcast
│   ├── devices/
│   │   ├── base.py        # Abstract BaseDevice interface
│   │   ├── nodemcu.py     # NodeMCU HTTP fetcher + boiler control
│   │   └── irrigation.py  # Stub for future irrigation Arduino
│   └── api/
│       ├── readings.py    # /devices endpoints (read)
│       ├── control.py     # /devices/nodemcu/boiler (write)
│       └── ws.py          # WebSocket /ws/live
├── .env.example           # Config template — copy to .env and fill in
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Configuration

Copy `.env.example` to `.env` and set your values:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `NODEMCU_IP` | — | NodeMCU IP address on your LAN |
| `NODEMCU_POLL_INTERVAL` | `10` | Seconds between polls |
| `NODEMCU_AUTH_USER` | _(empty)_ | HTTP Basic auth user (if required) |
| `NODEMCU_AUTH_PASSWORD` | _(empty)_ | HTTP Basic auth password |
| `STREAM_MAX_LEN` | `10000` | Max readings kept per device in Redis |

> **Note:** Do not put inline comments on value lines in `.env` — dotenv does not support them.

---

## Tests

Tests use [pytest](https://pytest.org/) with [fakeredis](https://github.com/cunla/fakeredis-py) so no running Redis instance is required.

### Install test dependencies

```bash
pip install pytest pytest-asyncio fakeredis
```

### Run

```bash
.venv/Scripts/pytest tests/ -v          # Windows
.venv/bin/pytest     tests/ -v          # macOS / Linux
```

### Test file

`tests/test_history_pipeline.py` covers the full data pipeline from Redis → API → UI-parseable response:

| Test | What it verifies |
|---|---|
| `test_history_returns_most_recent_entries` | `/history?count=N` returns the N most recent stream entries, not the oldest |
| `test_all_sensor_fields_survive_round_trip` | All 9 sensor fields stored in Redis are returned unchanged by the endpoint |
| `test_warmup_zeros_are_present_not_null` | ENS160 warm-up values (`"0"` for AQI/CO2/VOC) come back as `"0"`, not absent — so the UI renders 0 rather than a gap |
| `test_old_entries_missing_temperature_bmp580` | Entries written before `temperature_bmp580` was added don't crash the endpoint; the field is simply absent |
| `test_bulk_readings_past_timestamps_do_not_crash` | Offline buffer sync with timestamps older than the stream tip returns a non-500 response (past IDs are skipped gracefully) |
| `test_aggregation_marks_empty_window_as_missing` | Aggregator writes `missing=1` and empty strings for all fields when no raw data is available in the window |
| `test_aggregation_with_data_sets_missing_zero` | Aggregator writes `missing=0` and numeric averages when raw data is present |

---

## Local Development (no Docker)

This runs the server directly on your machine using the `.venv` virtual environment. Redis still runs in Docker.

### Prerequisites

- Python 3.11+
- Docker Desktop (for Redis only)

### Steps

**1. Create and activate the virtual environment**

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Configure**

```bash
cp .env.example .env
# Edit .env — set NODEMCU_IP and keep REDIS_URL=redis://localhost:6379
```

**4. Start Redis**

```bash
docker run -d -p 6379:6379 --name redis-local redis:7-alpine
```

To stop Redis later: `docker stop redis-local`

**5. Run the server**

From VSCode: open the Run panel and select **Run server**, then press **F5**.

From the terminal:

```bash
uvicorn app.main:app --reload --port 8000
```

The server will be available at `http://localhost:8000`.
API docs: `http://localhost:8000/docs`

---

## Local Development (full Docker Compose)

Runs both the server and Redis in containers — identical to the production setup.

### Prerequisites

- Docker Desktop

### Steps

**1. Configure**

```bash
cp .env.example .env
# Edit .env — set NODEMCU_IP
# Keep REDIS_URL=redis://redis:6379  (container name, not localhost)
```

**2. Build and start**

```bash
docker compose up --build
```

Use `-d` to run in the background: `docker compose up --build -d`

**3. Stop**

```bash
docker compose down
```

To also delete the Redis data volume:

```bash
docker compose down -v
```

---

## Deployment on TrueNAS SCALE 25.10 (Goldeye)

The preferred workflow is to build the image locally and push it to TrueNAS's built-in image registry. No code or git cloning needed on the NAS — only the image and a Redis container run there.

### Prerequisites

- TrueNAS SCALE 25.10 with SSH enabled
- Docker Desktop on your dev machine
- The NodeMCU must be reachable from the TrueNAS host IP
- A dataset for Redis persistence, e.g. `/mnt/mainpool/homeauto/redis-data`
  (see the symlink note below regarding pool names with spaces)

### Pool name with spaces

If your pool name contains a space (e.g. `Main Pool`), create a permanent symlink via a Post Init Script in TrueNAS:

`System → Advanced → Init/Shutdown Scripts → Add`
- Type: `Command`
- Command: `ln -s "/mnt/Main Pool" /mnt/mainpool`
- When: `Post Init`

Then use `/mnt/mainpool/...` everywhere.

---

The image is hosted on Docker Hub: [`eitaje/homeauto-server-python`](https://hub.docker.com/r/eitaje/homeauto-server-python)

---

### Step 1 — Build and push the image (dev machine)

Run these from the project folder whenever you have code changes:

```bash
docker build -t eitaje/homeauto-server-python:latest .
docker push eitaje/homeauto-server-python:latest
```

---

### Step 2 — Create the Redis data directory

SSH into TrueNAS and create the directory (or use the TrueNAS Datasets UI):

```bash
mkdir -p /mnt/mainpool/homeauto/redis-data
```

---

### Step 3 — Copy the compose file to TrueNAS

From your dev machine:

```bash
scp "docker-compose.truenas.yml" root@<truenas-ip>:/mnt/mainpool/homeauto/
scp ".env.example" root@<truenas-ip>:/mnt/mainpool/homeauto/.env
```

---

### Step 4 — Configure and start

SSH into TrueNAS:

```bash
ssh root@<truenas-ip>
cd /mnt/mainpool/homeauto

# Edit .env — set NODEMCU_IP at minimum
nano .env

# Start both containers
docker compose -f docker-compose.truenas.yml up -d
```

Both Redis and the server start together. Redis data is persisted to `/mnt/mainpool/homeauto/redis-data` on your pool.

**Redis persistence:** Two mechanisms are active simultaneously:
- `appendonlydir/` — AOF (append-only file): logs every write, near-zero data loss on crash
- `dump.rdb` — RDB snapshot: periodic full dump, extra safety net

On restart, Redis replays the AOF log to restore the full dataset in memory before accepting connections. All historical readings survive container destruction and NAS reboots.

To verify persistence is working:
```bash
docker exec redis redis-cli XLEN device:nodemcu:readings  # note the count
docker compose -f docker-compose.truenas.yml down
docker compose -f docker-compose.truenas.yml up -d
docker exec redis redis-cli XLEN device:nodemcu:readings  # should match
```

> **Network note:** If the NodeMCU is not reachable from inside the container, uncomment `network_mode: host` in `docker-compose.truenas.yml` and change `REDIS_URL` to `redis://localhost:6379`.

The API will be available at `http://<truenas-ip>:8000`.
API docs: `http://<truenas-ip>:8000/docs`

---

### Updating

```bash
# Dev machine — rebuild and push
docker build -t eitaje/homeauto-server-python:latest .
docker push eitaje/homeauto-server-python:latest

# TrueNAS — pull and restart (Redis is untouched)
ssh root@<truenas-ip>
cd /mnt/mainpool/homeauto
docker compose -f docker-compose.truenas.yml pull server
docker compose -f docker-compose.truenas.yml up -d server
```
