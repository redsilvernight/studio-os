from __future__ import annotations

from fastapi import APIRouter
from studio_contracts.auth import HeartbeatRequest, HeartbeatResponse

from studio_api.deps import CurrentMachine, DbSession
from studio_api.services import heartbeats as heartbeats_service
from studio_api.settings import get_settings

router = APIRouter(prefix="/api/v1/heartbeats", tags=["heartbeats"])


@router.post("", response_model=HeartbeatResponse)
async def post_heartbeat(
    req: HeartbeatRequest, machine: CurrentMachine, session: DbSession
) -> HeartbeatResponse:
    settings = get_settings()
    machine, now = await heartbeats_service.record_heartbeat(session, machine, req, settings)
    return HeartbeatResponse(
        machine_id=machine.id,
        status=heartbeats_service.derive_status(machine, settings),
        last_seen_at=now,
        server_timestamp=now,
    )
