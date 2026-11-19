"""Cross-studio isolation (DEC-0382, lot 4): a live SSE stream never delivers
another studio's event, an `X-Studio-Id` of a studio the caller is not a
member of is refused, and an instance operator gets no content access.
Complements the per-resource files of lots 2 and 3 (projects, shared data).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.studio import StudioMembershipModel, StudioModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session_factory
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service

from tests.api.test_events import (
    _event_payload,
    _read_one_sse_event,
    _real_engine_reset,
    live_client,
)
from tests.api.test_studio_isolation_projects import _actor, _create_project

__all__ = ["_real_engine_reset", "live_client"]

FORBIDDEN_STUDIO = {"error_code": "forbidden", "resource": "studio", "action": "read"}


@pytest.mark.isolation
async def test_studio_header_of_a_non_member_studio_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    mine = await _actor(db_session, "owner")
    foreign = await _actor(db_session, "owner")

    refused = await client.get(
        "/api/v1/projects",
        headers={**mine.headers, "X-Studio-Id": str(foreign.studio.id)},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == FORBIDDEN_STUDIO

    unknown = await client.get(
        "/api/v1/projects", headers={**mine.headers, "X-Studio-Id": str(uuid.uuid4())}
    )
    # An unknown studio answers exactly like a foreign one: no existence oracle.
    assert unknown.status_code == 403
    assert unknown.json()["detail"] == FORBIDDEN_STUDIO

    malformed = await client.get(
        "/api/v1/projects", headers={**mine.headers, "X-Studio-Id": "not-a-uuid"}
    )
    assert malformed.status_code == 403


@pytest.mark.isolation
async def test_an_instance_operator_has_no_content_access(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _actor(db_session, "owner")
    project_id = await _create_project(client, owner)

    operator_user = await provisioning_service.create_user(
        db_session, "Instance Operator", f"{uuid.uuid4()}@example.test", "developer"
    )
    operator_user.is_operator = True
    await db_session.flush()
    _, token = await provisioning_service.create_machine(
        db_session, operator_user.id, f"op-{uuid.uuid4().hex[:8]}"
    )
    operator = {"Authorization": f"Bearer {token}"}

    # Not a member of the owner's studio: asking for it is refused outright.
    asked = await client.get(
        "/api/v1/projects", headers={**operator, "X-Studio-Id": str(owner.studio.id)}
    )
    assert asked.status_code == 403
    # Without it, the operator acts in its own default studio and never sees
    # another studio's project, listed or by id.
    listed = await client.get("/api/v1/projects", headers=operator)
    assert listed.status_code == 200
    assert project_id not in {p["id"] for p in listed.json()}
    direct = await client.get(f"/api/v1/projects/{project_id}", headers=operator)
    assert direct.status_code in (403, 404)


@dataclass(frozen=True)
class LiveStudio:
    studio_id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    machine_id: uuid.UUID
    headers: dict[str, str]


async def _live_studio(label: str) -> LiveStudio:
    """A committed studio, owner, machine and project on the real engine: the
    live uvicorn server uses its own connections."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        studio = StudioModel(slug=f"{label}-{uuid.uuid4().hex[:8]}", name=f"Live {label}")
        session.add(studio)
        await session.flush()
        user = await provisioning_service.create_user(
            session, f"Live {label}", f"{uuid.uuid4()}@example.test", "developer"
        )
        session.add(StudioMembershipModel(studio_id=studio.id, user_id=user.id, role="owner"))
        machine, token = await provisioning_service.create_machine(
            session, user.id, f"live-{label}-machine"
        )
        project = await projects_service.create_project(
            session,
            f"live-{label}-{uuid.uuid4().hex[:8]}",
            f"Live {label}",
            None,
            creator=None,
            studio_id=studio.id,
        )
        live = LiveStudio(
            studio_id=studio.id,
            project_id=project.id,
            user_id=user.id,
            machine_id=machine.id,
            headers={"Authorization": f"Bearer {token}", "X-Studio-Id": str(studio.id)},
        )
        await session.commit()
    return live


async def _drop_live_studio(live: LiveStudio) -> None:
    async with get_session_factory()() as session:
        await session.execute(delete(EventModel).where(EventModel.project_id == live.project_id))
        await session.execute(delete(ProjectModel).where(ProjectModel.id == live.project_id))
        await session.execute(delete(MachineModel).where(MachineModel.id == live.machine_id))
        await session.execute(
            delete(StudioMembershipModel).where(StudioMembershipModel.user_id == live.user_id)
        )
        await session.execute(delete(UserModel).where(UserModel.id == live.user_id))
        await session.execute(delete(StudioModel).where(StudioModel.id == live.studio_id))
        await session.commit()


