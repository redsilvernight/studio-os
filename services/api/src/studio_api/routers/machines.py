from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from studio_contracts.auth import Machine, MachineCreate, MachineCreated, Role

from studio_api.db.models.user import UserModel
from studio_api.deps import CurrentMachine, DbSession, require_roles
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN, RESP_404_NOT_FOUND
from studio_api.services import heartbeats as heartbeats_service
from studio_api.services import provisioning as provisioning_service
from studio_api.settings import get_settings

router = APIRouter(prefix="/api/v1/machines", tags=["machines"])


@router.get(
    "",
    response_model=list[Machine],
    description=(
        "List machines whose credential is not revoked, oldest first. Any "
        "authenticated machine may read. `status` is derived server-side "
        "from `last_seen_at` (last heartbeat) and is never stored; a machine "
        "that never sent a heartbeat has `last_seen_at: null` and status "
        "`offline`. Credentials and their hashes are never exposed."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_machines(session: DbSession, machine: CurrentMachine) -> list[Machine]:
    settings = get_settings()
    return [
        Machine.model_validate(row).model_copy(
            update={"status": heartbeats_service.derive_status(row, settings)}
        )
        for row in await provisioning_service.list_active_machines(session)
    ]


@router.post(
    "",
    response_model=MachineCreated,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Provision a new machine credential. Requires the admin role. "
        "The credential is returned in clear text exactly once — store "
        "it immediately, it is never readable again. Deliberately not "
        "replayable: no `Idempotency-Key` (a replayable credential "
        "creation would persist the secret). The very first machine is "
        "created out of band, never through this endpoint."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def create_machine(
    machine_in: MachineCreate,
    session: DbSession,
    machine: CurrentMachine,
    _owner: Annotated[UserModel, Depends(require_roles(Role.ADMIN))],
) -> MachineCreated:
    new_machine, token = await provisioning_service.create_machine(
        session, machine_in.owner_user_id, machine_in.display_name
    )
    return MachineCreated(**Machine.model_validate(new_machine).model_dump(), credential=token)


@router.post(
    "/{machine_id}/revoke",
    response_model=Machine,
    description=(
        "Revoke a machine credential immediately. Requires the admin "
        "role. Revocation takes effect on the next request — there is no "
        "grace period and no rotation to manage."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def revoke_machine(
    machine_id: UUID,
    session: DbSession,
    machine: CurrentMachine,
    _owner: Annotated[UserModel, Depends(require_roles(Role.ADMIN))],
) -> Machine:
    target = await provisioning_service.get_machine(session, machine_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "machine not found")
    target = await provisioning_service.revoke_machine(session, target)
    return Machine.model_validate(target)
