import httpx
from typing import Any

from app.config import settings
from app.devices.base import BaseDevice


class NodeMCUDevice(BaseDevice):
    device_id = "nodemcu"

    def __init__(self) -> None:
        self._base_url = f"http://{settings.nodemcu_ip}"
        self._auth = (
            (settings.nodemcu_auth_user, settings.nodemcu_auth_password)
            if settings.nodemcu_auth_user
            else None
        )

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response | None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._base_url}{path}",
                    params=params,
                    auth=self._auth,
                )
                resp.raise_for_status()
                return resp
        except Exception:
            return None

    async def fetch_readings(self) -> dict[str, Any] | None:
        resp = await self._get("/curr_readings")
        if resp is None:
            return None
        return resp.json()

    async def fetch_sensor_status(self) -> dict[str, str] | None:
        resp = await self._get("/sensor_status")
        if resp is None:
            return None
        return resp.json()

    async def get_boiler(self) -> dict[str, Any] | None:
        """Returns {"state": 0|1, "runtime_minutes": float|None}."""
        resp = await self._get("/button_state")
        if resp is None:
            return None
        # Device returns plain text: "1,42.3" (on) or "0" (off)
        text = resp.text.strip()
        parts = text.split(",")
        state = int(parts[0])
        runtime = float(parts[1]) if len(parts) > 1 else None
        return {"state": state, "runtime_minutes": runtime}

    async def set_boiler(self, state: int) -> bool:
        resp = await self._get("/button_update", params={"state": state})
        return resp is not None
