from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from studio_contracts.auth import Machine, MachineCreate, MachineCreated, Role

from studio_api.db.models.user import UserModel
from studio_api.deps import CurrentMachine, DbSession, require_roles
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN, RESP_404_NOT_FOUND
from studio_api.services import provisioning as provisioning_service

router = APIRouter(prefix="/api/v1/machines", tags=["machines"])


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
