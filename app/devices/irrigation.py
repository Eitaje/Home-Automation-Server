from typing import Any

from app.devices.base import BaseDevice


class IrrigationDevice(BaseDevice):
    """Stub for the irrigation Arduino. Implement fetch_readings when the
    device has a network interface (HTTP, MQTT, serial-over-network, etc.)."""

    device_id = "irrigation"

    async def fetch_readings(self) -> dict[str, Any] | None:
        return None

    async def fetch_sensor_status(self) -> dict[str, str] | None:
        return None
