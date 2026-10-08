"""P08 (DEC-0192): replayable import of the ADR files and server decisions
into vault decision notes."""

from __future__ import annotations

import random
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.vault import VaultNoteModel, VaultNoteVersionModel
from studio_api.services import vault_decision_import as imp
from studio_contracts.vault import VaultNoteStatus, VaultScope

REPO = Path(__file__).resolve().parents[2]
DECISIONS_DIR = REPO / "docs" / "decisions"
SNAPSHOT = REPO / "docs" / "DEC_BASELINE_P00.json"


def _dec(
    readable_id: str,
    title: str,
    *,
    origin: str,
    status: str | None = "accepted",
    project_id: uuid.UUID | None = None,
    body: str = "Contexte.\n\nDécision.",
) -> imp.SourceDecision:
    return imp.SourceDecision(
        readable_id=readable_id,
        title=title,
        body=body,
        raw_status=status,
        project_id=project_id,
        origin=origin,
        path=f"decisions/{readable_id}.md" if origin == "file" else None,
    )


# ---------------------------------------------------------------- pure


def test_frontmatter_reader_matches_yaml_on_every_adr() -> None:
    yaml = pytest.importorskip("yaml")
    paths = [p for p in sorted(DECISIONS_DIR.glob("*.md")) if not p.name.startswith("_")]
    assert len(paths) > 100
    for path in paths:
        source = path.read_text(encoding="utf-8")
        fields, _ = imp.parse_frontmatter(source)
        expected = yaml.safe_load(source.split("---\n", 2)[1])
        for key in ("id", "title", "status", "server_readable_id"):
            value = expected.get(key)
            assert fields.get(key) == (None if value is None else str(value)), (path.name, key)


def test_same_number_same_decision_keeps_file_and_reports_gaps() -> None:
    project_id = uuid.uuid4()
    plan = imp.plan_import(
        [_dec("DEC-0001", "Layout du depot : monorepo uv", origin="file", project_id=project_id)],
        [
            _dec(
                "DEC-0001",
                "DEC-0001 — Layout du dépôt : monorepo uv",
                origin="server",
                status="proposed",
                project_id=project_id,
                body="autre corps",
            )
        ],
    )
    assert len(plan.notes) == 1
    note = plan.notes[0]
    assert (note.readable_id, note.origin, note.status) == (
        "DEC-0001",
        "file",
        VaultNoteStatus.VALIDATED,
    )
    assert note.body == "Contexte.\n\nDécision."
    assert note.slug == "decisions/dec-0001-layout-du-depot-monorepo-uv"
    assert note.summary == "Contexte."
    assert {f.kind for f in plan.findings} == {"status"}


def test_collision_imports_server_variant_without_number() -> None:
    project_id = uuid.uuid4()
    plan = imp.plan_import(
        [_dec("DEC-0100", "Workflow W2b : setup-hooks", origin="file", project_id=project_id)],
        [_dec("DEC-0100", "DU-0/C — Chaîne proxy de confiance", origin="server")],
    )
    numbered = [n for n in plan.notes if n.readable_id is not None]
    legacy = [n for n in plan.notes if n.readable_id is None]
    assert [n.origin for n in numbered] == ["file"]
    assert len(legacy) == 1
    assert legacy[0].scope is VaultScope.STUDIO
    assert legacy[0].slug.startswith("decisions/legacy-server/dec-0100-")
    assert "legacy-server-dec-0100" in legacy[0].tags
    assert [f.kind for f in plan.findings] == ["collision"]


def test_reviewed_same_decision_is_not_a_collision() -> None:
    plan = imp.plan_import(
        [_dec("DEC-0056", "Dashboard human authentication with JWT (DASH-4)", origin="file")],
        [
            _dec(
                "DEC-0056",
                "Authentification humaine du dashboard par JWT (DASH-4)",
                origin="server",
            )
        ],
    )
    assert [n.readable_id for n in plan.notes] == ["DEC-0056"]
    assert "collision" not in {f.kind for f in plan.findings}


def test_missing_file_status_falls_back_to_server() -> None:
    plan = imp.plan_import(
        [_dec("DEC-0014", "Docker Desktop installe", origin="file", status=None)],
        [_dec("DEC-0014", "Docker Desktop installé", origin="server", status="accepted")],
    )
    assert plan.notes[0].status is VaultNoteStatus.VALIDATED
    assert [f.kind for f in plan.findings] == ["missing_status"]


def test_server_only_keeps_number_and_project_scope() -> None:
    project_id = uuid.uuid4()
    plan = imp.plan_import(
        [],
        [
            _dec("DEC-0191", "Projet", origin="server", project_id=project_id),
            _dec("DEC-0190", "Studio", origin="server", status="superseded"),
        ],
    )
    by_id = {n.readable_id: n for n in plan.notes}
    assert (by_id["DEC-0191"].scope, by_id["DEC-0191"].project_id) == (
        VaultScope.PROJECT,
        project_id,
    )
    assert by_id["DEC-0190"].scope is VaultScope.STUDIO
    assert by_id["DEC-0190"].status is VaultNoteStatus.SUPERSEDED
    assert plan.max_number == 191


def test_url_password_is_dropped_not_the_note() -> None:
    body = "DSN `postgresql+asyncpg://studio:studio@localhost:5432/db` de test."
    plan = imp.plan_import([_dec("DEC-0010", "Tests", origin="file", body=body)], [])
    assert plan.notes[0].body == "DSN `postgresql+asyncpg://studio@localhost:5432/db` de test."
    assert {f.kind for f in plan.findings} == {"redacted", "file_only"}


