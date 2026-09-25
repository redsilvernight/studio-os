from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.idempotency import IdempotencyKeyModel, IdempotencyStatus
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service

TEST_DATABASE_URL = os.environ.get(
    "STUDIO_TEST_DATABASE_URL",
    "postgresql+asyncpg://studio:studio@localhost:5432/studio_os_test",
)


@pytest_asyncio.fixture
async def real_engine() -> AsyncIterator[AsyncEngine]:
    """A plain engine with no test-wrapping transaction: unlike
    `tests.api.conftest.db_session` (one savepoint-nested session shared by
    every request in a test, per its own docstring), this lets each request
    below get its own real, independently-committing connection — required
    to reproduce a race that only exists *across* Postgres transactions."""
    engine = create_async_engine(TEST_DATABASE_URL, pool_size=20, max_overflow=0)
    yield engine
    await engine.dispose()


async def _warm_pool(session_factory: async_sessionmaker[AsyncSession], count: int) -> None:
    """Establishes `count` real connections up front. Without this, opening a
    fresh asyncpg connection (TCP + auth handshake) dominates the timing of
    the first request in a batch, so it finishes its whole check-then-create
    sequence before the others even connect — masking the race instead of
    exercising it. Pre-warming lets all `count` requests start from an
    already-connected pool and genuinely overlap at the database."""

    async def _touch() -> None:
        async with session_factory() as session:
            await session.execute(text("select 1"))

    await asyncio.gather(*(_touch() for _ in range(count)))


@pytest_asyncio.fixture
async def real_client(real_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)


async def test_concurrent_same_key_creates_exactly_one_task(
    real_engine: AsyncEngine, real_client: AsyncClient
) -> None:
    """Regression test for 'Securiser l'idempotence sous concurrence': two
    requests that are genuinely concurrent at the Postgres level (separate
    connections/transactions, not just two sequential calls sharing one
    session) must still produce exactly one business row.

    Before the fix, `run_idempotent` ran the business `create()` before
    reserving (idempotency_key, endpoint), so both requests observed "no
    replay yet" and each created its own Task."""
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as setup_session:
        user = await provisioning_service.create_user(
            setup_session, "Concurrency Test User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning_service.create_machine(
            setup_session, user.id, "concurrency-test-machine"
        )
        project = await projects_service.create_project(
            setup_session,
            f"concurrency-{uuid.uuid4().hex[:8]}",
            "Concurrency Test Project",
            None,
            creator=None,
        )

    headers = {**{"Authorization": f"Bearer {token}"}, "Idempotency-Key": str(uuid.uuid4())}
    payload = {"project_id": str(project.id), "title": "Concurrent task"}

    concurrency = 10
    try:
        await _warm_pool(session_factory, concurrency)
        responses = await asyncio.gather(
            *(
                real_client.post("/api/v1/tasks", headers=headers, json=payload)
                for _ in range(concurrency)
            )
        )

        for response in responses:
            assert response.status_code == 201, response.text
        task_ids = {response.json()["id"] for response in responses}
        assert len(task_ids) == 1, (
            f"all {concurrency} concurrent callers using the same Idempotency-Key must be "
            f"told about the same task, got {len(task_ids)} distinct ids: {task_ids}"
        )

        async with session_factory() as check_session:
            result = await check_session.execute(
                select(TaskModel).where(TaskModel.project_id == project.id)
            )
            tasks = result.scalars().all()
        assert len(tasks) == 1, (
            f"expected exactly one Task for this Idempotency-Key, found {len(tasks)}"
        )
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                delete(TaskModel).where(TaskModel.project_id == project.id)
            )
            await cleanup_session.execute(
                delete(IdempotencyKeyModel).where(
                    IdempotencyKeyModel.idempotency_key == headers["Idempotency-Key"]
                )
            )
            await cleanup_session.execute(delete(ProjectModel).where(ProjectModel.id == project.id))
            await cleanup_session.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup_session.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup_session.commit()


async def test_same_key_different_payload_is_rejected_not_replayed(
    real_engine: AsyncEngine, real_client: AsyncClient
) -> None:
    """`request_hash` semantics (DEC-0015): reusing a key with a different
    body is a client error, not a silent replay of the first response and
    not a second resource."""
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as setup_session:
        user = await provisioning_service.create_user(
            setup_session, "Hash Mismatch Test User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning_service.create_machine(
            setup_session, user.id, "hash-mismatch-test-machine"
        )
        project = await projects_service.create_project(
            setup_session,
            f"hashmismatch-{uuid.uuid4().hex[:8]}",
            "Hash Mismatch Project",
            None,
            creator=None,
        )

    key = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}

    try:
        first = await real_client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"project_id": str(project.id), "title": "Original title"},
        )
        assert first.status_code == 201, first.text

        second = await real_client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"project_id": str(project.id), "title": "Different title"},
        )
        assert second.status_code == 409, second.text
        assert second.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"

        async with session_factory() as check_session:
            result = await check_session.execute(
                select(TaskModel).where(TaskModel.project_id == project.id)
            )
            tasks = result.scalars().all()
        assert len(tasks) == 1
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                delete(TaskModel).where(TaskModel.project_id == project.id)
            )
            await cleanup_session.execute(
                delete(IdempotencyKeyModel).where(IdempotencyKeyModel.idempotency_key == key)
            )
            await cleanup_session.execute(delete(ProjectModel).where(ProjectModel.id == project.id))
            await cleanup_session.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup_session.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup_session.commit()


