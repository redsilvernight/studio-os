from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services import transfers as transfers_service

TEST_DATABASE_URL = os.environ.get(
    "STUDIO_TEST_DATABASE_URL",
    "postgresql+asyncpg://studio:studio@localhost:5432/studio_os_test",
)


async def _create_transfer(
    client: AsyncClient,
    auth_headers: dict[str, str],
    size_bytes: int,
    project_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "project_id": str(project_id) if project_id else None,
            "category": "temporary",
            "filename": "report.bin",
            "content_type": "application/octet-stream",
            "size_bytes": size_bytes,
        },
    )
    return {"status_code": response.status_code, "body": response.json()}


async def test_create_transfer_rejects_single_transfer_over_max_size(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STUDIO_TRANSFER_MAX_SIZE_BYTES", "1000")

    result = await _create_transfer(client, auth_headers, 1001)

    assert result["status_code"] == 413
    assert result["body"]["detail"]["error_code"] == "transfer_too_large"


async def test_create_transfer_rejects_when_project_quota_exceeded(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUDIO_TRANSFER_MAX_SIZE_BYTES", "10000")
    monkeypatch.setenv("STUDIO_TRANSFER_PROJECT_QUOTA_BYTES", "1000")

    first = await _create_transfer(client, auth_headers, 700, project_id=project.id)
    assert first["status_code"] == 201

    second = await _create_transfer(client, auth_headers, 400, project_id=project.id)
    assert second["status_code"] == 507
    assert second["body"]["detail"]["error_code"] == "quota_exceeded"
    assert second["body"]["detail"]["consumed_bytes"] == 700
    assert second["body"]["detail"]["quota_bytes"] == 1000


async def test_project_quota_does_not_count_unscoped_transfers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUDIO_TRANSFER_MAX_SIZE_BYTES", "10000")
    monkeypatch.setenv("STUDIO_TRANSFER_PROJECT_QUOTA_BYTES", "1000")

    unscoped = await _create_transfer(client, auth_headers, 900, project_id=None)
    assert unscoped["status_code"] == 201

    scoped = await _create_transfer(client, auth_headers, 900, project_id=project.id)
    assert scoped["status_code"] == 201


async def test_consumption_endpoint_matches_real_transfers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUDIO_TRANSFER_MAX_SIZE_BYTES", "10000")
    monkeypatch.setenv("STUDIO_TRANSFER_PROJECT_QUOTA_BYTES", "5000")

    await _create_transfer(client, auth_headers, 300, project_id=project.id)
    await _create_transfer(client, auth_headers, 200, project_id=project.id)

    response = await client.get(
        "/api/v1/transfers/consumption",
        headers=auth_headers,
        params={"project_id": str(project.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == str(project.id)
    assert body["consumed_bytes"] == 500
    assert body["quota_bytes"] == 5000
    assert body["remaining_bytes"] == 4500


async def test_consumption_excludes_deleted_transfers(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    machine_model, _ = machine
    db_session.add(
        TransferModel(
            id=uuid.uuid4(),
            transfer_code="TRF-DELETED",
            sender_user_id=machine_model.owner_user_id,
            project_id=project.id,
            category="temporary",
            filename="gone.bin",
            object_key="studio/test/gone.bin",
            content_type="application/octet-stream",
            size_bytes=9999,
            status="deleted",
            created_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    consumed = await transfers_service.compute_consumption(db_session, project.id)
    assert consumed == 0


@pytest_asyncio.fixture
async def real_engine() -> AsyncIterator[AsyncEngine]:
    """A plain engine with no test-wrapping transaction: unlike the shared
    `db_session` fixture (one savepoint-nested session for the whole test),
    this gives each request its own real, independently-committing
    connection - required to reproduce a race that only exists *across*
    Postgres transactions (mirrors tests/api/test_idempotency_concurrency.py)."""
    engine = create_async_engine(TEST_DATABASE_URL, pool_size=20, max_overflow=0)
    yield engine
    await engine.dispose()


async def _warm_pool(session_factory: async_sessionmaker[AsyncSession], count: int) -> None:
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


async def test_concurrent_creates_never_exceed_project_quota(
    real_engine: AsyncEngine,
    real_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: without `_lock_quota_bucket`'s advisory lock, N
    genuinely concurrent requests (separate connections/transactions) each
    read the same pre-insert consumption and can all pass the check,
    cumulatively exceeding the quota. Quota=1000, size=600 per request: at
    most one of the concurrent requests can legitimately fit."""
    monkeypatch.setenv("STUDIO_TRANSFER_MAX_SIZE_BYTES", "10000")
    monkeypatch.setenv("STUDIO_TRANSFER_PROJECT_QUOTA_BYTES", "1000")

    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as setup_session:
        user = await provisioning_service.create_user(
            setup_session, "Quota Race User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning_service.create_machine(
            setup_session, user.id, "quota-race-machine"
        )
        project = await projects_service.create_project(
            setup_session,
            f"quota-race-{uuid.uuid4().hex[:8]}",
            "Quota Race Project",
            None,
            creator=user,
        )

    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "project_id": str(project.id),
        "category": "temporary",
        "filename": "race.bin",
        "content_type": "application/octet-stream",
        "size_bytes": 600,
    }

    concurrency = 8
    try:
        await _warm_pool(session_factory, concurrency)
        responses = await asyncio.gather(
            *(
                real_client.post("/api/v1/transfers", headers=headers, json=payload)
                for _ in range(concurrency)
            )
        )

        accepted = [r for r in responses if r.status_code == 201]
        rejected = [r for r in responses if r.status_code == 507]
        assert len(accepted) + len(rejected) == concurrency, [r.text for r in responses]
        assert len(accepted) == 1, (
            f"quota=1000, size=600: at most one of {concurrency} concurrent creates should "
            f"fit, got {len(accepted)} accepted"
        )
        for response in rejected:
            assert response.json()["detail"]["error_code"] == "quota_exceeded"

        async with session_factory() as check_session:
            result = await check_session.execute(
                select(TransferModel).where(TransferModel.project_id == project.id)
            )
            transfers = result.scalars().all()
        total_stored = sum(t.size_bytes for t in transfers)
        assert total_stored <= 1000, (
            f"total stored size {total_stored} exceeds the 1000-byte quota - the advisory "
            "lock failed to serialize concurrent creates"
        )
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                delete(TransferModel).where(TransferModel.project_id == project.id)
            )
            await cleanup_session.execute(delete(ProjectModel).where(ProjectModel.id == project.id))
            await cleanup_session.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup_session.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup_session.commit()
