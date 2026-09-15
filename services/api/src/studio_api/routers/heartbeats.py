from __future__ import annotations

from fastapi import APIRouter
from studio_contracts.auth import HeartbeatRequest, HeartbeatResponse

from studio_api.deps import CurrentMachine, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_409_MACHINE_ID_MISMATCH
from studio_api.services import heartbeats as heartbeats_service
from studio_api.settings import get_settings

router = APIRouter(prefix="/api/v1/heartbeats", tags=["heartbeats"])


@router.post(
    "",
    response_model=HeartbeatResponse,
    description=(
        "Report machine presence. Any authenticated machine may "
        "heartbeat, including read-only ones — this is the one write "
        "that never requires a writer role. `machine_id` must equal the "
        "authenticated machine's own id. `status` is derived server-side "
        "from the last report, never stored from the client; send "
        "roughly every 30 seconds."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_409_MACHINE_ID_MISMATCH},
)
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
