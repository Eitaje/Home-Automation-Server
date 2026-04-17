"""
Tests for the data pipeline from NodeMCU → Redis → history API → UI.

These tests were written to diagnose missing-value gaps appearing in charts
after deploying the xrevrange fix and new ENS160 firmware. Each test targets
one specific failure mode in the pipeline.

Run:  .venv/Scripts/pytest tests/test_history_pipeline.py -v
"""

import pytest
import pytest_asyncio
import fakeredis.aioredis
from httpx import AsyncClient, ASGITransport

import app.redis_client as redis_module
from app.main import app
from app.aggregator import _aggregate

# Fixed past timestamp — far enough in the past that it never falls inside
# a "current window" aggregation query.
BASE_MS = 1_700_000_000_000  # 2023-11-14, well outside any aggregation window

ALL_SENSOR_FIELDS = [
    "water_temperature", "temperature", "temperature_bmp580",
    "humidity", "light", "CO2", "VOC", "AQI", "pressure",
]

# Matches what getSensorReadings() on the NodeMCU sends when all sensors are healthy
FULL_READING = {
    "water_temperature": "22.50",
    "temperature": "21.30",
    "temperature_bmp580": "21.10",
    "humidity": "55.00",
    "light": "300.00",
    "CO2": "800",
    "VOC": "150",
    "AQI": "2",
    "pressure": "1013.25",
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def fake_redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_module._client = r
    yield r
    redis_module._client = None
    await r.aclose()


@pytest_asyncio.fixture
async def client(fake_redis):
    """HTTP test client — uses ASGITransport to avoid triggering app lifespan."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_history_returns_most_recent_entries(fake_redis, client):
    """
    Push 50 entries; requesting count=10 should return the 10 most recent,
    not the 10 oldest. This verifies the xrevrange change is working.

    BEFORE the fix: xrange returned oldest-first → charts showed stale data.
    AFTER the fix:  xrevrange+reverse returns newest N entries, oldest-first
                    within that slice.
    """
    stream = "device:nodemcu:readings"
    for i in range(50):
        ts = BASE_MS + i * 10_000
        await fake_redis.xadd(stream, {**FULL_READING, "_ts": str(ts)}, id=f"{ts}-0")

    resp = await client.get("/devices/nodemcu/history?count=10")

    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 10

    # Most-recent 10 should start at index 40 (i=40..49)
    expected_first_ts = BASE_MS + 40 * 10_000
    actual_first_ts = int(entries[0]["id"].split("-")[0])
    assert actual_first_ts == expected_first_ts, (
        f"Expected oldest of the most-recent-10 to be ts={expected_first_ts}, "
        f"but got ts={actual_first_ts}. "
        f"If this is BASE_MS+0, xrevrange is NOT in effect and we're seeing oldest entries."
    )


async def test_all_sensor_fields_survive_round_trip(fake_redis, client):
    """
    All sensor fields stored in Redis must be returned unchanged by /history.
    If any field is silently dropped, the UI will render a null gap for it.
    """
    stream = "device:nodemcu:readings"
    await fake_redis.xadd(stream, {**FULL_READING, "_ts": str(BASE_MS)}, id=f"{BASE_MS}-0")

    resp = await client.get("/devices/nodemcu/history?count=1")

    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 1, "Expected exactly 1 entry"

    missing = [f for f in ALL_SENSOR_FIELDS if f not in entries[0]]
    assert not missing, (
        f"Fields absent from history response (will render as chart gaps): {missing}"
    )
    for f in ALL_SENSOR_FIELDS:
        assert entries[0][f] == FULL_READING[f], f"Field {f!r} value changed in transit"


async def test_warmup_zeros_are_present_not_null(fake_redis, client):
    """
    During ENS160 warm-up, getSensorReadings() returns AQI/CO2/VOC as "0"
    (from the isEmpty() fallback). These should arrive as "0" — not absent —
    so the UI renders numeric 0 rather than a gap.

    If this test fails (field absent or empty), the firmware or storage layer
    is swallowing warmup values and the chart will show gaps for those sensors.
    """
    stream = "device:nodemcu:readings"
    warmup_entry = {**FULL_READING, "AQI": "0", "CO2": "0", "VOC": "0", "_ts": str(BASE_MS)}
    await fake_redis.xadd(stream, warmup_entry, id=f"{BASE_MS}-0")

    resp = await client.get("/devices/nodemcu/history?count=1")

    assert resp.status_code == 200
    entry = resp.json()[0]
    for field in ("AQI", "CO2", "VOC"):
        assert field in entry, (
            f"{field!r} is absent from the response — UI will show a gap instead of 0"
        )
        assert entry[field] == "0", (
            f"{field!r}: expected '0', got {entry[field]!r}"
        )


async def test_old_entries_missing_temperature_bmp580(fake_redis, client):
    """
    Entries written before temperature_bmp580 was added to the firmware lack
    that field in Redis. The endpoint must return them without crashing, and
    the field should be absent (the UI will show null for those points, which
    is correct — better than showing garbage).
    """
    stream = "device:nodemcu:readings"
    old_entry = {k: v for k, v in FULL_READING.items() if k != "temperature_bmp580"}
    old_entry["_ts"] = str(BASE_MS)
    await fake_redis.xadd(stream, old_entry, id=f"{BASE_MS}-0")

    resp = await client.get("/devices/nodemcu/history?count=1")

    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 1
    # Field must be absent (not an empty string), so the UI can distinguish
    # "no sensor data" from "sensor sent 0"
    assert "temperature_bmp580" not in entries[0], (
        "temperature_bmp580 should be absent for old entries — "
        "the UI correctly renders this as null"
    )


async def test_bulk_readings_past_timestamps_do_not_crash(fake_redis, client):
    """
    When the device comes back online after a reboot, offlineBuffer_syncToServer()
    POSTs old timestamped entries to /bulk_readings. Redis XADD with explicit IDs
    rejects any ID <= the stream's current tip with a ResponseError.

    This test verifies the endpoint handles that case gracefully (not HTTP 500).

    KNOWN BUG: before the fix, the unhandled ResponseError causes HTTP 500 and
    the offline buffer is never cleared, looping on every reconnect.
    """
    stream = "device:nodemcu:readings"

    # Current stream tip at T+10min
    current_ts = BASE_MS + 10 * 60_000
    await fake_redis.xadd(stream, {**FULL_READING, "_ts": str(current_ts)}, id=f"{current_ts}-0")

    # Offline buffer has entries from T+2min..T+8min (all older than current tip)
    past_readings = []
    for i in range(2, 9):
        ts_s = (BASE_MS + i * 60_000) // 1000  # unix seconds
        past_readings.append({
            "timestamp": ts_s,
            **{k: float(v) for k, v in FULL_READING.items()},
        })

    resp = await client.post("/devices/nodemcu/bulk_readings", json=past_readings)

    assert resp.status_code != 500, (
        f"Offline bulk sync crashed with HTTP 500: {resp.text}\n"
        "Fix: wrap xadd in bulk_readings with try/except to skip rejected IDs."
    )
    # Should report how many were actually stored (may be 0 if all rejected)
    assert "stored" in resp.json()


async def test_aggregation_marks_empty_window_as_missing(fake_redis):
    """
    When the aggregator runs with no raw data in the window (device was offline),
    it must write missing=1 with empty strings for all fields. The UI then shows
    a red indicator bar for that time slot.
    """
    # No entries in the raw stream — device was offline for this window.
    await _aggregate("nodemcu", "15min")

    agg_entries = await fake_redis.xrange("device:nodemcu:agg:15min")
    assert len(agg_entries) == 1, "Aggregator should write exactly one entry per run"
    _, fields = agg_entries[0]

    assert fields.get("missing") == "1", (
        f"Expected missing='1' for empty window, got missing={fields.get('missing')!r}"
    )
    for f in ALL_SENSOR_FIELDS:
        assert fields.get(f) == "", (
            f"Field {f!r} should be '' in a missing window, got {fields.get(f)!r}"
        )


async def test_aggregation_with_data_sets_missing_zero(fake_redis):
    """
    When raw data is present in the window, aggregation must write missing=0
    and numeric averages for all fields that had data.
    """
    import time
    stream = "device:nodemcu:readings"
    # Insert entries inside the current 15-min window
    now_ms = int(time.time() * 1000)
    for i in range(5):
        ts = now_ms - (4 - i) * 60_000  # last 4 minutes
        await fake_redis.xadd(stream, {**FULL_READING, "_ts": str(ts)}, id=f"{ts}-{i}")

    await _aggregate("nodemcu", "15min")

    agg_entries = await fake_redis.xrange("device:nodemcu:agg:15min")
    assert len(agg_entries) == 1
    _, fields = agg_entries[0]

    assert fields.get("missing") == "0", (
        f"Expected missing='0' when data is present, got {fields.get('missing')!r}"
    )
    # At least temperature should be a non-empty float string
    assert fields.get("temperature") != "", "Expected averaged temperature, got empty string"
    try:
        float(fields["temperature"])
    except (ValueError, KeyError):
        pytest.fail(f"temperature is not a valid float: {fields.get('temperature')!r}")
