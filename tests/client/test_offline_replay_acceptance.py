"""Real end-to-end acceptance test for the last-but-one open scenario of
`docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/10_TEST_ACCEPTANCE.md`
("replay offline complet") and the matching item in
`docs/ROADMAP_CORRECTIONS_AUDIT.md` step 7 ("replay offline complet avec
tasks, events et AIWorkLog").

Real Postgres (in-process ASGI transport for the API itself, per
`tests/client/conftest.py`) — no mocks for the server side. The client is
made offline via a real `httpx.ConnectError` raised by every request on a
dedicated transport, exercised through the same `OutboxStore`/`OutboxReplayer`
a live daemon uses, never a stand-in."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.outbox import OutboxReplayer, OutboxStore, OutboxTable, connect, transaction
from studio_client.retry import RetryPolicy
from studio_client.tokens import MemoryTokenStore
from studio_contracts.ai_work import AIWorkLogCreate
from studio_contracts.events import EventCreate, EventType
from studio_contracts.tasks import TaskCreate

_TASK_COUNT = 3


def _offline_transport() -> httpx.MockTransport:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated offline network", request=request)

    return httpx.MockTransport(_handler)


async def test_full_offline_replay_tasks_events_ai_work_is_lossless_and_idempotent(
    tmp_path: Path,
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    outbox_path = tmp_path / "outbox.sqlite3"
    retry_policy = RetryPolicy(max_attempts=1, backoff_initial=0.001, backoff_max=0.002)
    open_stores: list[OutboxStore] = []

    task_keys = [str(uuid.uuid4()) for _ in range(_TASK_COUNT)]
    task_payloads = [
        TaskCreate(project_id=project.id, title=f"offline-task-{i}").model_dump(mode="json")
        for i in range(_TASK_COUNT)
    ]
    event_ids = [uuid.uuid4() for _ in range(2)]
    events = [
        EventCreate(
            event_id=event_ids[0],
            event_type=EventType.TASK_CREATED,
            project_id=project.id,
            actor_type="agent",
            actor_id=agent.id,
            client_timestamp=datetime.now(UTC),
            payload={"title": "offline-task-0"},
        ),
        EventCreate(
            event_id=event_ids[1],
            event_type=EventType.AI_WORK_STARTED,
            project_id=project.id,
            actor_type="agent",
            actor_id=agent.id,
            client_timestamp=datetime.now(UTC),
            payload={"summary": "offline replay acceptance"},
        ),
    ]
    ai_work_key = str(uuid.uuid4())
    ai_work_payload = AIWorkLogCreate(
        project_id=project.id,
        agent_id=agent.id,
        machine_id=machine_model.id,
        summary="offline replay acceptance",
    ).model_dump(mode="json")

    try:
        # Phase 1: server unreachable. Every enqueue shares a transaction
        # with the local write it represents (.claude/rules/offline-sync.md).
        store = OutboxStore(connect(outbox_path))
        open_stores.append(store)
        for key, payload in zip(task_keys, task_payloads, strict=True):
            with transaction(store.connection):
                store.enqueue_mutation(key, "task.create", "POST", "/api/v1/tasks", payload)
        for event in events:
            with transaction(store.connection):
                store.enqueue_event(event)
        with transaction(store.connection):
            store.enqueue_mutation(
                ai_work_key, "ai_work.create", "POST", "/api/v1/ai-work", ai_work_payload
            )

        assert len(store.list_pending(OutboxTable.MUTATIONS, ready_only=False)) == _TASK_COUNT + 1
        assert len(store.list_pending(OutboxTable.EVENTS, ready_only=False)) == len(events)

        async with StudioApiClient(
            client_config, token_store, transport=_offline_transport()
        ) as offline_api:
            offline_outcome = await OutboxReplayer(store, offline_api, retry_policy).replay_ready()

        assert offline_outcome.succeeded == 0
        assert offline_outcome.dead_lettered == 0
        assert offline_outcome.stopped_on_transient_error is True
        # Nothing was lost: every row is still queued for the next attempt.
        assert len(store.list_pending(OutboxTable.MUTATIONS, ready_only=False)) == _TASK_COUNT + 1
        assert len(store.list_pending(OutboxTable.EVENTS, ready_only=False)) == len(events)

        # Phase 2: restart (brand-new OutboxStore/StudioApiClient on the same
        # SQLite file) and reconnect to the real API.
        resumed_store = OutboxStore(connect(outbox_path))
        open_stores.append(resumed_store)
        async with StudioApiClient(
            client_config, token_store, transport=app_transport
        ) as online_api:
            online_outcome = await OutboxReplayer(
                resumed_store, online_api, retry_policy
            ).replay_ready()

        assert online_outcome.succeeded == _TASK_COUNT + 1 + len(events)
        assert online_outcome.dead_lettered == 0
        assert online_outcome.stopped_on_transient_error is False
        assert resumed_store.list_pending(OutboxTable.MUTATIONS, ready_only=False) == []
        assert resumed_store.list_pending(OutboxTable.EVENTS, ready_only=False) == []

        # Phase 3: verify real, lossless arrival in Postgres.
        tasks = (
            (await db_session.execute(select(TaskModel).where(TaskModel.project_id == project.id)))
            .scalars()
            .all()
        )
        assert {t.title for t in tasks} == {f"offline-task-{i}" for i in range(_TASK_COUNT)}

        stored_events = (
            (await db_session.execute(select(EventModel).where(EventModel.id.in_(event_ids))))
            .scalars()
            .all()
        )
        assert len(stored_events) == len(events)
        assert {e.machine_id for e in stored_events} == {machine_model.id}

        ai_work_entries = (
            (
                await db_session.execute(
                    select(AIWorkLogModel).where(AIWorkLogModel.project_id == project.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(ai_work_entries) == 1
        assert ai_work_entries[0].agent_id == agent.id
        assert ai_work_entries[0].summary == "offline replay acceptance"
        ai_work_id = ai_work_entries[0].id

        # Phase 4: idempotence — re-enqueue the exact same operations
        # (same ids/keys/payloads) and replay again. Nothing must duplicate.
        replay_store = OutboxStore(connect(outbox_path))
        open_stores.append(replay_store)
        for key, payload in zip(task_keys, task_payloads, strict=True):
            with transaction(replay_store.connection):
                replay_store.enqueue_mutation(key, "task.create", "POST", "/api/v1/tasks", payload)
        for event in events:
            with transaction(replay_store.connection):
                replay_store.enqueue_event(event)
        with transaction(replay_store.connection):
            replay_store.enqueue_mutation(
                ai_work_key, "ai_work.create", "POST", "/api/v1/ai-work", ai_work_payload
            )

        async with StudioApiClient(
            client_config, token_store, transport=app_transport
        ) as replay_api:
            replay_outcome = await OutboxReplayer(
                replay_store, replay_api, retry_policy
            ).replay_ready()

        assert replay_outcome.succeeded == _TASK_COUNT + 1 + len(events)
        assert replay_outcome.dead_lettered == 0

        tasks_after_replay = (
            (await db_session.execute(select(TaskModel).where(TaskModel.project_id == project.id)))
            .scalars()
            .all()
        )
        assert len(tasks_after_replay) == _TASK_COUNT

        events_after_replay = (
            (await db_session.execute(select(EventModel).where(EventModel.id.in_(event_ids))))
            .scalars()
            .all()
        )
        assert len(events_after_replay) == len(events)

        ai_work_after_replay = (
            (
                await db_session.execute(
                    select(AIWorkLogModel).where(AIWorkLogModel.project_id == project.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(ai_work_after_replay) == 1
        assert ai_work_after_replay[0].id == ai_work_id
    finally:
        for open_store in open_stores:
            open_store.connection.close()
        outbox_path.unlink(missing_ok=True)
