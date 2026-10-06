from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel

VAULT_SLUG_PATTERN = r"^[a-z0-9]+(?:[-_/][a-z0-9]+)*$"
VAULT_SLUG_MAX = 200
VAULT_TITLE_MAX = 200
VAULT_SUMMARY_MAX = 600
VAULT_BODY_MAX = 262_144
VAULT_TAGS_MAX = 20
VAULT_TAG_MAX = 48
VAULT_LINKS_MAX = 200

VaultSlug = Annotated[
    str,
    StringConstraints(min_length=1, max_length=VAULT_SLUG_MAX, pattern=VAULT_SLUG_PATTERN),
]
VaultTag = Annotated[
    str,
    StringConstraints(min_length=1, max_length=VAULT_TAG_MAX, pattern=r"^[a-z0-9][a-z0-9_.-]*$"),
]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

_SLUG_RE = re.compile(VAULT_SLUG_PATTERN)


class VaultScope(StrEnum):
    """Where a note lives. `studio` notes are transverse to every project of the
    studio; `project` notes belong to exactly one project."""

    STUDIO = "studio"
    PROJECT = "project"


class VaultNoteType(StrEnum):
    DECISION = "decision"
    RULE = "rule"
    CONVENTION = "convention"
    PROCEDURE = "procedure"
    REFERENCE = "reference"
    LESSON = "lesson"
    NOTE = "note"


class VaultNoteStatus(StrEnum):
    """Lifecycle of a note. A decision note maps one-to-one onto the existing
    decision statuses: `proposed` -> `proposed`, `accepted` -> `validated`,
    `superseded` -> `superseded`."""

    DRAFT = "draft"
    PROPOSED = "proposed"
    VALIDATED = "validated"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class VaultLinkKind(StrEnum):
    LINKS_TO = "links_to"
    RELATES_TO = "relates_to"
    DERIVED_FROM = "derived_from"
    SUPERSEDES = "supersedes"


class VaultActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class VaultNoteLink(ContractModel):
    """A typed, directed link from a note to another note of the same studio.
    The target may live in the other scope."""

    target_note_id: UUID
    kind: VaultLinkKind = VaultLinkKind.LINKS_TO


def _check_scope(scope: VaultScope, project_id: UUID | None) -> None:
    if scope is VaultScope.PROJECT and project_id is None:
        raise ValueError("a project note carries a project_id")
    if scope is VaultScope.STUDIO and project_id is not None:
        raise ValueError("a studio note carries no project_id")


def _check_unique_links(links: Sequence[VaultNoteLink]) -> None:
    pairs = [(link.target_note_id, link.kind) for link in links]
    if len(set(pairs)) != len(pairs):
        raise ValueError("a link (target, kind) appears at most once")


class VaultNote(VersionedModel):
    """A vault note, the unit of knowledge stored by the server.

    Identity: `id` is stable; `(scope, project_id, slug)` is unique among notes
    that are not archived. `readable_id` is assigned by the server, never by the
    client, and only for numbered note types (a decision gets its readable identifier);
    it is `None` for every other type.

    Concurrency: `version` starts at 1 and grows by one on each accepted write;
    a write carries `expected_version` and a stale one is a 409 carrying the
    server version. Every accepted write appends a `VaultNoteVersion`.

    Precedence: for the same `slug`, the project note prevails over the studio
    note within that project (see `effective_notes`)."""

    id: UUID
    scope: VaultScope
    project_id: UUID | None = None
    slug: VaultSlug
    readable_id: str | None = None
    note_type: VaultNoteType = VaultNoteType.NOTE
    title: str = Field(min_length=1, max_length=VAULT_TITLE_MAX)
    summary: str = Field(default="", max_length=VAULT_SUMMARY_MAX)
    body: str = Field(max_length=VAULT_BODY_MAX)
    status: VaultNoteStatus = VaultNoteStatus.DRAFT
    tags: list[VaultTag] = Field(default_factory=list, max_length=VAULT_TAGS_MAX)
    links: list[VaultNoteLink] = Field(default_factory=list, max_length=VAULT_LINKS_MAX)
    content_hash: Sha256Hex
    author_type: VaultActorType
    author_id: UUID

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        _check_scope(self.scope, self.project_id)
        _check_unique_links(self.links)
        if self.readable_id is not None and self.note_type is not VaultNoteType.DECISION:
            raise ValueError("only a decision note carries a readable_id")
        return self


