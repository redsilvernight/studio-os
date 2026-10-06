"""AIB-J: who may launch work on a machine. The owner and admins always can;
anyone else needs an active grant from the owner, and in every case the task's
project must be accessible to the caller (a grant never widens project access)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.machine_launch_grant import MachineLaunchGrantModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.services.authz import (
    Principal,
    ensure_project_access,
    forbidden,
    has_project_access,
)


def _not_found(what: str, ident: uuid.UUID) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        detail={"error_code": "not_found", "message": f"{what} {ident} not found"},
    )


async def get_managed_machine(
    session: AsyncSession, principal: Principal, machine_id: uuid.UUID, action: str
) -> MachineModel:
    """Grants are managed by the machine's owner or an admin. Anyone else gets
    the same 403 whether the machine exists or not (no oracle); only an admin
    can learn that it does not."""
    machine = await session.get(MachineModel, machine_id)
    if principal.role == Role.ADMIN:
        if machine is None:
            raise _not_found("machine", machine_id)
        return machine
    if (
        machine is None
        or machine.owner_user_id != principal.user.id
        or principal.role == Role.READONLY
    ):
        raise forbidden("machine_launch_grant", action)
    return machine


async def list_grants(
    session: AsyncSession, machine: MachineModel
) -> list[MachineLaunchGrantModel]:
    rows = await session.execute(
        select(MachineLaunchGrantModel)
        .where(MachineLaunchGrantModel.machine_id == machine.id)
        .order_by(MachineLaunchGrantModel.created_at, MachineLaunchGrantModel.user_id)
    )
    return list(rows.scalars().all())


async def grant(
    session: AsyncSession,
    principal: Principal,
    machine: MachineModel,
    user_id: uuid.UUID,
    project_id: uuid.UUID | None,
    expires_at: datetime | None,
) -> tuple[MachineLaunchGrantModel, bool]:
    """Returns the grant and whether it was created. An existing grant is
    returned unchanged (revoke then grant to change its scope)."""
    if await session.get(UserModel, user_id) is None:
        raise _not_found("user", user_id)
    if project_id is not None:
        ensure_project_access(principal, project_id, "write")
        if await session.get(ProjectModel, project_id) is None:
            raise _not_found("project", project_id)
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "validation_error",
                "message": "expires_at must be in the future",
            },
        )
    inserted = await session.execute(
        pg_insert(MachineLaunchGrantModel)
        .values(
            machine_id=machine.id,
            user_id=user_id,
            project_id=project_id,
            expires_at=expires_at,
            granted_by_user_id=principal.user.id,
        )
        .on_conflict_do_nothing()
        .returning(MachineLaunchGrantModel.user_id)
    )
    created = inserted.scalar_one_or_none() is not None
    await session.commit()
    row = await session.get(MachineLaunchGrantModel, (machine.id, user_id), populate_existing=True)
    assert row is not None
    return row, created


async def revoke(session: AsyncSession, machine: MachineModel, user_id: uuid.UUID) -> None:
    """Idempotent."""
    await session.execute(
        delete(MachineLaunchGrantModel).where(
            MachineLaunchGrantModel.machine_id == machine.id,
            MachineLaunchGrantModel.user_id == user_id,
        )
    )
    await session.commit()


async def can_launch(
    session: AsyncSession,
    principal: Principal,
    machine: MachineModel,
    project_id: uuid.UUID,
) -> bool:
    if principal.role == Role.READONLY or not has_project_access(principal, project_id):
        return False
    if principal.role == Role.ADMIN or machine.owner_user_id == principal.user.id:
        return True
    found = await session.execute(
        select(MachineLaunchGrantModel.user_id).where(
            MachineLaunchGrantModel.machine_id == machine.id,
            MachineLaunchGrantModel.user_id == principal.user.id,
            or_(
                MachineLaunchGrantModel.project_id.is_(None),
                MachineLaunchGrantModel.project_id == project_id,
            ),
            or_(
                MachineLaunchGrantModel.expires_at.is_(None),
                MachineLaunchGrantModel.expires_at > datetime.now(UTC),
            ),
        )
    )
    return found.scalar_one_or_none() is not None


async def ensure_can_launch(
    session: AsyncSession,
    principal: Principal,
    machine: MachineModel,
    project_id: uuid.UUID,
) -> None:
    """Single 403 for every denial (no grant, expired, wrong project, not a
    member): the caller learns nothing about which condition failed."""
    if not await can_launch(session, principal, machine, project_id):
        raise forbidden("task_launch", "create")