def test_real_sources_give_every_adr_its_number() -> None:
    project_id = uuid.UUID("2a836038-153c-41cf-879a-73bd794760b0")
    files, findings = imp.load_file_decisions(DECISIONS_DIR, project_id)
    plan = imp.plan_import(files, imp.load_server_snapshot(SNAPSHOT))
    assert findings == []
    numbered = {n.readable_id: n for n in plan.notes if n.readable_id is not None}
    assert len(numbered) == sum(1 for n in plan.notes if n.readable_id is not None)
    for decision in files:
        assert numbered[decision.readable_id].origin == "file", decision.readable_id
    identities = [(n.scope, n.project_id, n.slug) for n in plan.notes]
    assert len(identities) == len(set(identities))
    assert "skipped" not in {f.kind for f in plan.findings}


def test_render_report_lists_every_section() -> None:
    plan = imp.plan_import(
        [_dec("DEC-0100", "A", origin="file")],
        [_dec("DEC-0100", "Zzz tout autre", origin="server")],
    )
    report = imp.render_report(plan)
    assert "## Collisions de numéro (décisions différentes) (1)" in report
    assert "DEC-0192" in report


# ---------------------------------------------------------------- database


def _unique_ids(count: int) -> list[str]:
    # Seven digits: far above any real or sequence-issued number, so the rows
    # never meet a note another test committed.
    base = random.randint(8_000_000, 8_900_000)
    return [f"DEC-{base + i}" for i in range(count)]


@pytest.fixture
def frozen_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(session: AsyncSession, floor: int) -> int:
        return floor + 1

    monkeypatch.setattr(imp, "_advance_sequence", _noop)


async def _count(session: AsyncSession, model: type, *where: object) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one()
    )


async def test_apply_is_replayable_without_duplicates(
    db_session: AsyncSession, project: ProjectModel, frozen_sequence: None
) -> None:
    first, collided = _unique_ids(2)
    plan = imp.plan_import(
        [
            _dec(first, "Alpha", origin="file", project_id=project.id),
            _dec(collided, "Beta fichier", origin="file", project_id=project.id),
        ],
        [_dec(collided, "Gamma serveur tout autre", origin="server", project_id=project.id)],
    )
    author = uuid.uuid4()

    created = await imp.apply_plan(db_session, plan, author)
    assert len(created.created) == 3
    replay = await imp.apply_plan(db_session, plan, author)
    assert (len(replay.created), len(replay.unchanged), replay.drifted) == (0, 3, [])

    notes = (
        (
            await db_session.execute(
                select(VaultNoteModel).where(VaultNoteModel.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(n.readable_id or "-" for n in notes) == sorted([first, collided, "-"])
    assert {n.note_type for n in notes} == {"decision"}
    assert {n.author_type for n in notes} == {"system"}
    versions = await _count(
        db_session,
        VaultNoteVersionModel,
        VaultNoteVersionModel.note_id.in_([n.id for n in notes]),
    )
    assert versions == 3


async def test_apply_reports_drift_and_never_overwrites(
    db_session: AsyncSession, project: ProjectModel, frozen_sequence: None
) -> None:
    (readable_id,) = _unique_ids(1)
    original = imp.plan_import(
        [_dec(readable_id, "Alpha", origin="file", project_id=project.id)], []
    )
    await imp.apply_plan(db_session, original, uuid.uuid4())

    edited = imp.plan_import(
        [_dec(readable_id, "Alpha", origin="file", project_id=project.id, body="Nouveau corps")], []
    )
    result = await imp.apply_plan(db_session, edited, uuid.uuid4())
    assert result.created == [] and len(result.drifted) == 1
    note = (
        await db_session.execute(
            select(VaultNoteModel).where(VaultNoteModel.readable_id == readable_id)
        )
    ).scalar_one()
    assert note.body == "Contexte.\n\nDécision."
    assert note.version == 1


async def test_sequence_moves_past_the_highest_number_never_back(db_session: AsyncSession) -> None:
    last_value, is_called = (
        await db_session.execute(
            text("SELECT last_value, is_called FROM decisions_readable_id_seq")
        )
    ).one()
    current_next = last_value + 1 if is_called else last_value

    assert await imp._advance_sequence(db_session, 1) >= current_next

    floor = current_next + 2
    assert await imp._advance_sequence(db_session, floor) == floor + 1
    issued = (
        await db_session.execute(text("SELECT nextval('decisions_readable_id_seq')"))
    ).scalar_one()
    assert issued == floor + 1


async def test_real_sources_apply_twice_without_duplicates(
    db_session: AsyncSession, project: ProjectModel, frozen_sequence: None
) -> None:
    project_id = project.id
    snapshot = [
        d
        if d.project_id is None
        else imp.SourceDecision(**{**d.__dict__, "project_id": project_id})
        for d in imp.load_server_snapshot(SNAPSHOT)
    ]
    files, _ = imp.load_file_decisions(DECISIONS_DIR, project_id)
    plan = imp.plan_import(files, snapshot)
    clash = (
        await db_session.execute(
            select(func.count())
            .select_from(VaultNoteModel)
            .where(
                VaultNoteModel.readable_id.in_([n.readable_id for n in plan.notes if n.readable_id])
            )
        )
    ).scalar_one()
    if clash:
        pytest.skip("test database already holds vault notes with historical DEC numbers")

    first = await imp.apply_plan(db_session, plan, uuid.uuid4())
    second = await imp.apply_plan(db_session, plan, uuid.uuid4())
    assert (len(first.created), first.conflicts) == (len(plan.notes), [])
    assert (len(second.created), len(second.unchanged), second.drifted) == (0, len(plan.notes), [])
