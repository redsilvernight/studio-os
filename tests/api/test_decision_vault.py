from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.db.models.vault import (
    VaultNoteLinkModel,
    VaultNoteModel,
    VaultNoteVersionModel,
)
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service

TEST_DATABASE_URL = os.environ.get(
    "STUDIO_TEST_DATABASE_URL",
    "postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test",
)


@pytest_asyncio.fixture
async def real_engine() -> AsyncIterator[AsyncEngine]:
    """Separate real, independently-committing connections per request — see the
    identical fixture in test_decisions_concurrency.py for why a
    savepoint-nested session (tests.api.conftest.db_session) cannot reproduce a
    race that only exists *across* Postgres transactions."""
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


async def _create_decision(
    client: AsyncClient,
    headers: dict[str, str],
    machine_id: uuid.UUID,
    project_id: uuid.UUID | None,
    title: str = "A decision worth keeping in the vault",
    body: str = "Server-Sent Events over WebSocket.",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/decisions",
        headers=headers,
        json={
            "project_id": str(project_id) if project_id is not None else None,
            "title": title,
            "body": body,
            "proposed_by_type": "agent",
            "proposed_by_id": str(machine_id),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _note_of(session: AsyncSession, decision: dict[str, object]) -> VaultNoteModel | None:
    """The vault note mirroring a decision, keyed by the readable id it shares
    with it — the only natural key between the two tables."""
    readable_id = str(decision["readable_id"])
    return (
        (
            await session.execute(
                select(VaultNoteModel).where(VaultNoteModel.readable_id == readable_id)
            )
        )
        .scalars()
        .first()
    )


async def _decision_with_note(
    client: AsyncClient,
    headers: dict[str, str],
    machine_id: uuid.UUID,
    project_id: uuid.UUID | None,
    session: AsyncSession,
    *,
    title: str = "A decision worth keeping in the vault",
) -> dict[str, object]:
    decision = await _create_decision(client, headers, machine_id, project_id, title=title)
    assert await _note_of(session, decision) is not None
    return decision


async def _history(session: AsyncSession, note_id: uuid.UUID) -> list[tuple[int, str]]:
    rows = (
        await session.execute(
            select(VaultNoteVersionModel.version, VaultNoteVersionModel.status)
            .where(VaultNoteVersionModel.note_id == note_id)
            .order_by(VaultNoteVersionModel.version.asc())
        )
    ).all()
    return [(row.version, row.status) for row in rows]


async def _links_of(session: AsyncSession, note_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    rows = (
        await session.execute(
            select(VaultNoteLinkModel.target_note_id, VaultNoteLinkModel.kind).where(
                VaultNoteLinkModel.source_note_id == note_id
            )
        )
    ).all()
    return [(row.target_note_id, row.kind) for row in rows]


async def test_create_decision_writes_a_proposed_project_note(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    """`POST /decisions` also records the decision in the vault: a numbered
    `decision` note, `proposed`, scoped to its project, with its first version."""
    machine_model, _ = machine
    decision = await _decision_with_note(
        client, auth_headers, machine_model.id, project.id, db_session
    )

    note = await _note_of(db_session, decision)
    assert note is not None
    assert note.note_type == "decision"
    assert note.readable_id == decision["readable_id"]
    assert note.status == "proposed"
    assert note.scope == "project"
    assert note.project_id == project.id
    assert note.slug.startswith(f"decisions/{str(decision['readable_id']).lower()}")
    assert note.version == 1
    assert await _history(db_session, note.id) == [(1, "proposed")]


async def test_create_global_decision_writes_a_studio_scoped_note(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    """A project-less (global) decision gets a `studio` note — the scope mirrors
    the decision, it never invents a project."""
    machine_model, _ = machine
    decision = await _decision_with_note(client, auth_headers, machine_model.id, None, db_session)

    note = await _note_of(db_session, decision)
    assert note is not None
    assert note.scope == "studio"
    assert note.project_id is None
    assert note.status == "proposed"
    assert note.slug.startswith(f"decisions/{str(decision['readable_id']).lower()}")
    assert note.version == 1


async def test_accept_validates_the_note_and_appends_a_second_version(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    decision = await _decision_with_note(
        client, auth_headers, machine_model.id, project.id, db_session
    )

    accepted = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers
    )
    assert accepted.status_code == 200, accepted.text

    note = await _note_of(db_session, decision)
    assert note is not None
    assert note.status == "validated"
    assert note.version == 2
    assert await _history(db_session, note.id) == [(1, "proposed"), (2, "validated")]


async def test_supersede_marks_the_note_superseded(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    decision = await _decision_with_note(
        client, auth_headers, machine_model.id, project.id, db_session
    )

    superseded = await client.post(
        f"/api/v1/decisions/{decision['id']}/supersede", headers=admin_auth_headers
    )
    assert superseded.status_code == 200, superseded.text

    note = await _note_of(db_session, decision)
    assert note is not None
    assert note.status == "superseded"


async def test_supersede_with_replacement_links_the_replacement_note(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    """`superseded_by` records *who replaces* the decision: the replacement's
    note carries a `supersedes` link to the superseded one."""
    machine_model, _ = machine
    replaced = await _decision_with_note(
        client, auth_headers, machine_model.id, project.id, db_session, title="The old way"
    )
    replacement = await _decision_with_note(
        client, auth_headers, machine_model.id, project.id, db_session, title="The new way"
    )

    response = await client.post(
        f"/api/v1/decisions/{replaced['id']}/supersede",
        headers=admin_auth_headers,
        json={"superseded_by": str(replacement["id"])},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "superseded"

    replaced_note = await _note_of(db_session, replaced)
    replacement_note = await _note_of(db_session, replacement)
    assert replaced_note is not None
    assert replacement_note is not None
    assert replaced_note.status == "superseded"
    assert (replaced_note.id, "supersedes") in await _links_of(db_session, replacement_note.id)


async def test_supersede_with_unknown_replacement_is_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    decision = await _decision_with_note(
        client, auth_headers, machine_model.id, project.id, db_session
    )

    response = await client.post(
        f"/api/v1/decisions/{decision['id']}/supersede",
        headers=admin_auth_headers,
        json={"superseded_by": str(uuid.uuid4())},
    )
    assert response.status_code == 404

    note = await _note_of(db_session, decision)
    assert note is not None
    assert note.status == "proposed"


async def test_supersede_by_itself_is_422(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    """A note can never supersede itself (`ck_vault_note_links_no_self`)."""
    machine_model, _ = machine
    decision = await _decision_with_note(
        client, auth_headers, machine_model.id, project.id, db_session
    )

    response = await client.post(
        f"/api/v1/decisions/{decision['id']}/supersede",
        headers=admin_auth_headers,
        json={"superseded_by": str(decision["id"])},
    )
    assert response.status_code == 422

    note = await _note_of(db_session, decision)
    assert note is not None
    assert note.status == "proposed"


async def test_accept_rebuilds_a_deleted_note_at_the_target_status(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    """A decision whose note went missing (a manual cleanup, an import
    replay) is healed by the next transition: the note comes back already at
    the target status."""
    machine_model, _ = machine
    decision = await _decision_with_note(
        client, auth_headers, machine_model.id, project.id, db_session
    )
    note = await _note_of(db_session, decision)
    assert note is not None

    deleted = await db_session.execute(delete(VaultNoteModel).where(VaultNoteModel.id == note.id))
    assert deleted.rowcount == 1
    assert await _note_of(db_session, decision) is None

    accepted = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers
    )
    assert accepted.status_code == 200, accepted.text

    rebuilt = await _note_of(db_session, decision)
    assert rebuilt is not None
    assert rebuilt.note_type == "decision"
    assert rebuilt.readable_id == decision["readable_id"]
    assert rebuilt.status == "validated"
    assert rebuilt.scope == "project"
    assert rebuilt.project_id == project.id


async def test_concurrent_decisions_each_keep_their_own_note(
    real_engine: AsyncEngine, real_client: AsyncClient
) -> None:
    """Each concurrent creation owns its numbered note: distinct readable ids
    mean distinct notes, never a shared or overwritten one."""
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as setup_session:
        user = await provisioning_service.create_user(
            setup_session,
            "Decision Vault Concurrency User",
            f"{uuid.uuid4()}@example.test",
            "developer",
        )
        machine, token = await provisioning_service.create_machine(
            setup_session, user.id, "decision-vault-concurrency-machine"
        )
        project = await projects_service.create_project(
            setup_session,
            f"dec-vault-concurrency-{uuid.uuid4().hex[:8]}",
            "Decision Vault Concurrency",
            None,
            creator=None,
        )

    headers = {"Authorization": f"Bearer {token}"}
    concurrency = 10

    try:
        await _warm_pool(session_factory, concurrency)
        responses = await asyncio.gather(
            *(
                real_client.post(
                    "/api/v1/decisions",
                    headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
                    json={
                        "project_id": str(project.id),
                        "title": f"Concurrent decision {i}",
                        "body": "Body",
                        "proposed_by_type": "agent",
                        "proposed_by_id": str(machine.id),
                    },
                )
                for i in range(concurrency)
            )
        )

        for response in responses:
            assert response.status_code == 201, response.text
        decisions = [response.json() for response in responses]
        readable_ids = [decision["readable_id"] for decision in decisions]
        assert len(set(readable_ids)) == concurrency, readable_ids

        async with session_factory() as check_session:
            notes = (
                (
                    await check_session.execute(
                        select(VaultNoteModel).where(VaultNoteModel.readable_id.in_(readable_ids))
                    )
                )
                .scalars()
                .all()
            )
            assert len(notes) == concurrency
            notes_by_readable_id = {note.readable_id: note for note in notes}
            assert set(notes_by_readable_id) == set(readable_ids)
            for decision in decisions:
                note = notes_by_readable_id[str(decision["readable_id"])]
                assert note.note_type == "decision"
                assert note.status == "proposed"
                assert note.scope == "project"
                assert note.project_id == project.id
                assert note.version == 1
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                delete(VaultNoteModel).where(VaultNoteModel.project_id == project.id)
            )
            await cleanup_session.execute(
                delete(DecisionModel).where(DecisionModel.project_id == project.id)
            )
            await cleanup_session.execute(delete(ProjectModel).where(ProjectModel.id == project.id))
            await cleanup_session.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup_session.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup_session.commit()
