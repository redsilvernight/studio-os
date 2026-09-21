from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session_factory
from studio_api.services import provisioning as provisioning_service

from tests.api.test_events import (
    _read_one_sse_event,
    _real_engine_reset,
    live_client,
    live_project_and_token,
)

__all__ = ["_real_engine_reset", "live_client", "live_project_and_token"]


@pytest_asyncio.fixture
async def live_admin_token(
    live_project_and_token: tuple[ProjectModel, MachineModel, str],
) -> AsyncIterator[str]:
    """A second, admin-role machine on the same real (committed) engine as
    `live_project_and_token` — accept/supersede are admin-only."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        admin = await provisioning_service.create_user(
            session, "Stream Admin", f"{uuid.uuid4()}@example.test", "admin"
        )
        admin_machine, token = await provisioning_service.create_machine(
            session, admin.id, "stream-admin-machine"
        )
        admin_id, admin_machine_id = admin.id, admin_machine.id
    try:
        yield token
    finally:
        async with session_factory() as session:
            # Torn down before `live_project_and_token` (LIFO fixture order),
            # so the `decision.accepted` event this admin machine authored
            # still exists — delete it first or the FK on `events.machine_id`
            # blocks the machine delete.
            await session.execute(
                delete(EventModel).where(EventModel.machine_id == admin_machine_id)
            )
            await session.execute(delete(MachineModel).where(MachineModel.id == admin_machine_id))
            await session.execute(delete(UserModel).where(UserModel.id == admin_id))
            await session.commit()


async def test_accept_decision_is_delivered_live_on_the_sse_stream(
    live_client: AsyncClient,
    live_project_and_token: tuple[ProjectModel, MachineModel, str],
    live_admin_token: str,
) -> None:
    """DEC-0094: the lost prior attempt found a defect exactly here — a
    transition recorded in the events table but never fanned out to
    `GET /events/stream`. Assert the live delivery itself, not just that the
    event was stored (`test_accept_decision_emits_decision_accepted_event`
    in `test_decisions.py` already covers storage)."""
    project, machine_model, token = live_project_and_token
    headers = {"Authorization": f"Bearer {token}"}
    admin_headers = {"Authorization": f"Bearer {live_admin_token}"}

    created = await live_client.post(
        "/api/v1/decisions",
        headers=headers,
        json={
            "project_id": str(project.id),
            "title": "Adopt SSE for streaming",
            "body": "Body",
            "proposed_by_type": "agent",
            "proposed_by_id": str(machine_model.id),
        },
    )
    assert created.status_code == 201
    decision_id = created.json()["id"]

    async def _accept_after_connected() -> None:
        await asyncio.sleep(0.2)
        response = await live_client.post(
            f"/api/v1/decisions/{decision_id}/accept", headers=admin_headers
        )
        assert response.status_code == 200

    try:
        async with live_client.stream(
            "GET",
            "/api/v1/events/stream",
            headers=headers,
            params={"project": str(project.id)},
        ) as stream:
            assert stream.status_code == 200
            acceptor = asyncio.create_task(_accept_after_connected())
            _seq, body = await asyncio.wait_for(_read_one_sse_event(stream.aiter_lines()), 5)
            await acceptor

        assert body["event_type"] == "decision.accepted"
        assert body["payload"]["decision_id"] == decision_id
        assert body["payload"]["status"] == "accepted"
    finally:
        # `live_project_and_token`'s own teardown deletes events/machine/user
        # for this project but predates Decisions — the row this test creates
        # would otherwise block that teardown's `DELETE FROM projects` on the
        # `decisions_project_id_fkey` FK.
        session_factory = get_session_factory()
        async with session_factory() as session:
            await session.execute(delete(DecisionModel).where(DecisionModel.id == decision_id))
            await session.commit()