class VaultNoteCreate(IdempotentCreate):
    """Creation payload. The server assigns `id`, `readable_id`, `version`,
    `content_hash` and the author (from the authenticated actor). A new note
    starts as `draft`, or `proposed` when the client asks for validation."""

    scope: VaultScope
    project_id: UUID | None = None
    slug: VaultSlug
    note_type: VaultNoteType = VaultNoteType.NOTE
    title: str = Field(min_length=1, max_length=VAULT_TITLE_MAX)
    summary: str = Field(default="", max_length=VAULT_SUMMARY_MAX)
    body: str = Field(max_length=VAULT_BODY_MAX)
    status: VaultNoteStatus = VaultNoteStatus.DRAFT
    tags: list[VaultTag] = Field(default_factory=list, max_length=VAULT_TAGS_MAX)
    links: list[VaultNoteLink] = Field(default_factory=list, max_length=VAULT_LINKS_MAX)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        _check_scope(self.scope, self.project_id)
        _check_unique_links(self.links)
        if self.status not in (VaultNoteStatus.DRAFT, VaultNoteStatus.PROPOSED):
            raise ValueError("a note is created as draft or proposed")
        return self


class VaultNoteUpdate(ContractModel):
    """Partial write on an existing note. `expected_version` is mandatory.
    Scope, project and slug never change; moving a note is a new note plus a
    `supersedes` link. Absent fields are left untouched; `tags` and `links`
    replace the whole list when present."""

    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=VAULT_TITLE_MAX)
    summary: str | None = Field(default=None, max_length=VAULT_SUMMARY_MAX)
    body: str | None = Field(default=None, max_length=VAULT_BODY_MAX)
    status: VaultNoteStatus | None = None
    tags: list[VaultTag] | None = Field(default=None, max_length=VAULT_TAGS_MAX)
    links: list[VaultNoteLink] | None = Field(default=None, max_length=VAULT_LINKS_MAX)
    change_summary: str | None = Field(default=None, max_length=VAULT_SUMMARY_MAX)

    @model_validator(mode="after")
    def _changes_something(self) -> Self:
        changed = (
            self.title,
            self.summary,
            self.body,
            self.status,
            self.tags,
            self.links,
        )
        if all(value is None for value in changed):
            raise ValueError("an update changes at least one field")
        if self.links is not None:
            _check_unique_links(self.links)
        return self


class VaultNoteVersion(ContractModel):
    """One immutable entry of a note's history, appended on every accepted write
    (creation included). Append-only; the latest entry equals the current note."""

    note_id: UUID
    version: int = Field(ge=1)
    title: str
    summary: str
    body: str
    status: VaultNoteStatus
    tags: list[VaultTag] = Field(default_factory=list)
    links: list[VaultNoteLink] = Field(default_factory=list)
    content_hash: Sha256Hex
    change_summary: str | None = None
    author_type: VaultActorType
    author_id: UUID
    created_at: datetime


def effective_notes[N: VaultNote](notes: Iterable[N], project_id: UUID | None) -> list[N]:
    """The notes a reader working in `project_id` sees: the studio notes plus
    that project's notes, where a project note replaces the studio note with the
    same slug, whatever their status (a draft project note masks a validated
    studio note). Archived notes are never effective. `project_id=None` is a
    reader outside any project and sees the studio scope only.

    Order: by slug."""

    visible: dict[str, N] = {}
    for note in notes:
        if note.status is VaultNoteStatus.ARCHIVED:
            continue
        if note.scope is VaultScope.PROJECT and note.project_id != project_id:
            continue
        current = visible.get(note.slug)
        if current is None or (
            note.scope is VaultScope.PROJECT and current.scope is VaultScope.STUDIO
        ):
            visible[note.slug] = note
    return [visible[slug] for slug in sorted(visible)]


def is_valid_slug(value: str) -> bool:
    return len(value) <= VAULT_SLUG_MAX and _SLUG_RE.fullmatch(value) is not None
