from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from studio_contracts.auth import Machine, MachineCreate, MachineCreated, Role

from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN, RESP_404_NOT_FOUND
from studio_api.services import heartbeats as heartbeats_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services.authz import forbidden
from studio_api.settings import get_settings

router = APIRouter(prefix="/api/v1/machines", tags=["machines"])


@router.get(
    "",
    response_model=list[Machine],
    description=(
        "List machines whose credential is not revoked, oldest first: the "
        "caller's own User's machines only, every machine for `admin` "
        "(contract version 2). `status` is derived server-side "
        "from `last_seen_at` (last heartbeat) and is never stored; a machine "
        "that never sent a heartbeat has `last_seen_at: null` and status "
        "`offline`. Credentials and their hashes are never exposed."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_machines(session: DbSession, principal: CurrentPrincipal) -> list[Machine]:
    settings = get_settings()
    owner = None if principal.role == Role.ADMIN else principal.user.id
    return [
        Machine.model_validate(row).model_copy(
            update={"status": heartbeats_service.derive_status(row, settings)}
        )
        for row in await provisioning_service.list_active_machines(session, owner)
    ]


@router.get(
    "/me",
    response_model=Machine,
    description=(
        "Return the machine the presented credential belongs to, so a "
        "client holding only its credential can learn its own `id` (for "
        "heartbeats and the local daemon). Any authenticated machine may "
        "read. `status` is derived from `last_seen_at` exactly as in the list."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def get_own_machine(machine: CurrentMachine) -> Machine:
    return Machine.model_validate(machine).model_copy(
        update={"status": heartbeats_service.derive_status(machine, get_settings())}
    )


@router.post(
    "",
    response_model=MachineCreated,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Provision a new machine credential (self-service, A5). Any "
        "authenticated caller whose role is not `agent` creates a machine "
        "owned by its own User: `owner_user_id` absent or equal to the "
        "caller's User. Naming another User requires `admin`, otherwise "
        "`403 forbidden` (`resource: machine`, `action: create`) without "
        "that User ever being looked up. The new machine inherits its "
        "owner's role and project memberships, never more. The credential "
        "is returned in clear text exactly once — store it immediately, it "
        "is never readable again. Deliberately not replayable: no "
        "`Idempotency-Key` (a replayable credential creation would persist "
        "the secret). The very first machine is created out of band, never "
        "through this endpoint."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def create_machine(
    machine_in: MachineCreate, session: DbSession, principal: CurrentPrincipal
) -> MachineCreated:
    if principal.role == Role.AGENT:
        raise forbidden("machine", "create")
    owner_user_id = machine_in.owner_user_id or principal.user.id
    if owner_user_id != principal.user.id and principal.role != Role.ADMIN:
        raise forbidden("machine", "create")
    new_machine, token = await provisioning_service.create_machine(
        session, owner_user_id, machine_in.display_name
    )
    return MachineCreated(**Machine.model_validate(new_machine).model_dump(), credential=token)


@router.post(
    "/{machine_id}/revoke",
    response_model=Machine,
    description=(
        "Revoke a machine credential immediately (self-service, A5): its "
        "owner or `admin`. Another User's machine answers 404 for a "
        "non-admin, exactly like a nonexistent one, so its existence cannot "
        "be inferred (as `GET /machines` never lists it). `agent` never "
        "revokes. Revoking the calling machine itself is allowed. "
        "Revocation takes effect on the next request — there is no grace "
        "period and no rotation to manage."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def revoke_machine(
    machine_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> Machine:
    if principal.role == Role.AGENT:
        raise forbidden("machine", "revoke")
    target = await provisioning_service.get_machine(session, machine_id)
    if target is None or (
        principal.role != Role.ADMIN and target.owner_user_id != principal.user.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "machine not found")
    target = await provisioning_service.revoke_machine(session, target)
    return Machine.model_validate(target)
