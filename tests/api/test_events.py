from __future__ import annotations

import asyncio
import json
import os
import socket
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
import uvicorn
from httpx import AsyncClient
from sqlalchemy import delete
from studio_api.db import session as db_session
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session_factory
from studio_api.main import app
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service

# The live-server fixtures below need the app's real (non-overridden)
# `get_session` to point at the test database. Set at import time, before
# `get_session_factory()`'s module-level engine cache can be populated by
# either fixture in whichever order pytest instantiates them.
os.environ["STUDIO_DATABASE_URL"] = os.environ.get(
    "STUDIO_TEST_DATABASE_URL", "postgresql+asyncpg://studio:studio@localhost:5432/studio_os_test"
)


def _event_payload(
    project_id: uuid.UUID, actor_id: uuid.UUID, event_id: uuid.UUID
) -> dict[str, object]:
    return {
        "event_id": str(event_id),
        "event_type": "task.created",
        "project_id": str(project_id),
        "actor_type": "system",
        "actor_id": str(actor_id),
        "client_timestamp": datetime.now(UTC).isoformat(),
        "payload": {"title": "Some task"},
    }


async def test_event_replay_by_event_id_returns_original_row(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    event_id = uuid.uuid4()
    payload = _event_payload(project.id, machine_model.id, event_id)

    first = await client.post("/api/v1/events", headers=auth_headers, json=payload)
    assert first.status_code == 200
    first_body = first.json()

    replay_payload = dict(payload)
    replay_payload["payload"] = {"title": "Different, ignored on replay"}
    second = await client.post("/api/v1/events", headers=auth_headers, json=replay_payload)
    assert second.status_code == 200
    second_body = second.json()

    assert second_body["event_id"] == first_body["event_id"]
    assert second_body["server_timestamp"] == first_body["server_timestamp"]
    assert second_body["payload"] == {"title": "Some task"}

    listing = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    matching = [e for e in listing.json() if e["event_id"] == str(event_id)]
    assert len(matching) == 1


async def test_get_events_filters_by_project(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await client.post(
        "/api/v1/events",
        headers=auth_headers,
        json=_event_payload(project.id, machine_model.id, uuid.uuid4()),
    )

    other_project_events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(uuid.uuid4())}
    )
    assert other_project_events.json() == []

    same_project_events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    assert len(same_project_events.json()) == 1


async def _read_one_sse_event(lines: AsyncIterator[str]) -> tuple[int, dict[str, object]]:
    seq: int | None = None
    async for line in lines:
        if line.startswith("id:"):
            seq = int(line.removeprefix("id:").strip())
        elif line.startswith("data:"):
            assert seq is not None
            return seq, json.loads(line.removeprefix("data:").strip())
    raise AssertionError("stream ended before an event was received")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest_asyncio.fixture
async def _real_engine_reset() -> AsyncIterator[None]:
    """`get_engine`/`get_session_factory` (`studio_api/db/session.py`) cache
    an `AsyncEngine` in a module-level global — fine for the app process, but
    pytest-asyncio hands each test its own event loop (`tests/api/conftest.py`
    `engine` fixture docstring) and asyncpg connections are bound to the loop
    they were created on. Reused as-is across tests, the pool's connections
    would belong to an already-closed loop. Reset before and dispose after
    each test that touches the real engine (`live_client`,
    `live_project_and_token`), so it's always created fresh on the current
    loop."""
    await db_session.reset_engine()
    try:
        yield
    finally:
        await db_session.reset_engine()


@pytest_asyncio.fixture
async def live_client(_real_engine_reset: None) -> AsyncIterator[AsyncClient]:
    """A real uvicorn server on localhost, talking to the real (uncommitted-
    savepoint-free) test database. Required for `GET /events/stream`: it
    never completes its response body by design, and httpx's `ASGITransport`
    (used by the `client` fixture) buffers a request's *entire* response
    body before `handle_async_request` returns — a genuinely open-ended
    stream would hang forever under that transport, real sockets don't have
    that limitation."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as ac:
            yield ac
    finally:
        server.should_exit = True
        await serve_task


@pytest_asyncio.fixture
async def live_project_and_token(
    _real_engine_reset: None,
) -> AsyncIterator[tuple[ProjectModel, MachineModel, str]]:
    """Committed rows on the real engine (not the `db_session` savepoint used
    by the other fixtures) — the live uvicorn server in `live_client` uses
    its own connections, which would never see uncommitted data."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        user = await provisioning_service.create_user(
            session, "Stream Test User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine_model, token = await provisioning_service.create_machine(
            session, user.id, "stream-test-machine"
        )
        project = await projects_service.create_project(
            session, f"proj-{uuid.uuid4().hex[:8]}", "Stream Test Project", None
        )
        user_id, project_id = user.id, project.id

    try:
        yield project, machine_model, token
    finally:
        async with session_factory() as session:
            await session.execute(delete(EventModel).where(EventModel.project_id == project_id))
            await session.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
            await session.execute(delete(MachineModel).where(MachineModel.id == machine_model.id))
            await session.execute(delete(UserModel).where(UserModel.id == user_id))
            await session.commit()


