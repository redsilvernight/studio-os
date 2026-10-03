from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.task_launch import TERMINAL_STATUSES, TaskLaunchCredential, TaskLaunchStatus

from studio_api.db.models.launch_credential import LaunchCredentialModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.user import UserModel
from studio_api.security import generate_machine_token, hash_token
from studio_api.services.authz import (
    LAUNCH_SCOPE_ATTR,
    LaunchScope,
    Principal,
    ensure_can_write,
    ensure_project_access,
    get_launch_scope,
)

LAUNCH_REST_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/agents/ensure"),
        ("GET", "/api/v1/agents"),
    }
)

LAUNCH_MCP_ALLOWLIST: frozenset[str] = frozenset(
    {
        "studio_prepare_context",
        "studio_start_work",
        "studio_start_session",
        "studio_end_session",
        "studio_sync",
        "studio_coordinate",
        "studio_log_ai_work",
        "studio_handoff",
        "studio_register_agent",
        "studio_get_task",
        "studio_update_task",
        "studio_claim_task",
        "studio_release_task",
        "studio_claim_resource",
        "studio_claim_resources",
        "studio_release_resource",
        "studio_get_resource_claims",
        "studio_get_decisions",
        "studio_add_decision",
    }
)

_ISSUABLE_STATUSES = (
    TaskLaunchStatus.ACCEPTED.value,
    TaskLaunchStatus.PREPARING.value,
    TaskLaunchStatus.RUNNING.value,
)
_TERMINAL_VALUES = [s.value for s in TERMINAL_STATUSES]


def _scope_denied() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        detail={"error_code": "launch_credential_scope"},
    )


def ensure_rest_allowed(machine: MachineModel, method: str, route_path: str | None) -> None:
    if get_launch_scope(machine) is None:
        return
    if route_path is None or (method.upper(), route_path) not in LAUNCH_REST_ALLOWLIST:
        raise _scope_denied()


def ensure_tool_allowed(machine: MachineModel, tool_name: str | None) -> None:
    if get_launch_scope(machine) is None:
        return
    if tool_name is None or tool_name not in LAUNCH_MCP_ALLOWLIST:
        raise _scope_denied()


async def resolve_launch_credential(session: AsyncSession, token: str) -> MachineModel | None:
    """Ephemeral token -> the launch's target machine, tagged with its
    `LaunchScope`. The machine is a detached copy, so the scope never leaks to
    a durable-token principal sharing the session's identity map. Void when
    expired, revoked, past the launch's life, or when the machine or its owner
    is blocked (same gates as a durable token)."""
    result = await session.execute(
        select(LaunchCredentialModel, MachineModel)
        .join(MachineModel, MachineModel.id == LaunchCredentialModel.machine_id)
        .join(UserModel, UserModel.id == MachineModel.owner_user_id)
        .join(TaskLaunchModel, TaskLaunchModel.id == LaunchCredentialModel.launch_id)
        .where(
            LaunchCredentialModel.credential_hash == hash_token(token),
            LaunchCredentialModel.revoked_at.is_(None),
            LaunchCredentialModel.expires_at > datetime.now(UTC),
            TaskLaunchModel.status.notin_(_TERMINAL_VALUES),
            TaskLaunchModel.expires_at > datetime.now(UTC),
            MachineModel.credential_revoked_at.is_(None),
            UserModel.disabled_at.is_(None),
            UserModel.email_verified_at.is_not(None),
        )
    )
    row = result.first()
    if row is None:
        return None
    credential, durable = row
    machine = MachineModel(
        **{column.key: getattr(durable, column.key) for column in MachineModel.__table__.columns}
    )
    setattr(
        machine,
        LAUNCH_SCOPE_ATTR,
        LaunchScope(
            launch_id=credential.launch_id,
            project_id=credential.project_id,
            task_id=credential.task_id,
        ),
    )
    return machine


async def issue_credential(
    session: AsyncSession, principal: Principal, launch: TaskLaunchModel
) -> TaskLaunchCredential:
    """Only the launch's target machine, with its durable credential (never an
    ephemeral one), obtains a credential, on a live accepted launch."""
    ensure_can_write(principal, "task_launch")
    ensure_project_access(principal, launch.project_id)
    if launch.machine_id != principal.machine.id or get_launch_scope(principal.machine):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"error_code": "forbidden", "resource": "task_launch", "action": "credential"},
        )
    now = datetime.now(UTC)
    if launch.status not in _ISSUABLE_STATUSES or now >= launch.expires_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "launch_not_active"},
        )
    previous = await session.execute(
        select(LaunchCredentialModel).where(
            LaunchCredentialModel.launch_id == launch.id,
            LaunchCredentialModel.revoked_at.is_(None),
        )
    )
    for old in previous.scalars().all():
        old.revoked_at = now
    token = generate_machine_token()
    session.add(
        LaunchCredentialModel(
            id=uuid.uuid4(),
            launch_id=launch.id,
            machine_id=launch.machine_id,
            project_id=launch.project_id,
            task_id=launch.task_id,
            credential_hash=hash_token(token),
            expires_at=launch.expires_at,
        )
    )
    await session.commit()
    return TaskLaunchCredential(token=token, expires_at=launch.expires_at)
