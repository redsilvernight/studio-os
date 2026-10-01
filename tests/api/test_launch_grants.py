"""AIB-J: launch grants on a machine and the `can_launch` decision.

Owner or admin manage grants; a grant never widens project access; every
denial is the same 403 (no oracle)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.deps import get_session  # noqa: F401  (fixture wiring)
from studio_api.services import launch_grants as grants_service
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services.authz import load_principal

pytestmark = [pytest.mark.asyncio, pytest.mark.isolation]


def _url(machine_id: uuid.UUID, user_id: uuid.UUID | None = None) -> str:
    base = f"/api/v1/machines/{machine_id}/launch-grants"
    return base if user_id is None else f"{base}/{user_id}"


async def _user_machine(
    db: AsyncSession, role: str = "developer"
) -> tuple[MachineModel, dict[str, str]]:
    user = await provisioning_service.create_user(db, "U", f"{uuid.uuid4()}@example.test", role)
    machine, token = await provisioning_service.create_machine(db, user.id, "m")
    return machine, {"Authorization": f"Bearer {token}"}


async def _member(db: AsyncSession, project: ProjectModel, machine: MachineModel) -> None:
    await projects_service.grant_member(
        db, project.id, machine.owner_user_id, granted_by_user_id=machine.owner_user_id
    )


async def _principal(db: AsyncSession, machine: MachineModel):  # type: ignore[no-untyped-def]
    await db.refresh(machine)
    return await load_principal(db, machine)


async def test_owner_grants_lists_and_revokes(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    owner_machine, _ = machine
    grantee = other_machine[0].owner_user_id
    r = await client.put(_url(owner_machine.id, grantee), headers=auth_headers, json={})
    assert r.status_code == 201
    assert r.json()["granted_by_user_id"] == str(owner_machine.owner_user_id)
    again = await client.put(_url(owner_machine.id, grantee), headers=auth_headers)
    assert again.status_code == 200
    assert again.json()["created_at"] == r.json()["created_at"]
    listed = await client.get(_url(owner_machine.id), headers=auth_headers)
    assert [g["user_id"] for g in listed.json()] == [str(grantee)]
    assert (
        await client.delete(_url(owner_machine.id, grantee), headers=auth_headers)
    ).status_code == 204
    assert (
        await client.delete(_url(owner_machine.id, grantee), headers=auth_headers)
    ).status_code == 204
    assert (await client.get(_url(owner_machine.id), headers=auth_headers)).json() == []


async def test_non_owner_cannot_manage_grants_and_gets_no_oracle(
    client: AsyncClient,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    other_auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
) -> None:
    owner_machine, _ = machine
    victim = other_machine[0].owner_user_id
    denied = await client.put(_url(owner_machine.id, victim), headers=other_auth_headers)
    unknown = await client.put(_url(uuid.uuid4(), victim), headers=other_auth_headers)
    assert denied.status_code == unknown.status_code == 403
    assert denied.json() == unknown.json()
    assert (await client.get(_url(owner_machine.id), headers=other_auth_headers)).status_code == 403
    assert (
        await client.delete(_url(owner_machine.id, victim), headers=other_auth_headers)
    ).status_code == 403
    assert (
        await client.get(_url(owner_machine.id), headers=readonly_auth_headers)
    ).status_code == 403


async def test_owner_cannot_grant_self_and_admin_can_manage(
    client: AsyncClient,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
    admin_auth_headers: dict[str, str],
) -> None:
    owner_machine, _ = machine
    self_grant = await client.put(
        _url(owner_machine.id, owner_machine.owner_user_id), headers=auth_headers
    )
    assert self_grant.status_code == 403
    assert self_grant.json()["detail"]["error_code"] == "self_modification_forbidden"
    grantee = other_machine[0].owner_user_id
    assert (
        await client.put(_url(owner_machine.id, grantee), headers=admin_auth_headers)
    ).status_code == 201
    assert (
        await client.put(_url(uuid.uuid4(), grantee), headers=admin_auth_headers)
    ).status_code == 404


async def test_grant_validation(
    client: AsyncClient,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    owner_machine, _ = machine
    grantee = other_machine[0].owner_user_id
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    assert (
        await client.put(
            _url(owner_machine.id, grantee), headers=auth_headers, json={"expires_at": past}
        )
    ).status_code == 422
    assert (
        await client.put(_url(owner_machine.id, uuid.uuid4()), headers=auth_headers, json={})
    ).status_code == 404
    # The owner is not a member of `project`: cannot scope a grant to it.
    no_access = await client.put(
        _url(owner_machine.id, grantee), headers=auth_headers, json={"project_id": str(project.id)}
    )
    assert no_access.status_code == 403


async def test_can_launch_matrix(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    target, _ = machine
    other, _ = other_machine
    # Another project and a stranger's machine, for isolation checks.
    elsewhere = await projects_service.create_project(
        db_session, f"p-{uuid.uuid4().hex[:8]}", "Elsewhere", None, creator=None
    )
    await _member(db_session, project, target)
    await _member(db_session, elsewhere, target)
    await _member(db_session, project, other)

    owner = await _principal(db_session, target)
    grantee = await _principal(db_session, other)

    # Owner launches on their own machine; a stranger without a grant cannot.
    assert await grants_service.can_launch(db_session, owner, target, project.id)
    assert not await grants_service.can_launch(db_session, grantee, target, project.id)

    # A grant opens the machine for a member of the project.
    await grants_service.grant(db_session, owner, target, other.owner_user_id, None, None)
    assert await grants_service.can_launch(db_session, grantee, target, project.id)
    # ...but never for a project the grantee is not a member of.
    assert not await grants_service.can_launch(db_session, grantee, target, elsewhere.id)
    # ...and never on another machine of the owner.
    mine_two, _ = await provisioning_service.create_machine(
        db_session, target.owner_user_id, "second"
    )
    assert not await grants_service.can_launch(db_session, grantee, mine_two, project.id)

    # The grant is not reciprocal.
    assert not await grants_service.can_launch(db_session, owner, other, project.id)

    # Revocation closes it.
    await grants_service.revoke(db_session, target, other.owner_user_id)
    assert not await grants_service.can_launch(db_session, grantee, target, project.id)


async def test_scoped_and_expired_grants(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    target, _ = machine
    other, _ = other_machine
    second = await projects_service.create_project(
        db_session, f"p-{uuid.uuid4().hex[:8]}", "Second", None, creator=None
    )
    for p in (project, second):
        await _member(db_session, p, target)
        await _member(db_session, p, other)
    owner = await _principal(db_session, target)
    grantee = await _principal(db_session, other)

    await grants_service.grant(db_session, owner, target, other.owner_user_id, project.id, None)
    assert await grants_service.can_launch(db_session, grantee, target, project.id)
    assert not await grants_service.can_launch(db_session, grantee, target, second.id)

    await grants_service.revoke(db_session, target, other.owner_user_id)
    await grants_service.grant(
        db_session, owner, target, other.owner_user_id, None, datetime.now(UTC) + timedelta(hours=1)
    )
    assert await grants_service.can_launch(db_session, grantee, target, project.id)
    # Time passes: rewrite the stored expiry into the past.
    from studio_api.db.models.machine_launch_grant import MachineLaunchGrantModel

    row = await db_session.get(MachineLaunchGrantModel, (target.id, other.owner_user_id))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert not await grants_service.can_launch(db_session, grantee, target, project.id)


async def test_readonly_and_admin(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    target, _ = machine
    ro_machine, _ = await _user_machine(db_session, "readonly")
    admin_machine, _ = await _user_machine(db_session, "admin")
    await _member(db_session, project, ro_machine)
    await grants_service.grant(
        db_session,
        await _principal(db_session, admin_machine),
        target,
        ro_machine.owner_user_id,
        None,
        None,
    )
    ro = await _principal(db_session, ro_machine)
    admin = await _principal(db_session, admin_machine)
    assert not await grants_service.can_launch(db_session, ro, target, project.id)
    assert await grants_service.can_launch(db_session, admin, target, project.id)
    with pytest.raises(Exception) as exc:
        await grants_service.ensure_can_launch(db_session, ro, target, project.id)
    assert getattr(exc.value, "status_code", None) == 403
