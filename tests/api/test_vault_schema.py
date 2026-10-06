from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.vault import (
    VaultNoteLinkModel,
    VaultNoteModel,
    VaultNoteVersionModel,
)

TEST_DATABASE_URL = os.environ.get(
    "STUDIO_TEST_DATABASE_URL",
    "postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test",
)


def _note(**overrides: object) -> VaultNoteModel:
    fields: dict[str, object] = {
        "scope": "studio",
        "slug": f"note-{uuid.uuid4().hex[:8]}",
        "title": "Titre",
        "summary": "",
        "body": "Corps",
        "content_hash": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        "author_type": "user",
        "author_id": uuid.uuid4(),
    }
    fields.update(overrides)
    return VaultNoteModel(**fields)


async def _rejected(session: AsyncSession, note: VaultNoteModel) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(note)
            await session.flush()


async def test_note_defaults(db_session: AsyncSession) -> None:
    note = _note()
    db_session.add(note)
    await db_session.flush()
    await db_session.refresh(note)
    assert (note.version, note.status, note.note_type) == (1, "draft", "note")
    assert note.tags == []
    assert note.readable_id is None


async def test_scope_requires_matching_project(
    db_session: AsyncSession, project: ProjectModel
) -> None:
    await _rejected(db_session, _note(scope="project", project_id=None))
    await _rejected(db_session, _note(scope="studio", project_id=project.id))
    await _rejected(db_session, _note(scope="team"))
    db_session.add(_note(scope="project", project_id=project.id))
    await db_session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"note_type": "essay"},
        {"status": "deleted"},
        {"author_type": "robot"},
        {"content_hash": "abc"},
        {"version": 0},
    ],
)
async def test_value_constraints(db_session: AsyncSession, overrides: dict[str, object]) -> None:
    await _rejected(db_session, _note(**overrides))


async def test_slug_unique_per_scope_outside_archived(
    db_session: AsyncSession, project: ProjectModel
) -> None:
    other = ProjectModel(slug=f"other-{uuid.uuid4().hex[:8]}", name="Other")
    db_session.add(other)
    await db_session.flush()

    db_session.add_all(
        [
            _note(slug="regle", scope="studio"),
            _note(slug="regle", scope="project", project_id=project.id),
            _note(slug="regle", scope="project", project_id=other.id),
        ]
    )
    await db_session.flush()

    await _rejected(db_session, _note(slug="regle", scope="studio"))
    await _rejected(db_session, _note(slug="regle", scope="project", project_id=project.id))

    archived = await db_session.scalar(
        select(VaultNoteModel).where(
            VaultNoteModel.slug == "regle", VaultNoteModel.scope == "studio"
        )
    )
    assert archived is not None
    archived.status = "archived"
    await db_session.flush()
    db_session.add(_note(slug="regle", scope="studio"))
    await db_session.flush()


async def test_readable_id_only_for_decisions_and_unique(db_session: AsyncSession) -> None:
    await _rejected(db_session, _note(readable_id="DEC-9001", note_type="rule"))
    db_session.add(_note(readable_id="DEC-9001", note_type="decision"))
    await db_session.flush()
    await _rejected(db_session, _note(readable_id="DEC-9001", note_type="decision"))


async def test_search_vector_is_generated_and_stemmed(db_session: AsyncSession) -> None:
    note = _note(title="Décisions unifiées", summary="résumé", body="Les chemins relatifs")
    other = _note(title="Autre", body="rien")
    db_session.add_all([note, other])
    await db_session.flush()

    found = (
        await db_session.scalars(
            select(VaultNoteModel.id).where(
                VaultNoteModel.search_vector.op("@@")(text("plainto_tsquery('french', 'décision')"))
            )
        )
    ).all()
    assert note.id in found
    assert other.id not in found

    note.body = "autre contenu"
    await db_session.flush()
    stale = (
        await db_session.scalars(
            select(VaultNoteModel.id).where(
                VaultNoteModel.search_vector.op("@@")(text("plainto_tsquery('french', 'chemin')")),
                VaultNoteModel.id == note.id,
            )
        )
    ).all()
    assert stale == []


