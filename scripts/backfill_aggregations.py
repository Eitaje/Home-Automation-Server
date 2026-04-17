"""
One-time backfill script — computes 15min / 1h / 1d / 1w aggregations
for all existing raw readings in the Redis stream.

Run from the project root:
    python -m scripts.backfill_aggregations

Or with a custom Redis URL:
    REDIS_URL=redis://192.168.1.70:6379 python -m scripts.backfill_aggregations
"""
import asyncio
import math
import os
import sys
from datetime import datetime, timezone

import redis.asyncio as aioredis

# ── Config ────────────────────────────────────────────────────────────────────
REDIS_URL   = os.environ.get("REDIS_URL", "redis://localhost:6379")
DEVICE_ID   = "nodemcu"
RAW_STREAM  = f"device:{DEVICE_ID}:readings"
BATCH_SIZE  = 500   # entries fetched per XRANGE call

NUMERIC_FIELDS = [
    "water_temperature", "temperature", "temperature_bmp580",
    "humidity", "light", "CO2", "VOC", "AQI", "pressure",
]

RESOLUTIONS = {
    "15min": {"seconds": 900,    "maxlen": 2880},
    "1h":    {"seconds": 3600,   "maxlen": 720},
    "1d":    {"seconds": 86400,  "maxlen": 365},
    "1w":    {"seconds": 604800, "maxlen": 104},
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def bucket_start_ms(ts_ms: int, window_sec: int) -> int:
    """Floor ts_ms to the nearest window boundary (UTC)."""
    window_ms = window_sec * 1000
    return (ts_ms // window_ms) * window_ms


def avg_payload(entries_in_bucket: list[dict]) -> dict:
    accum: dict[str, list[float]] = {f: [] for f in NUMERIC_FIELDS}
    for fields in entries_in_bucket:
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
    return payload


# ── Main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    r = aioredis.from_url(REDIS_URL, decode_responses=True)

    # 1. Read all raw entries in chronological order (batched)
    print(f"Connecting to {REDIS_URL} …")
    print(f"Reading raw stream '{RAW_STREAM}' …", flush=True)
    all_entries: list[tuple[str, dict]] = []
    cursor = "-"
    while True:
        batch = await r.xrange(RAW_STREAM, min=cursor, max="+", count=BATCH_SIZE)
        if not batch:
            break
        all_entries.extend(batch)
        last_id = batch[-1][0]
        # Advance cursor just past the last id to avoid re-fetching it
        ts, seq = last_id.split("-")
        cursor = f"{ts}-{int(seq) + 1}"
        print(f"  … fetched {len(all_entries)} entries so far", end="\r", flush=True)
        if len(batch) < BATCH_SIZE:
            break

    print(f"\nTotal raw entries: {len(all_entries)}")
    if not all_entries:
        print("Nothing to backfill.")
        await r.aclose()
        return

    first_ms = int(all_entries[0][0].split("-")[0])
    last_ms  = int(all_entries[-1][0].split("-")[0])
    print(f"Time range: {datetime.fromtimestamp(first_ms/1000, tz=timezone.utc)} "
          f"→ {datetime.fromtimestamp(last_ms/1000, tz=timezone.utc)}")

    # 2. For each resolution, bucket all entries and write aggregations
    for res, cfg in RESOLUTIONS.items():
        window_ms = cfg["seconds"] * 1000

        # Group entries by bucket
        buckets: dict[int, list[dict]] = {}
        for entry_id, fields in all_entries:
            ts_ms = int(entry_id.split("-")[0])
            bkt = bucket_start_ms(ts_ms, cfg["seconds"])
            buckets.setdefault(bkt, []).append(fields)

        # Generate every bucket in the range (so we can mark gaps as missing)
        first_bkt = bucket_start_ms(first_ms, cfg["seconds"])
        last_bkt  = bucket_start_ms(last_ms,  cfg["seconds"])
        n_buckets = (last_bkt - first_bkt) // window_ms + 1
        n_missing = 0

        # Clear existing agg stream for this resolution before backfilling
        agg_key = f"device:{DEVICE_ID}:agg:{res}"
        await r.delete(agg_key)

        for i in range(n_buckets):
            bkt_ms = first_bkt + i * window_ms
            entries_in_bkt = buckets.get(bkt_ms, [])

            if entries_in_bkt:
                payload = avg_payload(entries_in_bkt)
            else:
                payload = {f: "" for f in NUMERIC_FIELDS}
                payload["missing"] = "1"
                n_missing += 1

            # Use the bucket-start ms as the stream ID so it's time-ordered
            payload["_ts"] = str(bkt_ms)
            await r.xadd(
                agg_key,
                payload,
                id=f"{bkt_ms}-0",
                maxlen=cfg["maxlen"],
                approximate=False,
            )

        print(f"  [{res:5s}]  {n_buckets} buckets written, {n_missing} marked missing")

    await r.aclose()
    print("\nBackfill complete.")


if __name__ == "__main__":
    asyncio.run(main())
