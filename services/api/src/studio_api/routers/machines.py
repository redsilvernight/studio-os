from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from studio_contracts.auth import Machine, MachineCreate, MachineCreated, MachineUpdate, Role
from studio_contracts.launch_grants import MachineLaunchGrant, MachineLaunchGrantCreate

from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN, RESP_404_NOT_FOUND, RESP_409_VERSION_CONFLICT
from studio_api.services import heartbeats as heartbeats_service
from studio_api.services import launch_grants as launch_grants_service
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


@router.patch(
    "/{machine_id}",
    response_model=Machine,
    description=(
        "Rename a machine (owner or admin). Another User's machine answers "
        "404 for a non-admin, exactly like a nonexistent one. `agent` never "
        "renames. Uses optimistic concurrency via `If-Match-Version`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND, **RESP_409_VERSION_CONFLICT},
)
async def rename_machine(
    machine_id: UUID,
    machine_in: MachineUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
    if_match_version: int | None = None,
) -> Machine:
    if principal.role == Role.AGENT:
        raise forbidden("machine", "rename")
    target = await provisioning_service.get_machine(session, machine_id)
    if target is None or (
        principal.role != Role.ADMIN and target.owner_user_id != principal.user.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "machine not found")
    if if_match_version is not None and target.version != if_match_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "version_conflict",
                "message": "machine was modified concurrently",
                "expected_version": if_match_version,
                "current_version": target.version,
            },
        )
    target = await provisioning_service.update_machine(session, target, machine_in.display_name)
    return Machine.model_validate(target)


@router.get(
    "/{machine_id}/launch-grants",
    response_model=list[MachineLaunchGrant],
    description=(
        "List the launch grants on a machine (AIB-J). Only the machine's "
        "owner or an admin; anyone else gets `403 forbidden` whether the "
        "machine exists or not."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def list_launch_grants(
    machine_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> list[MachineLaunchGrant]:
    machine = await launch_grants_service.get_managed_machine(
        session, principal, machine_id, "read"
    )
    rows = await launch_grants_service.list_grants(session, machine)
    return [MachineLaunchGrant.model_validate(r) for r in rows]


@router.put(
    "/{machine_id}/launch-grants/{user_id}",
    response_model=MachineLaunchGrant,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Let a User launch work on this machine (AIB-J). Only the owner or "
        "an admin. Optional `project_id` limits it to one project, optional "
        "`expires_at` (future) ends it; the grantee still needs access to the "
        "task's project. `201` with the new grant; an existing grant is "
        "returned unchanged with `200` (revoke then grant to change it). "
        "Naturally idempotent: no `Idempotency-Key`. Granting yourself: "
        "`403 self_modification_forbidden`. Unknown user or project: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def grant_launch(
    machine_id: UUID,
    user_id: UUID,
    response: Response,
    session: DbSession,
    principal: CurrentPrincipal,
    body: MachineLaunchGrantCreate | None = None,
) -> MachineLaunchGrant:
    provisioning_service.ensure_not_self(principal.user, user_id, "grant_launch")
    machine = await launch_grants_service.get_managed_machine(
        session, principal, machine_id, "write"
    )
    body = body or MachineLaunchGrantCreate()
    row, created = await launch_grants_service.grant(
        session, principal, machine, user_id, body.project_id, body.expires_at
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return MachineLaunchGrant.model_validate(row)


@router.delete(
    "/{machine_id}/launch-grants/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Withdraw a User's launch right on this machine (owner or admin). "
        "Idempotent `204`, also when no grant exists."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def revoke_launch(
    machine_id: UUID, user_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> Response:
    provisioning_service.ensure_not_self(principal.user, user_id, "revoke_launch")
    machine = await launch_grants_service.get_managed_machine(
        session, principal, machine_id, "write"
    )
    await launch_grants_service.revoke(session, machine, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