async def test_failed_creation_releases_key_for_a_clean_retry(
    real_engine: AsyncEngine, real_client: AsyncClient
) -> None:
    """A creation that fails inside `create()` (project slug already taken)
    must not leave a stuck pending reservation nor a phantom response —
    critere d'acceptation: 'une création échouée peut être retentée
    proprement'."""
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as setup_session:
        user = await provisioning_service.create_user(
            setup_session, "Retry Test Admin", f"{uuid.uuid4()}@example.test", "admin"
        )
        machine, token = await provisioning_service.create_machine(
            setup_session, user.id, "retry-test-machine"
        )
        taken_slug = f"taken-{uuid.uuid4().hex[:8]}"
        existing_project = await projects_service.create_project(
            setup_session, taken_slug, "Existing Project", None, creator=None
        )

    key = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}

    try:
        failed = await real_client.post(
            "/api/v1/projects",
            headers=headers,
            json={"slug": taken_slug, "name": "Duplicate slug project"},
        )
        assert failed.status_code == 409, failed.text

        async with session_factory() as check_session:
            row = (
                await check_session.execute(
                    select(IdempotencyKeyModel).where(
                        IdempotencyKeyModel.idempotency_key == key,
                        IdempotencyKeyModel.endpoint == "POST /projects",
                    )
                )
            ).scalar_one_or_none()
        assert row is None, "a failed create() must not leave a stuck idempotency reservation"

        retried = await real_client.post(
            "/api/v1/projects",
            headers=headers,
            json={"slug": taken_slug, "name": "Duplicate slug project"},
        )
        assert retried.status_code == 409, (
            "retry must re-attempt creation (and hit the same real conflict), "
            "not hang or return a stale/phantom response"
        )
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                delete(IdempotencyKeyModel).where(IdempotencyKeyModel.idempotency_key == key)
            )
            await cleanup_session.execute(
                delete(ProjectModel).where(ProjectModel.id == existing_project.id)
            )
            await cleanup_session.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup_session.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup_session.commit()


async def test_stale_pending_reservation_is_reclaimed_after_a_crash(
    real_engine: AsyncEngine, real_client: AsyncClient
) -> None:
    """DEC-0015 mitigation: a process that crashes between `_reserve` and
    `_complete`/`_release` runs no Python cleanup, so it leaves a `pending`
    row behind forever unless something reclaims it. Simulates that crash by
    inserting a `pending` row directly, backdated past the reclaim threshold,
    then checks that a normal request with the same key still succeeds
    instead of being blocked indefinitely."""
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as setup_session:
        user = await provisioning_service.create_user(
            setup_session, "Reclaim Test User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning_service.create_machine(
            setup_session, user.id, "reclaim-test-machine"
        )
        project = await projects_service.create_project(
            setup_session,
            f"reclaim-{uuid.uuid4().hex[:8]}",
            "Reclaim Test Project",
            None,
            creator=None,
        )

    key = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}

    try:
        async with session_factory() as abandon_session:
            abandon_session.add(
                IdempotencyKeyModel(
                    idempotency_key=key,
                    endpoint="POST /tasks",
                    request_hash="stale-hash-from-a-crashed-request",
                    status=IdempotencyStatus.PENDING,
                    created_at=datetime.now(UTC) - timedelta(seconds=60),
                )
            )
            await abandon_session.commit()

        response = await real_client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"project_id": str(project.id), "title": "Recovered after crash"},
        )
        assert response.status_code == 201, response.text

        async with session_factory() as check_session:
            result = await check_session.execute(
                select(TaskModel).where(TaskModel.project_id == project.id)
            )
            tasks = result.scalars().all()
        assert len(tasks) == 1
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                delete(TaskModel).where(TaskModel.project_id == project.id)
            )
            await cleanup_session.execute(
                delete(IdempotencyKeyModel).where(IdempotencyKeyModel.idempotency_key == key)
            )
            await cleanup_session.execute(delete(ProjectModel).where(ProjectModel.id == project.id))
            await cleanup_session.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup_session.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup_session.commit()