async def test_links_are_typed_unique_and_not_reflexive(db_session: AsyncSession) -> None:
    a, b = _note(), _note()
    db_session.add_all([a, b])
    await db_session.flush()

    db_session.add_all(
        [
            VaultNoteLinkModel(source_note_id=a.id, target_note_id=b.id, kind="links_to"),
            VaultNoteLinkModel(source_note_id=a.id, target_note_id=b.id, kind="supersedes"),
        ]
    )
    await db_session.flush()

    for bad in (
        VaultNoteLinkModel(source_note_id=a.id, target_note_id=b.id, kind="links_to"),
        VaultNoteLinkModel(source_note_id=a.id, target_note_id=a.id, kind="links_to"),
        VaultNoteLinkModel(source_note_id=a.id, target_note_id=b.id, kind="mentions"),
        VaultNoteLinkModel(source_note_id=a.id, target_note_id=uuid.uuid4(), kind="relates_to"),
    ):
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                db_session.add(bad)
                await db_session.flush()


async def test_versions_are_keyed_by_note_and_version(db_session: AsyncSession) -> None:
    note = _note()
    db_session.add(note)
    await db_session.flush()

    def version(number: int) -> VaultNoteVersionModel:
        return VaultNoteVersionModel(
            note_id=note.id,
            version=number,
            title="Titre",
            body="Corps",
            status="draft",
            links=[{"target_note_id": str(uuid.uuid4()), "kind": "links_to"}],
            content_hash=note.content_hash,
            author_type="user",
            author_id=note.author_id,
        )

    db_session.add_all([version(1), version(2)])
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(version(2))
            await db_session.flush()


async def test_deleting_a_note_removes_links_and_versions(db_session: AsyncSession) -> None:
    a, b = _note(), _note()
    db_session.add_all([a, b])
    await db_session.flush()
    db_session.add(VaultNoteLinkModel(source_note_id=a.id, target_note_id=b.id, kind="links_to"))
    db_session.add(
        VaultNoteVersionModel(
            note_id=a.id,
            version=1,
            title="t",
            body="b",
            status="draft",
            content_hash=a.content_hash,
            author_type="user",
            author_id=a.author_id,
        )
    )
    await db_session.flush()

    await db_session.execute(delete(VaultNoteModel).where(VaultNoteModel.id == a.id))
    assert await db_session.scalar(select(VaultNoteLinkModel.source_note_id)) is None
    assert await db_session.scalar(select(VaultNoteVersionModel.note_id)) is None


@pytest_asyncio.fixture
async def real_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL, pool_size=20, max_overflow=0)
    yield engine
    await engine.dispose()


async def test_concurrent_decision_numbers_never_collide_across_tables(
    real_engine: AsyncEngine,
) -> None:
    """The server sequence is the single source of DEC numbers: concurrent
    creations through `decisions` and `vault_notes` (independent transactions)
    never produce the same readable_id."""
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    async with session_factory() as setup:
        setup.add(ProjectModel(id=project_id, slug=f"vault-{uuid.uuid4().hex[:8]}", name="Vault"))
        await setup.commit()

    async def _next_id(session: AsyncSession) -> str:
        value = (
            await session.execute(text("SELECT nextval('decisions_readable_id_seq')"))
        ).scalar_one()
        return f"DEC-{value:04d}"

    async def _create(index: int) -> str:
        async with session_factory() as session:
            readable_id = await _next_id(session)
            if index % 2:
                session.add(
                    _note(
                        scope="project",
                        project_id=project_id,
                        note_type="decision",
                        readable_id=readable_id,
                    )
                )
            else:
                session.add(
                    DecisionModel(
                        readable_id=readable_id,
                        project_id=project_id,
                        title=f"Concurrent {index}",
                        body="Body",
                        proposed_by_type="agent",
                        proposed_by_id=uuid.uuid4(),
                    )
                )
            await session.commit()
            return readable_id

    concurrency = 12
    try:
        ids = await asyncio.gather(*(_create(i) for i in range(concurrency)))
        assert len(set(ids)) == concurrency
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(
                delete(VaultNoteModel).where(VaultNoteModel.project_id == project_id)
            )
            await cleanup.execute(
                delete(DecisionModel).where(DecisionModel.project_id == project_id)
            )
            await cleanup.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
            await cleanup.commit()
