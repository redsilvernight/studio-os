"""Studio authorization core (DEC-0382/0386, lot 1): active-studio resolution,
studio roles -> rights mapping, operator perimeter and cross-studio isolation.
Pure-function checks run without infrastructure; the resolution and HTTP tests
need the real PostgreSQL test database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.studio import (
    INTERNAL_STUDIO_ID,
    StudioMembershipModel,
    StudioModel,
    StudioRole,
)
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.user import UserModel
from studio_api.jwt_auth import create_access_token
from studio_api.services import provisioning as provisioning_service
from studio_api.services.authz import (
    LAUNCH_SCOPE_ATTR,
    LaunchScope,
    Principal,
    ensure_can_provision,
    ensure_can_write,
    ensure_machine_owned,
    ensure_operator,
    ensure_project_access,
    ensure_studio_role,
    has_project_access,
    load_principal,
    resolve_active_studio,
    studio_clause,
    transfer_visibility_clause,
)
from studio_api.settings import get_settings
from studio_contracts.auth import Role

FORBIDDEN_STUDIO = {"error_code": "forbidden", "resource": "studio", "action": "read"}


def _principal(
    *,
    role: Role = Role.DEVELOPER,
    studio_role: StudioRole = StudioRole.MEMBER,
    is_operator: bool = False,
    project_scope: frozenset[UUID] = frozenset(),
) -> Principal:
    user_id = uuid.uuid4()
    user = UserModel(
        id=user_id,
        role=role.value,
        display_name="t",
        email=f"{user_id}@example.test",
        is_operator=is_operator,
    )
    machine = MachineModel(
        id=uuid.uuid4(), owner_user_id=user_id, display_name="m", credential_hash="x"
    )
    return Principal(
        machine=machine,
        user=user,
        role=role,
        studio_id=INTERNAL_STUDIO_ID,
        studio_role=studio_role,
        is_operator=is_operator,
        project_scope=project_scope,
    )


def _sql(clause: Any) -> str:
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


# --- Studio roles -> rights -------------------------------------------------


@pytest.mark.parametrize(
    ("studio_role", "min_role", "allowed"),
    [
        (StudioRole.OWNER, StudioRole.OWNER, True),
        (StudioRole.OWNER, StudioRole.ADMIN, True),
        (StudioRole.ADMIN, StudioRole.OWNER, False),
        (StudioRole.ADMIN, StudioRole.ADMIN, True),
        (StudioRole.MEMBER, StudioRole.ADMIN, False),
        (StudioRole.MEMBER, StudioRole.MEMBER, True),
        (StudioRole.VIEWER, StudioRole.MEMBER, False),
        (StudioRole.VIEWER, StudioRole.VIEWER, True),
    ],
)
def test_ensure_studio_role_ranking(
    studio_role: StudioRole, min_role: StudioRole, allowed: bool
) -> None:
    principal = _principal(studio_role=studio_role)
    if allowed:
        ensure_studio_role(principal, min_role)
    else:
        with pytest.raises(HTTPException) as denied:
            ensure_studio_role(principal, min_role)
        assert denied.value.status_code == 403
        assert denied.value.detail["resource"] == "studio"


def test_viewer_is_read_only_and_member_writes() -> None:
    ensure_can_write(_principal(studio_role=StudioRole.MEMBER), "task")
    for principal in (
        _principal(studio_role=StudioRole.VIEWER),
        _principal(role=Role.READONLY, studio_role=StudioRole.MEMBER),
    ):
        with pytest.raises(HTTPException) as denied:
            ensure_can_write(principal, "task")
        assert denied.value.detail == {
            "error_code": "forbidden",
            "resource": "task",
            "action": "write",
        }


def test_provisioning_needs_a_studio_manager_or_a_developer() -> None:
    ensure_can_provision(_principal(studio_role=StudioRole.ADMIN), "project")
    ensure_can_provision(_principal(role=Role.DEVELOPER, studio_role=StudioRole.MEMBER), "project")
    for principal in (
        _principal(role=Role.AGENT, studio_role=StudioRole.MEMBER),
        _principal(role=Role.READONLY, studio_role=StudioRole.VIEWER),
    ):
        with pytest.raises(HTTPException):
            ensure_can_provision(principal, "project")


def test_studio_manager_bypasses_machine_ownership_but_member_does_not() -> None:
    other_machine = uuid.uuid4()
    ensure_machine_owned(_principal(studio_role=StudioRole.OWNER), other_machine, "task")
    with pytest.raises(HTTPException):
        ensure_machine_owned(_principal(studio_role=StudioRole.MEMBER), other_machine, "task")


# --- Operator perimeter -----------------------------------------------------


def test_operator_flag_grants_no_content_access() -> None:
    operator = _principal(studio_role=StudioRole.VIEWER, is_operator=True)
    ensure_operator(operator)
    assert not has_project_access(operator, uuid.uuid4())
    with pytest.raises(HTTPException):
        ensure_project_access(operator, uuid.uuid4())

    with pytest.raises(HTTPException) as denied:
        ensure_operator(_principal(is_operator=False))
    assert denied.value.detail == {
        "error_code": "forbidden",
        "resource": "instance",
        "action": "operate",
    }


# --- Clauses ---------------------------------------------------------------


def test_transfer_visibility_is_always_studio_bounded() -> None:
    member_clause = _sql(transfer_visibility_clause(_principal()))
    assert "transfers.studio_id" in member_clause
    assert "transfers.sender_user_id" in member_clause
    assert "transfers.recipient_user_id IS NULL" in member_clause

    manager_clause = _sql(transfer_visibility_clause(_principal(studio_role=StudioRole.ADMIN)))
    assert "transfers.studio_id" in manager_clause
    assert "transfers.sender_user_id" not in manager_clause


def test_studio_clause_combines_studio_and_project_visibility() -> None:
    principal = _principal(project_scope=frozenset({uuid.uuid4()}))
    clause = _sql(studio_clause(principal, TransferModel.studio_id, TransferModel.project_id))
    assert "transfers.studio_id" in clause
    assert "transfers.project_id IN" in clause

    studio_only = _sql(studio_clause(principal, TransferModel.studio_id))
    assert "transfers.studio_id" in studio_only
    assert "transfers.project_id" not in studio_only


def test_has_project_access_rejects_another_studios_project() -> None:
    project_id = uuid.uuid4()
    principal = _principal(project_scope=frozenset({project_id}))
    assert has_project_access(principal, project_id)
    assert not has_project_access(principal, project_id, uuid.uuid4())


# --- Active studio resolution (DB) -----------------------------------------


async def _user_with_machine(
    db_session: AsyncSession, *, role: str = "developer", is_operator: bool = False
) -> tuple[UserModel, MachineModel, str]:
    user = await provisioning_service.create_user(
        db_session, "Studio User", f"{uuid.uuid4()}@example.test", role
    )
    if is_operator:
        user.is_operator = True
        await db_session.flush()
    machine, token = await provisioning_service.create_machine(db_session, user.id, "m")
    return user, machine, token


async def _second_studio(db_session: AsyncSession) -> StudioModel:
    studio = StudioModel(slug=f"studio-{uuid.uuid4().hex[:8]}", name="Second studio")
    db_session.add(studio)
    await db_session.flush()
    return studio


async def _membership(
    db_session: AsyncSession,
    user: UserModel,
    studio: StudioModel | UUID,
    role: str,
    *,
    created_at: datetime | None = None,
) -> StudioMembershipModel:
    studio_id = studio if isinstance(studio, uuid.UUID) else studio.id
    membership = StudioMembershipModel(
        studio_id=studio_id,
        user_id=user.id,
        role=role,
        created_at=created_at or datetime.now(UTC),
    )
    db_session.add(membership)
    await db_session.flush()
    return membership


async def _project(db_session: AsyncSession, studio_id: UUID) -> ProjectModel:
    project = ProjectModel(slug=f"proj-{uuid.uuid4().hex[:8]}", name="Project", studio_id=studio_id)
    db_session.add(project)
    await db_session.flush()
    return project


async def test_single_membership_is_the_default(db_session: AsyncSession) -> None:
    user, _, _ = await _user_with_machine(db_session)
    active = await resolve_active_studio(db_session, user)
    assert active.studio_id == INTERNAL_STUDIO_ID
    assert active.role is StudioRole.MEMBER


async def test_multiple_memberships_default_to_the_internal_studio(
    db_session: AsyncSession,
) -> None:
    user, _, _ = await _user_with_machine(db_session)
    second = await _second_studio(db_session)
    await _membership(db_session, user, second, "owner")

    active = await resolve_active_studio(db_session, user)
    assert active.studio_id == INTERNAL_STUDIO_ID
    assert active.role is StudioRole.MEMBER


async def test_without_internal_studio_the_oldest_membership_wins(
    db_session: AsyncSession,
) -> None:
    user, _, _ = await _user_with_machine(db_session)
    stale = await db_session.scalar(
        select(StudioMembershipModel).where(
            StudioMembershipModel.user_id == user.id,
            StudioMembershipModel.studio_id == INTERNAL_STUDIO_ID,
        )
    )
    assert stale is not None
    await db_session.delete(stale)
    await db_session.flush()

    older = await _second_studio(db_session)
    newer = await _second_studio(db_session)
    await _membership(db_session, user, newer, "admin", created_at=datetime(2026, 2, 1, tzinfo=UTC))
    await _membership(
        db_session, user, older, "viewer", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    active = await resolve_active_studio(db_session, user)
    assert active.studio_id == older.id
    assert active.role is StudioRole.VIEWER


async def test_requested_studio_must_be_a_membership(db_session: AsyncSession) -> None:
    user, _, _ = await _user_with_machine(db_session)
    second = await _second_studio(db_session)
    await _membership(db_session, user, second, "admin")

    active = await resolve_active_studio(db_session, user, second.id)
    assert active.studio_id == second.id
    assert active.role is StudioRole.ADMIN

    unknown = uuid.uuid4()
    with pytest.raises(HTTPException) as denied:
        await resolve_active_studio(db_session, user, unknown)
    assert denied.value.status_code == 403
    assert denied.value.detail == FORBIDDEN_STUDIO

    outsider = await _second_studio(db_session)
    with pytest.raises(HTTPException) as denied_non_member:
        await resolve_active_studio(db_session, user, outsider.id)
    assert denied_non_member.value.status_code == 403
    assert denied_non_member.value.detail == FORBIDDEN_STUDIO


async def test_header_selects_a_studio_and_rejects_a_non_member(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, _, token = await _user_with_machine(db_session)
    second = await _second_studio(db_session)
    await _membership(db_session, user, second, "owner")
    internal_project = await _project(db_session, INTERNAL_STUDIO_ID)
    second_project = await _project(db_session, second.id)
    headers = {"Authorization": f"Bearer {token}"}

    default_listing = await client.get("/api/v1/projects", headers=headers)
    assert default_listing.status_code == 200
    default_ids = {p["id"] for p in default_listing.json()}
    assert str(internal_project.id) in default_ids
    assert str(second_project.id) not in default_ids

    second_listing = await client.get(
        "/api/v1/projects", headers={**headers, "X-Studio-Id": str(second.id)}
    )
    assert second_listing.status_code == 200
    second_ids = {p["id"] for p in second_listing.json()}
    assert second_ids == {str(second_project.id)}

    outsider_studio = await _second_studio(db_session)
    denied = await client.get(
        "/api/v1/projects", headers={**headers, "X-Studio-Id": str(outsider_studio.id)}
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == FORBIDDEN_STUDIO

    malformed = await client.get("/api/v1/projects", headers={**headers, "X-Studio-Id": "nope"})
    assert malformed.status_code == 403
    assert malformed.json()["detail"] == FORBIDDEN_STUDIO


async def test_jwt_claim_selects_the_studio_and_wins_over_the_header(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, machine, token = await _user_with_machine(db_session)
    second = await _second_studio(db_session)
    await _membership(db_session, user, second, "admin")
    internal_project = await _project(db_session, INTERNAL_STUDIO_ID)
    second_project = await _project(db_session, second.id)

    jwt = create_access_token(user, machine, get_settings(), studio_id=second.id)
    listing = await client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {jwt}", "X-Studio-Id": str(INTERNAL_STUDIO_ID)},
    )
    assert listing.status_code == 200
    listed_ids = {p["id"] for p in listing.json()}
    assert listed_ids == {str(second_project.id)}
    assert str(internal_project.id) not in listed_ids

    # Without the claim, the same opaque-token caller keeps the machine/default
    # studio: no new 4xx for a client that never sends a studio.
    baseline = await client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
    assert baseline.status_code == 200


async def test_launch_credential_ignores_the_requested_studio(
    db_session: AsyncSession,
) -> None:
    user, machine, _ = await _user_with_machine(db_session)
    second = await _second_studio(db_session)
    await _membership(db_session, user, second, "owner")
    internal_project = await _project(db_session, INTERNAL_STUDIO_ID)

    setattr(
        machine,
        LAUNCH_SCOPE_ATTR,
        LaunchScope(launch_id=uuid.uuid4(), project_id=internal_project.id, task_id=uuid.uuid4()),
    )
    principal = await load_principal(db_session, machine, requested_studio_id=second.id)
    assert principal.studio_id == INTERNAL_STUDIO_ID
    assert principal.project_scope == frozenset({internal_project.id})


async def test_machine_studio_is_a_preference_not_a_request(
    db_session: AsyncSession,
) -> None:
    """`machines.studio_id` applies while the user is a member of it; once the
    membership is gone the default applies, never a permanent 403."""
    user, machine, _ = await _user_with_machine(db_session)
    second = await _second_studio(db_session)
    await _membership(db_session, user, second, "owner")

    machine.studio_id = second.id
    await db_session.flush()
    assert (await load_principal(db_session, machine)).studio_id == second.id

    await db_session.execute(
        delete(StudioMembershipModel).where(
            StudioMembershipModel.user_id == user.id,
            StudioMembershipModel.studio_id == second.id,
        )
    )
    assert (await load_principal(db_session, machine)).studio_id == INTERNAL_STUDIO_ID


async def test_viewer_reads_but_cannot_write(client: AsyncClient, db_session: AsyncSession) -> None:
    user, _, token = await _user_with_machine(db_session)
    membership = await db_session.scalar(
        select(StudioMembershipModel).where(
            StudioMembershipModel.user_id == user.id,
            StudioMembershipModel.studio_id == INTERNAL_STUDIO_ID,
        )
    )
    assert membership is not None
    membership.role = "viewer"
    await db_session.flush()
    project = await _project(db_session, INTERNAL_STUDIO_ID)
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get(f"/api/v1/projects/{project.id}", headers=headers)).status_code == 200
    denied = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"project_id": str(project.id), "title": "viewer write"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == {
        "error_code": "forbidden",
        "resource": "task",
        "action": "write",
    }


async def test_global_admin_without_a_studio_manager_role_is_denied(
    client: AsyncClient, admin_machine: tuple[MachineModel, str], db_session: AsyncSession
) -> None:
    admin, token = admin_machine
    membership = await db_session.scalar(
        select(StudioMembershipModel).where(
            StudioMembershipModel.user_id == admin.owner_user_id,
            StudioMembershipModel.studio_id == INTERNAL_STUDIO_ID,
        )
    )
    assert membership is not None
    membership.role = "member"
    await db_session.flush()
    headers = {"Authorization": f"Bearer {token}"}

    denied = await client.get("/api/v1/studio/members", headers=headers)
    assert denied.status_code == 403

    membership.role = "owner"
    await db_session.flush()
    assert (await client.get("/api/v1/studio/members", headers=headers)).status_code == 200


async def test_operator_without_membership_reads_no_content(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, machine, token = await _user_with_machine(db_session, is_operator=True)
    membership = await db_session.scalar(
        select(StudioMembershipModel).where(StudioMembershipModel.user_id == user.id)
    )
    assert membership is not None
    await db_session.delete(membership)
    await db_session.flush()

    principal = Principal(
        machine=machine,
        user=user,
        role=Role(user.role),
        studio_id=INTERNAL_STUDIO_ID,
        studio_role=StudioRole.VIEWER,
        is_operator=True,
    )
    ensure_operator(principal)

    denied = await client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
    assert denied.status_code == 403
    assert denied.json()["detail"] == FORBIDDEN_STUDIO
