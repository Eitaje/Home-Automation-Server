from abc import ABC, abstractmethod
from typing import Any


class BaseDevice(ABC):
    device_id: str

    @abstractmethod
    async def fetch_readings(self) -> dict[str, Any] | None:
        """Fetch current readings. Returns None on unreachable/error."""
        ...

    @abstractmethod
    async def fetch_sensor_status(self) -> dict[str, str] | None:
        """Fetch per-sensor ok/fault/disabled map. Returns None on error."""
        ...
