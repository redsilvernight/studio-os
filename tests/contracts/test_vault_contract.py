"""`VaultNote` contract shapes: scope/project coherence, bounds, link and update
rules, scope precedence, and the UC-2B hygiene rule (no numbered `DEC-` reference
in a schema description). No DB, no app."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from studio_contracts.vault import (
    VAULT_ANCHORS_MAX,
    VAULT_BODY_MAX,
    VAULT_TAGS_MAX,
    VaultLinkKind,
    VaultNote,
    VaultNoteCreate,
    VaultNoteLink,
    VaultNoteStatus,
    VaultNoteType,
    VaultNoteUpdate,
    VaultNoteVersion,
    VaultScope,
    effective_notes,
    is_valid_slug,
)

PROJECT = uuid4()


def _note(
    slug: str = "a/b",
    scope: VaultScope = VaultScope.STUDIO,
    project_id: UUID | None = None,
    **extra: object,
) -> VaultNote:
    now = datetime.now(UTC)
    fields: dict[str, object] = {
        "id": uuid4(),
        "scope": scope,
        "project_id": project_id,
        "slug": slug,
        "title": "t",
        "body": "b",
        "content_hash": "0" * 64,
        "author_type": "agent",
        "author_id": uuid4(),
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    fields.update(extra)
    return VaultNote(**fields)  # type: ignore[arg-type]


def test_scope_requires_matching_project_id() -> None:
    _note(scope=VaultScope.PROJECT, project_id=PROJECT)
    with pytest.raises(ValidationError):
        _note(scope=VaultScope.PROJECT)
    with pytest.raises(ValidationError):
        _note(scope=VaultScope.STUDIO, project_id=PROJECT)


@pytest.mark.parametrize("slug", ["", "A", "a b", "-a", "a--b", "a/", "/a", "é"])
def test_invalid_slugs_rejected(slug: str) -> None:
    assert not is_valid_slug(slug)
    with pytest.raises(ValidationError):
        _note(slug=slug)


@pytest.mark.parametrize("slug", ["a", "a-b", "a_b", "conventions/git-flow", "x1/y2/z3"])
def test_valid_slugs_accepted(slug: str) -> None:
    assert is_valid_slug(slug)
    assert _note(slug=slug).slug == slug


def test_readable_id_only_for_decisions() -> None:
    _note(note_type=VaultNoteType.DECISION, readable_id="DEC-0001")
    with pytest.raises(ValidationError):
        _note(note_type=VaultNoteType.RULE, readable_id="DEC-0001")


def test_bounds_and_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        _note(body="x" * (VAULT_BODY_MAX + 1))
    with pytest.raises(ValidationError):
        _note(tags=["t"] * (VAULT_TAGS_MAX + 1))
    with pytest.raises(ValidationError):
        _note(content_hash="xyz")
    with pytest.raises(ValidationError):
        _note(unknown=1)


def test_duplicate_links_rejected() -> None:
    target = uuid4()
    link = VaultNoteLink(target_note_id=target, kind=VaultLinkKind.SUPERSEDES)
    with pytest.raises(ValidationError):
        _note(links=[link, link])
    _note(links=[link, VaultNoteLink(target_note_id=target)])


def test_create_status_and_scope() -> None:
    ok = VaultNoteCreate(
        scope=VaultScope.PROJECT, project_id=PROJECT, slug="a", title="t", body="b"
    )
    assert ok.status is VaultNoteStatus.DRAFT
    with pytest.raises(ValidationError):
        VaultNoteCreate(scope=VaultScope.PROJECT, slug="a", title="t", body="b")
    with pytest.raises(ValidationError):
        VaultNoteCreate(
            scope=VaultScope.STUDIO,
            slug="a",
            title="t",
            body="b",
            status=VaultNoteStatus.VALIDATED,
        )


def test_create_rejects_server_assigned_fields() -> None:
    with pytest.raises(ValidationError):
        VaultNoteCreate(
            scope=VaultScope.STUDIO,
            slug="a",
            title="t",
            body="b",
            readable_id="DEC-0001",  # type: ignore[call-arg]
        )


def test_update_needs_version_and_a_change() -> None:
    with pytest.raises(ValidationError):
        VaultNoteUpdate(body="x")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        VaultNoteUpdate(expected_version=1)
    with pytest.raises(ValidationError):
        VaultNoteUpdate(expected_version=0, body="x")
    with pytest.raises(ValidationError):
        VaultNoteUpdate(expected_version=1, slug="other")  # type: ignore[call-arg]
    assert VaultNoteUpdate(expected_version=1, tags=[]).tags == []


def test_roundtrip_json() -> None:
    note = _note(links=[VaultNoteLink(target_note_id=uuid4())])
    assert VaultNote.model_validate_json(note.model_dump_json()) == note
    version = VaultNoteVersion(
        note_id=note.id,
        version=1,
        title="t",
        summary="",
        body="b",
        status=VaultNoteStatus.DRAFT,
        content_hash="0" * 64,
        author_type="user",  # type: ignore[arg-type]
        author_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    assert VaultNoteVersion.model_validate_json(version.model_dump_json()) == version


@pytest.mark.parametrize(
    "anchor",
    [
        "task:1b4a9aa7-f8e3-454a-a20a-1f5da4de82aa",
        "path:services/api/src/x.py",
        "path:services/",
        "path:a",
    ],
)
def test_valid_anchors_accepted(anchor: str) -> None:
    assert _note(anchors=[anchor]).anchors == [anchor]


@pytest.mark.parametrize(
    "anchor",
    [
        "task:not-a-uuid",
        "task:7DDA69C2-191B-4F4F-998A-9F526090E045",
        "task: ed10ca78-5bbf-4b98-8ef1-1b8a3c8f507c",
        "path:",
        "path:a b",
        "path:a\\b",
        "services/api/src/x.py",
    ],
)
def test_invalid_anchors_rejected(anchor: str) -> None:
    with pytest.raises(ValidationError):
        _note(anchors=[anchor])


def test_duplicate_anchors_rejected() -> None:
    anchor = "path:services/"
    with pytest.raises(ValidationError):
        _note(anchors=[anchor, anchor])


def test_anchors_are_bounded() -> None:
    anchors = [f"path:dir{i}/" for i in range(VAULT_ANCHORS_MAX + 1)]
    with pytest.raises(ValidationError):
        _note(anchors=anchors)


def test_project_note_prevails_over_studio_note() -> None:
    studio = _note(slug="a")
    project = _note(slug="a", scope=VaultScope.PROJECT, project_id=PROJECT)
    other = _note(slug="a", scope=VaultScope.PROJECT, project_id=uuid4())
    only_studio = _note(slug="b")
    notes = [studio, other, project, only_studio]
    assert effective_notes(notes, PROJECT) == [project, only_studio]
    assert effective_notes(list(reversed(notes)), PROJECT) == [project, only_studio]
    assert effective_notes(notes, None) == [studio, only_studio]


def test_archived_notes_are_not_effective() -> None:
    studio = _note(slug="a")
    archived = _note(
        slug="a",
        scope=VaultScope.PROJECT,
        project_id=PROJECT,
        status=VaultNoteStatus.ARCHIVED,
    )
    assert effective_notes([studio, archived], PROJECT) == [studio]


def test_schema_descriptions_carry_no_numbered_decision_reference() -> None:
    for model in (VaultNote, VaultNoteCreate, VaultNoteUpdate, VaultNoteVersion, VaultNoteLink):
        assert not re.search(r"DEC-\d", json.dumps(model.model_json_schema()))
