"""Domain-level guarantees of the Roadmap service that HTTP-on-one-session tests
cannot show: atomic rollback of a unit of work, and real cross-transaction races
(separate Postgres connections) on version checks, the single active roadmap
per project and hydration."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.event import EventModel
from studio_api.db.models.idempotency import IdempotencyKeyModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.roadmap import RoadmapModel, RoadmapStepTaskLinkModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.services import events as events_service
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services import roadmap_hydration, roadmaps
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.roadmaps import (
    HydrationApplyRequest,
    RoadmapCreate,
    RoadmapImport,
    RoadmapTransition,
    TransitionRequest,
)

from tests.api.test_roadmaps_api import DOCUMENT

TEST_DATABASE_URL = os.environ.get(
    "STUDIO_TEST_DATABASE_URL",
    "postgresql+asyncpg://studio:studio@localhost:5432/studio_os_test",
)


async def _principal(db_session: AsyncSession, machine: tuple[MachineModel, str]) -> Principal:
    return await load_principal(db_session, machine[0])


async def test_hydration_is_one_unit_of_work_a_failure_leaves_nothing_committed(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = await _principal(db_session, machine)
    imported = await roadmaps.import_roadmap(
        db_session,
        principal,
        RoadmapImport(project_id=project.id, document=DOCUMENT),  # type: ignore[arg-type]
    )
    active = await roadmaps.transition_roadmap(
        db_session,
        principal,
        imported.id,
        TransitionRequest(transition=RoadmapTransition.ACTIVATE, expected_version=imported.version),
    )

    real_add_task = tasks_service.add_task
    calls = {"n": 0}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("second task cannot be created")
        return await real_add_task(*args, **kwargs)

    commits = {"n": 0}
    real_commit = db_session.commit

    async def counting_commit() -> None:
        commits["n"] += 1
        await real_commit()

    monkeypatch.setattr(tasks_service, "add_task", flaky)
    monkeypatch.setattr(db_session, "commit", counting_commit)

    with pytest.raises(RuntimeError):
        await roadmap_hydration.apply_hydration(
            db_session,
            principal,
            active.id,
            HydrationApplyRequest(expected_version=active.version),
        )
    assert commits["n"] == 0  # nothing was made durable before the failure
    await db_session.rollback()

    tasks = (await db_session.execute(select(func.count()).select_from(TaskModel))).scalar_one()
    links = (
        await db_session.execute(select(func.count()).select_from(RoadmapStepTaskLinkModel))
    ).scalar_one()
    assert (tasks, links) == (0, 0)


async def test_state_and_audit_event_are_committed_together(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = await _principal(db_session, machine)
    commits = {"n": 0}
    real_commit = db_session.commit

    async def counting_commit() -> None:
        commits["n"] += 1
        await real_commit()

    monkeypatch.setattr(db_session, "commit", counting_commit)
    await roadmaps.import_roadmap(
        db_session,
        principal,
        RoadmapImport(project_id=project.id, document=DOCUMENT, submit=True),  # type: ignore[arg-type]
    )
    assert commits["n"] == 1  # import + created + proposed events: one transaction
    kinds = (
        (
            await db_session.execute(
                select(EventModel.event_type).where(EventModel.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(kinds) == ["roadmap.created", "roadmap.proposed"]

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("event store down")

    monkeypatch.setattr(events_service, "stage_event", broken)
    commits["n"] = 0
    with pytest.raises(RuntimeError):
        await roadmaps.create_roadmap(
            db_session,
            principal,
            RoadmapCreate(project_id=project.id, title="never durable"),
        )
    assert commits["n"] == 0  # no state is committed without its audit event


async def test_failed_import_leaves_no_partial_roadmap(
    db_session: AsyncSession, machine: tuple[MachineModel, str], project: ProjectModel
) -> None:
    from fastapi import HTTPException

    principal = await _principal(db_session, machine)
    broken = {**DOCUMENT, "phases": [{**DOCUMENT["phases"][0]}, {**DOCUMENT["phases"][0]}]}
    with pytest.raises(HTTPException) as caught:
        await roadmaps.import_roadmap(
            db_session,
            principal,
            RoadmapImport(project_id=project.id, document=broken),  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 422
    count = (await db_session.execute(select(func.count()).select_from(RoadmapModel))).scalar_one()
    assert count == 0


# --- real cross-transaction races ---
@pytest_asyncio.fixture
async def real_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL, pool_size=10, max_overflow=0)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def race(
    real_engine: AsyncEngine,
) -> AsyncIterator[tuple[AsyncClient, dict[str, str], ProjectModel]]:
    factory = async_sessionmaker(real_engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    async with factory() as setup:
        user = await provisioning_service.create_user(
            setup, "Race User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning_service.create_machine(setup, user.id, "race-machine")
        project = await projects_service.create_project(
            setup, f"race-{uuid.uuid4().hex[:8]}", "Race Project", None
        )

    async def _touch() -> None:
        async with factory() as session:
            await session.execute(select(1))

    await asyncio.gather(*(_touch() for _ in range(6)))
    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, {"Authorization": f"Bearer {token}"}, project
    finally:
        app.dependency_overrides.pop(get_session, None)
        async with factory() as cleanup:
            await cleanup.execute(delete(EventModel).where(EventModel.project_id == project.id))
            await cleanup.execute(delete(RoadmapModel).where(RoadmapModel.project_id == project.id))
            await cleanup.execute(delete(TaskModel).where(TaskModel.project_id == project.id))
            await cleanup.execute(
                delete(IdempotencyKeyModel).where(
                    IdempotencyKeyModel.endpoint.like("POST /roadmaps%")
                )
            )
            await cleanup.execute(delete(ProjectModel).where(ProjectModel.id == project.id))
            await cleanup.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup.commit()


async def _import(client: AsyncClient, headers: dict[str, str], project: ProjectModel) -> Any:
    response = await client.post(
        "/api/v1/roadmaps/import",
        headers=headers,
        json={"project_id": str(project.id), "document": DOCUMENT},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_concurrent_patches_with_the_same_version_exactly_one_wins(
    race: tuple[AsyncClient, dict[str, str], ProjectModel],
) -> None:
    client, headers, project = race
    roadmap = await _import(client, headers, project)
    responses = await asyncio.gather(
        *(
            client.patch(
                f"/api/v1/roadmaps/{roadmap['id']}",
                headers={**headers, "If-Match-Version": str(roadmap["version"])},
                json={"title": f"Writer {n}"},
            )
            for n in range(5)
        )
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 409, 409, 409, 409], codes
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json()["detail"] == {
        "error_code": "version_conflict",
        "server_version": roadmap["version"] + 1,
    }


async def test_concurrent_activation_of_two_roadmaps_leaves_a_single_active_one(
    race: tuple[AsyncClient, dict[str, str], ProjectModel],
) -> None:
    client, headers, project = race
    first = await _import(client, headers, project)
    second = await _import(client, headers, project)
    responses = await asyncio.gather(
        *(
            client.post(
                f"/api/v1/roadmaps/{roadmap['id']}/transitions",
                headers=headers,
                json={"transition": "activate", "expected_version": roadmap["version"]},
            )
            for roadmap in (first, second)
        )
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 409], [r.text for r in responses]
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json()["detail"]["error_code"] == "active_roadmap_exists"
    listing = await client.get(
        f"/api/v1/projects/{project.id}/roadmaps", headers=headers, params={"status": "active"}
    )
    assert len(listing.json()) == 1


async def test_concurrent_hydrations_with_distinct_keys_create_each_task_once(
    race: tuple[AsyncClient, dict[str, str], ProjectModel], real_engine: AsyncEngine
) -> None:
    client, headers, project = race
    roadmap = await _import(client, headers, project)
    active = (
        await client.post(
            f"/api/v1/roadmaps/{roadmap['id']}/transitions",
            headers=headers,
            json={"transition": "activate", "expected_version": roadmap["version"]},
        )
    ).json()
    responses = await asyncio.gather(
        *(
            client.post(
                f"/api/v1/roadmaps/{roadmap['id']}/hydration/apply",
                headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
                json={"expected_version": active["version"]},
            )
            for _ in range(5)
        )
    )
    assert [r.status_code for r in responses] == [200] * 5, [r.text for r in responses]
    created = sorted(r.json()["counts"]["create"] for r in responses)
    assert created == [0, 0, 0, 0, 2]  # exactly one caller materialized the plan
    async with async_sessionmaker(real_engine, expire_on_commit=False)() as check:
        task_count = (
            await check.execute(
                select(func.count())
                .select_from(TaskModel)
                .where(TaskModel.project_id == project.id)
            )
        ).scalar_one()
    assert task_count == 2
