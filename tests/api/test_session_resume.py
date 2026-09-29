"""Session resume (AIB-H, L2/DEC-0161): `list_sessions` filters by agent and
open state, and `resume_or_start_session` resumes the calling machine's open
session for the same agent on the task — closing an expired one first, never
reusing an ended one. Service-level (the HTTP surface is exercised through
`studio_start_work` in 9dff9368). Needs the real Postgres test DB."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import sessions as sessions_service
from studio_api.services.authz import Principal
from studio_api.settings import get_settings
from studio_contracts.auth import Role
from studio_contracts.sessions import SessionStatus, WorkSessionCreate


async def _principal(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> Principal:
    machine_model, _ = machine
    user = await db_session.get(UserModel, machine_model.owner_user_id)
    assert user is not None
    return Principal(
        machine=machine_model,
        user=user,
        role=Role(user.role),
        project_scope=frozenset({project.id}),
    )


async def _task_id(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> uuid.UUID:
    created = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "resume task"},
    )
    assert created.status_code == 201
    return uuid.UUID(created.json()["id"])


def _session_in(
    task_id: uuid.UUID, machine_id: uuid.UUID, agent_id: uuid.UUID
) -> WorkSessionCreate:
    return WorkSessionCreate(task_id=task_id, machine_id=machine_id, agent_id=agent_id)


async def _backdate(db_session: AsyncSession, session_id: uuid.UUID, age: timedelta) -> None:
    await db_session.execute(
        update(WorkSessionModel)
        .where(WorkSessionModel.id == session_id)
        .values(last_activity_at=datetime.now(UTC) - age)
    )
    await db_session.commit()


async def test_resume_returns_the_open_session(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    principal = await _principal(db_session, machine, project)
    task_id = await _task_id(client, auth_headers, project)
    session_in = _session_in(task_id, machine_model.id, agent.id)

    created, resumed_on_create = await sessions_service.resume_or_start_session(
        db_session, principal, session_in, get_settings()
    )
    assert resumed_on_create is False

    resumed, resumed_on_resume = await sessions_service.resume_or_start_session(
        db_session, principal, session_in, get_settings()
    )
    assert resumed_on_resume is True
    assert resumed.id == created.id
    # A resume is activity: the timestamp moved forward, the row did not fork.
    assert resumed.last_activity_at >= created.last_activity_at


async def test_resume_closes_an_expired_session_then_starts_a_new_one(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    principal = await _principal(db_session, machine, project)
    task_id = await _task_id(client, auth_headers, project)
    session_in = _session_in(task_id, machine_model.id, agent.id)
    settings = get_settings()

    created, _ = await sessions_service.resume_or_start_session(
        db_session, principal, session_in, settings
    )
    await _backdate(
        db_session, created.id, timedelta(seconds=settings.session_expire_after_seconds + 60)
    )

    fresh, resumed = await sessions_service.resume_or_start_session(
        db_session, principal, session_in, settings
    )
    assert resumed is False
    assert fresh.id != created.id

    closed = await db_session.get(WorkSessionModel, created.id)
    assert closed is not None and closed.ended_at is not None
    assert sessions_service.derive_session_status(closed, settings) is SessionStatus.ENDED


async def test_resume_never_reuses_an_ended_session(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    principal = await _principal(db_session, machine, project)
    task_id = await _task_id(client, auth_headers, project)
    session_in = _session_in(task_id, machine_model.id, agent.id)

    created, _ = await sessions_service.resume_or_start_session(
        db_session, principal, session_in, get_settings()
    )
    await sessions_service.end_session(db_session, principal, created.id)

    fresh, resumed = await sessions_service.resume_or_start_session(
        db_session, principal, session_in, get_settings()
    )
    assert resumed is False
    assert fresh.id != created.id


async def test_list_sessions_filters_by_agent_and_open_state(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    principal = await _principal(db_session, machine, project)
    task_id = await _task_id(client, auth_headers, project)

    open_session, _ = await sessions_service.resume_or_start_session(
        db_session,
        principal,
        _session_in(task_id, machine_model.id, agent.id),
        get_settings(),
    )
    # `start_session` always creates a row (no resume), so the second one is
    # a genuine sibling we can close while the first stays open.
    closed_session = await sessions_service.start_session(
        db_session, principal, _session_in(task_id, machine_model.id, agent.id)
    )
    await sessions_service.end_session(db_session, principal, closed_session.id)

    by_task = await sessions_service.list_sessions(db_session, principal, task_id=task_id)
    assert {s.id for s in by_task} == {open_session.id, closed_session.id}

    only_open = await sessions_service.list_sessions(
        db_session, principal, task_id=task_id, open_only=True
    )
    assert {s.id for s in only_open} == {open_session.id}

    other_agent = uuid.uuid4()
    by_other_agent = await sessions_service.list_sessions(
        db_session, principal, task_id=task_id, agent_id=other_agent
    )
    assert by_other_agent == []

    by_agent = await sessions_service.list_sessions(
        db_session, principal, task_id=task_id, agent_id=agent.id, open_only=True
    )
    assert {s.id for s in by_agent} == {open_session.id}


async def test_http_list_sessions_honours_agent_and_open_params(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    machine_model, _ = machine
    task_id = await _task_id(client, auth_headers, project)
    created = await client.post(
        "/api/v1/sessions",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "task_id": str(task_id),
            "machine_id": str(machine_model.id),
            "agent_id": str(agent.id),
        },
    )
    assert created.status_code == 201

    params = {"task_id": str(task_id), "agent_id": str(agent.id), "open": "true"}
    listing = await client.get("/api/v1/sessions", headers=auth_headers, params=params)
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()] == [created.json()["id"]]

    ended = await client.patch(f"/api/v1/sessions/{created.json()['id']}/end", headers=auth_headers)
    assert ended.status_code == 200
    still_open = await client.get("/api/v1/sessions", headers=auth_headers, params=params)
    assert still_open.status_code == 200
    assert still_open.json() == []