async def test_stream_delivers_new_event_to_two_concurrent_clients(
    live_client: AsyncClient,
    live_project_and_token: tuple[ProjectModel, MachineModel, str],
) -> None:
    project, machine_model, token = live_project_and_token
    headers = {"Authorization": f"Bearer {token}"}
    event_id = uuid.uuid4()

    async def _post_after_both_connected() -> None:
        await asyncio.sleep(0.2)
        await live_client.post(
            "/api/v1/events",
            headers=headers,
            json=_event_payload(project.id, machine_model.id, event_id),
        )

    async with (
        live_client.stream(
            "GET",
            "/api/v1/events/stream",
            headers=headers,
            params={"project": str(project.id)},
        ) as stream_a,
        live_client.stream(
            "GET",
            "/api/v1/events/stream",
            headers=headers,
            params={"project": str(project.id)},
        ) as stream_b,
    ):
        assert stream_a.status_code == 200
        assert stream_b.status_code == 200
        poster = asyncio.create_task(_post_after_both_connected())
        seq_a, body_a = await asyncio.wait_for(_read_one_sse_event(stream_a.aiter_lines()), 5)
        seq_b, body_b = await asyncio.wait_for(_read_one_sse_event(stream_b.aiter_lines()), 5)
        await poster

    assert body_a["event_id"] == str(event_id)
    assert body_b["event_id"] == str(event_id)
    assert seq_a == seq_b


async def test_stream_resume_after_reconnect_has_no_duplicate_or_loss(
    live_client: AsyncClient,
    live_project_and_token: tuple[ProjectModel, MachineModel, str],
) -> None:
    project, machine_model, token = live_project_and_token
    headers = {"Authorization": f"Bearer {token}"}
    event_a_id = uuid.uuid4()
    event_b_id = uuid.uuid4()

    async def _post(event_id: uuid.UUID) -> None:
        await live_client.post(
            "/api/v1/events",
            headers=headers,
            json=_event_payload(project.id, machine_model.id, event_id),
        )

    async with live_client.stream(
        "GET",
        "/api/v1/events/stream",
        headers=headers,
        params={"project": str(project.id)},
    ) as first_connection:
        assert first_connection.status_code == 200
        poster = asyncio.create_task(_post(event_a_id))
        seq_a, body_a = await asyncio.wait_for(
            _read_one_sse_event(first_connection.aiter_lines()), 5
        )
        await poster

    assert body_a["event_id"] == str(event_a_id)

    await _post(event_b_id)

    async with live_client.stream(
        "GET",
        "/api/v1/events/stream",
        headers={**headers, "Last-Event-ID": str(seq_a)},
        params={"project": str(project.id)},
    ) as second_connection:
        assert second_connection.status_code == 200
        seq_b, body_b = await asyncio.wait_for(
            _read_one_sse_event(second_connection.aiter_lines()), 5
        )

    assert body_b["event_id"] == str(event_b_id)
    assert seq_b > seq_a


async def test_stream_does_not_republish_an_idempotent_replay(
    live_client: AsyncClient,
    live_project_and_token: tuple[ProjectModel, MachineModel, str],
) -> None:
    project, machine_model, token = live_project_and_token
    headers = {"Authorization": f"Bearer {token}"}
    event_a_id = uuid.uuid4()
    event_b_id = uuid.uuid4()
    payload_a = _event_payload(project.id, machine_model.id, event_a_id)

    async with live_client.stream(
        "GET",
        "/api/v1/events/stream",
        headers=headers,
        params={"project": str(project.id)},
    ) as connection:
        assert connection.status_code == 200
        lines = connection.aiter_lines()

        poster = asyncio.create_task(
            live_client.post("/api/v1/events", headers=headers, json=payload_a)
        )
        seq_a, body_a = await asyncio.wait_for(_read_one_sse_event(lines), 5)
        await poster
        assert body_a["event_id"] == str(event_a_id)

        # Replay of the same event_id must not trigger a second publish —
        # only the genuinely new event below should be the next thing this
        # subscriber sees.
        replay = await live_client.post("/api/v1/events", headers=headers, json=payload_a)
        assert replay.status_code == 200

        poster = asyncio.create_task(
            live_client.post(
                "/api/v1/events",
                headers=headers,
                json=_event_payload(project.id, machine_model.id, event_b_id),
            )
        )
        seq_b, body_b = await asyncio.wait_for(_read_one_sse_event(lines), 5)
        await poster

    assert body_b["event_id"] == str(event_b_id)
    assert seq_b > seq_a


async def test_stream_requires_authentication(client: AsyncClient, project: ProjectModel) -> None:
    response = await client.get("/api/v1/events/stream", params={"project": str(project.id)})
    assert response.status_code == 401
