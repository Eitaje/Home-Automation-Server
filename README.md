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

## Deployment on TrueNAS SCALE

TrueNAS SCALE supports Docker Compose via SSH. Redis data is persisted in a named volume on your pool.

### Prerequisites

- TrueNAS SCALE with SSH enabled
- A dataset on your pool for the project files (e.g. `/mnt/pool/homeauto`)
- The NodeMCU must be reachable from the TrueNAS host IP

### Steps

**1. Copy project files to TrueNAS**

From your development machine:

```bash
scp -r "home automation server/" root@<truenas-ip>:/mnt/pool/homeauto
```

Or use a Git repository:

```bash
# On TrueNAS (via SSH)
git clone <your-repo-url> /mnt/pool/homeauto
```

**2. SSH into TrueNAS**

```bash
ssh root@<truenas-ip>
cd /mnt/pool/homeauto
```

**3. Configure**

```bash
cp .env.example .env
nano .env
# Set NODEMCU_IP to the NodeMCU's LAN IP
# Set REDIS_URL=redis://redis:6379
```

**4. Build and start**

```bash
docker compose up -d --build
```

**5. Verify**

```bash
docker compose ps        # both services should be "running"
docker compose logs -f   # watch live logs
```

The API will be available at `http://<truenas-ip>:8000`.

### Network note

By default Docker uses a bridged network. If the NodeMCU is not reachable from within the container (common on some TrueNAS network configurations), switch to host networking:

In `docker-compose.yml`, under the `server` service:
- Remove the `ports:` block
- Uncomment `# network_mode: host`

The server will then use port 8000 on the TrueNAS host IP directly.

### Auto-start on boot

`docker compose` with `restart: unless-stopped` (already set) will automatically restart containers after a TrueNAS reboot, as long as the Docker engine itself starts on boot (it does by default on TrueNAS SCALE).

### Updating

```bash
ssh root@<truenas-ip>
cd /mnt/pool/homeauto
git pull                        # or re-copy files
docker compose up -d --build    # rebuilds only if code changed
```
