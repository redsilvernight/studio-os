"""Stage 2 (`.claude/rules/contracts.md`): exercises `StudioApiClient`
against the real FastAPI app + a real Postgres transaction, not a mock.
Guards against the mock in `test_api_client.py` drifting away from the
server's actual behavior."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.errors import AuthenticationError, ConflictError
from studio_client.tokens import MemoryTokenStore
from studio_contracts.claims import ResourceClaimCreate, ResourceType
from studio_contracts.sessions import WorkSessionCreate
from studio_contracts.tasks import TaskCreate, TaskStatus


async def test_create_task_idempotent_replay_returns_same_task(
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
) -> None:
    async with StudioApiClient(client_config, token_store, transport=app_transport) as client:
        key = str(uuid.uuid4())
        task_in = TaskCreate(project_id=project.id, title="Do the thing")

        first = await client.create_task(task_in, idempotency_key=key)
        second = await client.create_task(task_in, idempotency_key=key)

    assert first.id == second.id


async def test_create_task_payload_mismatch_is_typed_conflict(
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
) -> None:
    async with StudioApiClient(client_config, token_store, transport=app_transport) as client:
        key = str(uuid.uuid4())
        await client.create_task(
            TaskCreate(project_id=project.id, title="First"), idempotency_key=key
        )

        with pytest.raises(ConflictError) as excinfo:
            await client.create_task(
                TaskCreate(project_id=project.id, title="Different"), idempotency_key=key
            )

    assert excinfo.value.error_code == "idempotency_key_payload_mismatch"


async def test_revoked_token_raises_authentication_error(
    app_transport: ASGITransport,
    client_config: ClientConfig,
) -> None:
    bad_store = MemoryTokenStore()
    bad_store.set_token("http://test", "not-a-real-token")

    async with StudioApiClient(client_config, bad_store, transport=app_transport) as client:
        with pytest.raises(AuthenticationError):
            await client.list_projects()


async def test_list_projects_round_trips_against_real_app(
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
) -> None:
    async with StudioApiClient(client_config, token_store, transport=app_transport) as client:
        projects = await client.list_projects()

    assert any(p.id == project.id for p in projects)


async def test_task_claim_and_release_round_trip_against_real_app(
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
) -> None:
    async with StudioApiClient(client_config, token_store, transport=app_transport) as client:
        task = await client.create_task(
            TaskCreate(project_id=project.id, title="Claim me"),
            idempotency_key=str(uuid.uuid4()),
        )

        listed = await client.list_tasks(project_id=project.id)
        assert any(t.id == task.id for t in listed)

        claimed = await client.claim_task(task.id)
        assert claimed.status == TaskStatus.IN_PROGRESS
        assert claimed.claimed_by_machine_id is not None

        released = await client.release_task(task.id)

    assert released.claimed_by_machine_id is None
    assert released.claimed_by_machine_id is None


async def test_session_start_and_end_round_trip_against_real_app(
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    async with StudioApiClient(client_config, token_store, transport=app_transport) as client:
        task = await client.create_task(
            TaskCreate(project_id=project.id, title="Work on it"),
            idempotency_key=str(uuid.uuid4()),
        )
        session = await client.start_session(
            WorkSessionCreate(task_id=task.id, machine_id=machine_model.id),
            idempotency_key=str(uuid.uuid4()),
        )
        assert session.ended_at is None

        sessions = await client.list_sessions(task_id=task.id)
        assert any(s.id == session.id for s in sessions)

        ended = await client.end_session(session.id)

    assert ended.ended_at is not None


async def test_claim_create_renew_release_round_trip_against_real_app(
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
) -> None:
    async with StudioApiClient(client_config, token_store, transport=app_transport) as client:
        claim = await client.create_claim(
            ResourceClaimCreate(
                project_id=project.id,
                resource_path="scenes/main.tscn",
                resource_type=ResourceType.FILE,
                ttl_seconds=300,
            ),
            idempotency_key=str(uuid.uuid4()),
        )

        listed = await client.list_claims(project_id=project.id)
        assert any(c.id == claim.id for c in listed)

        renewed = await client.renew_claim(claim.id)
        assert renewed.renewed_at is not None

        await client.release_claim(claim.id)

        remaining = await client.list_claims(project_id=project.id)

    assert all(c.id != claim.id or c.status.value == "released" for c in remaining)