@pytest_asyncio.fixture
async def two_live_studios(
    _real_engine_reset: None,
) -> AsyncIterator[tuple[LiveStudio, LiveStudio]]:
    first = await _live_studio("a")
    second = await _live_studio("b")
    try:
        yield first, second
    finally:
        await _drop_live_studio(first)
        await _drop_live_studio(second)


async def test_a_live_stream_is_bound_to_its_own_studio(
    live_client: AsyncClient, two_live_studios: tuple[LiveStudio, LiveStudio]
) -> None:
    mine, theirs = two_live_studios

    # The stream of another studio's project cannot even be opened: its
    # project answers like an unknown one for this studio.
    async with live_client.stream(
        "GET",
        "/api/v1/events/stream",
        headers=mine.headers,
        params={"project": str(theirs.project_id)},
    ) as refused:
        assert refused.status_code in (403, 404)

    # Positive control: the studio's own project stream delivers its event, and
    # an event of the other studio posted meanwhile is never mixed into it.
    their_event, my_event = uuid.uuid4(), uuid.uuid4()

    async def _post_theirs_then_mine() -> None:
        await asyncio.sleep(0.3)
        response = await live_client.post(
            "/api/v1/events",
            headers=theirs.headers,
            json=_event_payload(theirs.project_id, theirs.user_id, their_event),
        )
        assert response.status_code == 200, response.text
        await asyncio.sleep(0.3)
        response = await live_client.post(
            "/api/v1/events",
            headers=mine.headers,
            json=_event_payload(mine.project_id, mine.user_id, my_event),
        )
        assert response.status_code == 200, response.text

    async with live_client.stream(
        "GET",
        "/api/v1/events/stream",
        headers=mine.headers,
        params={"project": str(mine.project_id)},
    ) as stream:
        poster = asyncio.create_task(_post_theirs_then_mine())
        try:
            _, body = await asyncio.wait_for(_read_one_sse_event(stream.aiter_lines()), 10)
        finally:
            await poster
    assert body["event_id"] == str(my_event)


def _project_scoped_get_routes() -> list[tuple[str, str]]:
    """Every GET route addressed by a project id, found from the OpenAPI
    document so a route added later is covered without editing this test:
    `(path, query_name)`, where `query_name` is empty for a `{project_id}` path
    parameter and the query parameter's name for a `project_id`/`project`
    filter."""
    from studio_api.main import app

    routes: list[tuple[str, str]] = []
    for path, operations in app.openapi()["paths"].items():
        operation = operations.get("get")
        if operation is None:
            continue
        if "{project_id}" in path:
            routes.append((path, ""))
            continue
        if "{" in path:
            continue
        for parameter in operation.get("parameters", []):
            if parameter.get("in") == "query" and parameter.get("name") in (
                "project_id",
                "project",
            ):
                routes.append((path, parameter["name"]))
    return sorted(routes)


@pytest.mark.isolation
@pytest.mark.parametrize(("path", "query_name"), _project_scoped_get_routes())
async def test_no_project_route_reads_another_studios_project(
    client: AsyncClient, db_session: AsyncSession, path: str, query_name: str
) -> None:
    """A studio owner/admin asking for another studio's project, on any GET
    route addressed by a project id, never gets its content: refused, unknown,
    or an empty collection."""
    if path.endswith("/stream"):
        pytest.skip("open-ended SSE stream: covered by the live stream test")
    owner = await _actor(db_session, "owner")
    foreign = await _actor(db_session, "owner")
    foreign_project = await _create_project(client, foreign)

    if query_name:
        response = await client.get(
            path, headers=owner.headers, params={query_name: foreign_project}
        )
    else:
        response = await client.get(
            path.replace("{project_id}", foreign_project), headers=owner.headers
        )
    if response.status_code == 200:
        body = response.json()
        # Empty: a bare empty collection, or an object whose values are all
        # empty collections/zero (the requested project id echoed back is not
        # content).
        assert body in ([], {}, None) or (
            isinstance(body, dict)
            and all(v in ([], {}, None, 0, foreign_project) for v in body.values())
        ), f"{path} returned content of another studio's project: {response.text[:200]}"
    else:
        assert response.status_code in (403, 404, 405, 409, 422), (
            f"{path} -> {response.status_code}: {response.text[:200]}"
        )
