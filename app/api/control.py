from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.devices.nodemcu import NodeMCUDevice

router = APIRouter()
_nodemcu = NodeMCUDevice()


class BoilerCommand(BaseModel):
    state: int

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: int) -> int:
        if v not in (0, 1):
            raise ValueError("state must be 0 or 1")
        return v


@router.get("/devices/nodemcu/boiler")
async def get_boiler():
    result = await _nodemcu.get_boiler()
    if result is None:
        raise HTTPException(status_code=503, detail="Device unreachable")
    return result


@router.post("/devices/nodemcu/boiler")
async def set_boiler(cmd: BoilerCommand):
    ok = await _nodemcu.set_boiler(cmd.state)
    if not ok:
        raise HTTPException(status_code=503, detail="Device unreachable")
    return {"ok": True, "state": cmd.state}
