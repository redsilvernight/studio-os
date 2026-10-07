from __future__ import annotations

import base64
import json
import re
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, case, delete, exists, func, literal, literal_column, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.vault import VAULT_SEARCH_SNIPPET_MAX as _SNIPPET_MAX
from studio_contracts.vault import (
    VaultActorType,
    VaultLinkKind,
    VaultNote,
    VaultNoteCreate,
    VaultNoteLink,
    VaultNoteStatus,
    VaultNoteSummary,
    VaultNoteType,
    VaultNoteUpdate,
    VaultNoteVersion,
    VaultScope,
    VaultSearchHit,
    VaultSearchReason,
    VaultSearchResult,
    VaultTreePage,
    VaultVersionPage,
    content_hash,
)

from studio_api.db.models.vault import (
    VaultNoteLinkModel,
    VaultNoteModel,
    VaultNoteVersionModel,
)
from studio_api.services.authz import (
    ALL_PROJECTS,
    Principal,
    ensure_can_write,
    ensure_project_access,
    forbidden,
)
from studio_api.services.vault_secrets import scan as _scan_secrets

_TREE_LIMIT_DEFAULT = 50
_TREE_LIMIT_MAX = 200

_ADMIN_ONLY_STATUSES = frozenset(
    {
        VaultNoteStatus.VALIDATED.value,
        VaultNoteStatus.SUPERSEDED.value,
        VaultNoteStatus.ARCHIVED.value,
    }
)


def note_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "vault note not found")


def _slug_conflict(slug: str) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={"error_code": "vault_slug_conflict", "slug": slug},
    )


def _version_conflict(server_version: int) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={"error_code": "version_conflict", "server_version": server_version},
    )


def _invalid_link(target_note_id: uuid.UUID) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error_code": "invalid_vault_link", "target_note_id": str(target_note_id)},
    )


def _invalid_cursor() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error_code": "invalid_cursor"},
    )


async def _next_readable_id(session: AsyncSession) -> str:
    result = await session.execute(text("SELECT nextval('decisions_readable_id_seq')"))
    value = result.scalar_one()
    return f"DEC-{value:04d}"


def _compute_hash(
    title: str,
    summary: str,
    body: str,
    status: str,
    tags: list[str],
    links: list[VaultNoteLink],
    anchors: list[str],
) -> str:
    return content_hash(
        title=title,
        summary=summary,
        body=body,
        status=VaultNoteStatus(status),
        tags=tags,
        links=links,
        anchors=anchors,
    )


def _secret_detected(findings: list[Any]) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "error_code": "secret_detected",
            "details": [
                {"field": finding.field, "pattern": finding.pattern} for finding in findings
            ],
        },
    )


def _reject_secrets(fields: dict[str, str]) -> None:
    findings = _scan_secrets(fields)
    if findings:
        raise _secret_detected(findings)


def _create_secret_fields(note_in: VaultNoteCreate) -> dict[str, str]:
    return {
        "title": note_in.title,
        "summary": note_in.summary,
        "body": note_in.body,
        "tags": "\n".join(note_in.tags),
    }


def _update_secret_fields(note_in: VaultNoteUpdate) -> dict[str, str]:
    fields: dict[str, str] = {}
    if note_in.title is not None:
        fields["title"] = note_in.title
    if note_in.summary is not None:
        fields["summary"] = note_in.summary
    if note_in.body is not None:
        fields["body"] = note_in.body
    if note_in.tags is not None:
        fields["tags"] = "\n".join(note_in.tags)
    if note_in.change_summary is not None:
        fields["change_summary"] = note_in.change_summary
    return fields


def authorize_create(principal: Principal, note_in: VaultNoteCreate) -> None:
    """Scope then role check of a note creation, run ahead of the idempotency
    replay short-circuit (DEC-0036, DEC-0103 §12)."""
    _authorize_scope_write(principal, note_in.scope.value, note_in.project_id, note_in.status.value)
    _reject_secrets(_create_secret_fields(note_in))


def _authorize_scope_write(
    principal: Principal,
    scope: str,
    project_id: uuid.UUID | None,
    target_status: str,
    current_status: str | None = None,
) -> None:
    if scope == VaultScope.PROJECT.value:
        if project_id is None:
            raise forbidden("project", "write")
        ensure_project_access(principal, project_id, "write")
        ensure_can_write(principal, "vault_note")
        return
    ensure_can_write(principal, "vault_note")
    # A studio note in an admin-only status is admin-owned: a non-admin can
    # neither reach that status nor leave it (no demote-then-edit bypass).
    statuses = {target_status, current_status} & _ADMIN_ONLY_STATUSES
    if statuses and principal.role != Role.ADMIN:
        raise forbidden("vault_note", "write")


def _authorize_read(principal: Principal, note: VaultNoteModel) -> None:
    if note.scope == VaultScope.PROJECT.value:
        if note.project_id is None:
            raise forbidden("project", "read")
        ensure_project_access(principal, note.project_id, "read")


async def _ensure_slug_available(session: AsyncSession, note_in: VaultNoteCreate) -> None:
    stmt = select(VaultNoteModel.id).where(
        VaultNoteModel.scope == note_in.scope.value,
        VaultNoteModel.slug == note_in.slug,
        VaultNoteModel.status != VaultNoteStatus.ARCHIVED.value,
    )
    if note_in.scope is VaultScope.PROJECT:
        stmt = stmt.where(VaultNoteModel.project_id == note_in.project_id)
    if (await session.execute(stmt)).scalar_one_or_none() is not None:
        raise _slug_conflict(note_in.slug)


async def _validate_links(
    session: AsyncSession,
    source_scope: str,
    source_project_id: uuid.UUID | None,
    links: list[VaultNoteLink],
) -> None:
    for link in links:
        target = await session.get(VaultNoteModel, link.target_note_id)
        if target is None:
            raise _invalid_link(link.target_note_id)
        if target.scope == VaultScope.PROJECT.value and target.project_id != source_project_id:
            raise _invalid_link(link.target_note_id)


async def _append_version(
    session: AsyncSession,
    note: VaultNoteModel,
    links: list[VaultNoteLink],
    change_summary: str | None,
) -> None:
    session.add(
        VaultNoteVersionModel(
            note_id=note.id,
            version=note.version,
            title=note.title,
            summary=note.summary,
            body=note.body,
            status=note.status,
            tags=list(note.tags),
            links=[
                {"target_note_id": str(link.target_note_id), "kind": link.kind.value}
                for link in links
            ],
            anchors=list(note.anchors),
            content_hash=note.content_hash,
            change_summary=change_summary,
            author_type=note.author_type,
            author_id=note.author_id,
        )
    )


async def _replace_links(
    session: AsyncSession, note_id: uuid.UUID, links: list[VaultNoteLink]
) -> None:
    await session.execute(
        delete(VaultNoteLinkModel).where(VaultNoteLinkModel.source_note_id == note_id)
    )
    for link in links:
        session.add(
            VaultNoteLinkModel(
                source_note_id=note_id,
                target_note_id=link.target_note_id,
                kind=link.kind.value,
            )
        )


async def create_note(
    session: AsyncSession, principal: Principal, note_in: VaultNoteCreate
) -> VaultNoteModel:
    authorize_create(principal, note_in)
    await _ensure_slug_available(session, note_in)
    await _validate_links(session, note_in.scope.value, note_in.project_id, note_in.links)
    readable_id = (
        await _next_readable_id(session) if note_in.note_type is VaultNoteType.DECISION else None
    )
    note = VaultNoteModel(
        scope=note_in.scope.value,
        project_id=note_in.project_id,
        slug=note_in.slug,
        readable_id=readable_id,
        note_type=note_in.note_type.value,
        title=note_in.title,
        summary=note_in.summary,
        body=note_in.body,
        status=note_in.status.value,
        tags=list(note_in.tags),
        anchors=list(note_in.anchors),
        content_hash=_compute_hash(
            note_in.title,
            note_in.summary,
            note_in.body,
            note_in.status.value,
            note_in.tags,
            note_in.links,
            note_in.anchors,
        ),
        author_type=VaultActorType.USER.value,
        author_id=principal.user.id,
    )
    session.add(note)
    try:
        await session.flush()
    except IntegrityError as exc:  # concurrent create of the same slug
        await session.rollback()
        raise _slug_conflict(note_in.slug) from exc
    await _append_version(session, note, note_in.links, None)
    await _replace_links(session, note.id, note_in.links)
    await session.commit()
    await session.refresh(note)
    return note


async def read_note(
    session: AsyncSession, principal: Principal, note_id: uuid.UUID
) -> VaultNoteModel:
    note = await session.get(VaultNoteModel, note_id)
    if note is None:
        raise note_not_found()
    _authorize_read(principal, note)
    return note


async def _lock_note(session: AsyncSession, note_id: uuid.UUID) -> VaultNoteModel:
    note = (
        await session.execute(
            select(VaultNoteModel).where(VaultNoteModel.id == note_id).with_for_update()
        )
    ).scalar_one_or_none()
    if note is None:
        raise note_not_found()
    return note


async def update_note(
    session: AsyncSession, principal: Principal, note_id: uuid.UUID, note_in: VaultNoteUpdate
) -> VaultNoteModel:
    _reject_secrets(_update_secret_fields(note_in))
    note = await _lock_note(session, note_id)
    target_status = note_in.status.value if note_in.status is not None else note.status
    _authorize_scope_write(principal, note.scope, note.project_id, target_status, note.status)
    if note.version != note_in.expected_version:
        raise _version_conflict(note.version)

    current_links = await load_links(session, note.id)
    links = current_links if note_in.links is None else note_in.links
    if note_in.links is not None:
        await _validate_links(session, note.scope, note.project_id, note_in.links)

    if note_in.title is not None:
        note.title = note_in.title
    if note_in.summary is not None:
        note.summary = note_in.summary
    if note_in.body is not None:
        note.body = note_in.body
    if note_in.status is not None:
        note.status = note_in.status.value
    if note_in.tags is not None:
        note.tags = list(note_in.tags)
    if note_in.anchors is not None:
        note.anchors = list(note_in.anchors)
    note.version += 1
    # Audit (P05): each version records who wrote it, not who created the note.
    note.author_type = VaultActorType.USER.value
    note.author_id = principal.user.id
    note.content_hash = _compute_hash(
        note.title, note.summary, note.body, note.status, list(note.tags), links, list(note.anchors)
    )
    await _append_version(session, note, links, note_in.change_summary)
    if note_in.links is not None:
        await _replace_links(session, note.id, note_in.links)
    await session.commit()
    await session.refresh(note)
    return note


async def load_links(session: AsyncSession, note_id: uuid.UUID) -> list[VaultNoteLink]:
    rows = (
        (
            await session.execute(
                select(VaultNoteLinkModel).where(VaultNoteLinkModel.source_note_id == note_id)
            )
        )
        .scalars()
        .all()
    )
    return [
        VaultNoteLink(target_note_id=row.target_note_id, kind=VaultLinkKind(row.kind))
        for row in rows
    ]


async def serialize_note(session: AsyncSession, note: VaultNoteModel) -> VaultNote:
    return to_note(note, await load_links(session, note.id))


async def _load_links_for_notes(
    session: AsyncSession, note_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[VaultNoteLink]]:
    if not note_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(VaultNoteLinkModel).where(VaultNoteLinkModel.source_note_id.in_(note_ids))
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[uuid.UUID, list[VaultNoteLink]] = {}
    for row in rows:
        grouped.setdefault(row.source_note_id, []).append(
            VaultNoteLink(target_note_id=row.target_note_id, kind=VaultLinkKind(row.kind))
        )
    return grouped


def to_note(note: VaultNoteModel, links: list[VaultNoteLink]) -> VaultNote:
    return VaultNote(
        id=note.id,
        scope=VaultScope(note.scope),
        project_id=note.project_id,
        slug=note.slug,
        readable_id=note.readable_id,
        note_type=VaultNoteType(note.note_type),
        title=note.title,
        summary=note.summary,
        body=note.body,
        status=VaultNoteStatus(note.status),
        tags=note.tags,
        links=links,
        anchors=note.anchors,
        content_hash=note.content_hash,
        author_type=VaultActorType(note.author_type),
        author_id=note.author_id,
        version=note.version,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


def to_summary(note: VaultNoteModel, links: list[VaultNoteLink]) -> VaultNoteSummary:
    return VaultNoteSummary(
        id=note.id,
        scope=VaultScope(note.scope),
        project_id=note.project_id,
        slug=note.slug,
        readable_id=note.readable_id,
        note_type=VaultNoteType(note.note_type),
        title=note.title,
        summary=note.summary,
        status=VaultNoteStatus(note.status),
        tags=note.tags,
        links=links,
        anchors=note.anchors,
        content_hash=note.content_hash,
        author_type=VaultActorType(note.author_type),
        author_id=note.author_id,
        version=note.version,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


def to_version(row: VaultNoteVersionModel) -> VaultNoteVersion:
    return VaultNoteVersion(
        note_id=row.note_id,
        version=row.version,
        title=row.title,
        summary=row.summary,
        body=row.body,
        status=VaultNoteStatus(row.status),
        tags=row.tags,
        anchors=row.anchors,
        links=[
            VaultNoteLink(
                target_note_id=uuid.UUID(entry["target_note_id"]),
                kind=VaultLinkKind(entry["kind"]),
            )
            for entry in row.links
        ],
        content_hash=row.content_hash,
        change_summary=row.change_summary,
        author_type=VaultActorType(row.author_type),
        author_id=row.author_id,
        created_at=row.created_at,
    )


def _encode_tree_cursor(slug: str, note_id: uuid.UUID) -> str:
    payload = json.dumps({"s": slug, "i": str(note_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_tree_cursor(cursor: str) -> tuple[str, uuid.UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        return payload["s"], uuid.UUID(payload["i"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise _invalid_cursor() from exc


def _encode_version_cursor(version: int) -> str:
    return base64.urlsafe_b64encode(str(version).encode("ascii")).decode("ascii")


def _decode_version_cursor(cursor: str) -> int:
    try:
        return int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii"))
    except (ValueError, TypeError) as exc:
        raise _invalid_cursor() from exc


def _tree_visibility_clause(principal: Principal) -> Any | None:
    scope = principal.project_scope
    if scope is ALL_PROJECTS:
        return None
    if not scope:
        return VaultNoteModel.scope == VaultScope.STUDIO.value
    return or_(
        VaultNoteModel.scope == VaultScope.STUDIO.value,
        and_(
            VaultNoteModel.scope == VaultScope.PROJECT.value,
            VaultNoteModel.project_id.in_(scope),
        ),
    )


async def list_tree(
    session: AsyncSession,
    principal: Principal,
    scope: VaultScope | None,
    project_id: uuid.UUID | None,
    prefix: str | None,
    status_filter: VaultNoteStatus | None,
    include_archived: bool,
    limit: int,
    cursor: str | None,
) -> VaultTreePage:
    stmt = select(VaultNoteModel)
    if scope is VaultScope.STUDIO:
        stmt = stmt.where(VaultNoteModel.scope == VaultScope.STUDIO.value)
    elif scope is VaultScope.PROJECT:
        if project_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "missing_project_id"},
            )
        ensure_project_access(principal, project_id, "read")
        stmt = stmt.where(
            VaultNoteModel.scope == VaultScope.PROJECT.value,
            VaultNoteModel.project_id == project_id,
        )
    elif project_id is not None:
        ensure_project_access(principal, project_id, "read")
        stmt = stmt.where(
            VaultNoteModel.scope == VaultScope.PROJECT.value,
            VaultNoteModel.project_id == project_id,
        )
    elif (visible := _tree_visibility_clause(principal)) is not None:
        stmt = stmt.where(visible)
    if prefix is not None:
        stmt = stmt.where(VaultNoteModel.slug.startswith(prefix, autoescape=True))
    if status_filter is not None:
        stmt = stmt.where(VaultNoteModel.status == status_filter.value)
    if not include_archived:
        stmt = stmt.where(VaultNoteModel.status != VaultNoteStatus.ARCHIVED.value)
    if cursor is not None:
        slug_cursor, id_cursor = _decode_tree_cursor(cursor)
        stmt = stmt.where(
            or_(
                VaultNoteModel.slug > slug_cursor,
                and_(VaultNoteModel.slug == slug_cursor, VaultNoteModel.id > id_cursor),
            )
        )
    stmt = stmt.order_by(VaultNoteModel.slug.asc(), VaultNoteModel.id.asc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())

    next_cursor: str | None = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_tree_cursor(last.slug, last.id)
        rows = rows[:limit]
    links_by_note = await _load_links_for_notes(session, [row.id for row in rows])
    items = [to_summary(row, links_by_note.get(row.id, [])) for row in rows]
    return VaultTreePage(items=items, next_cursor=next_cursor)


async def list_versions(
    session: AsyncSession,
    principal: Principal,
    note_id: uuid.UUID,
    limit: int,
    cursor: str | None,
) -> VaultVersionPage:
    await read_note(session, principal, note_id)
    stmt = select(VaultNoteVersionModel).where(VaultNoteVersionModel.note_id == note_id)
    if cursor is not None:
        stmt = stmt.where(VaultNoteVersionModel.version > _decode_version_cursor(cursor))
    stmt = stmt.order_by(VaultNoteVersionModel.version.asc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())

    next_cursor: str | None = None
    if len(rows) > limit:
        next_cursor = _encode_version_cursor(rows[limit - 1].version)
        rows = rows[:limit]
    return VaultVersionPage(items=[to_version(row) for row in rows], next_cursor=next_cursor)


async def get_version(
    session: AsyncSession, principal: Principal, note_id: uuid.UUID, version: int
) -> VaultNoteVersion:
    await read_note(session, principal, note_id)
    row = (
        await session.execute(
            select(VaultNoteVersionModel).where(
                VaultNoteVersionModel.note_id == note_id,
                VaultNoteVersionModel.version == version,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "vault note version not found")
    return to_version(row)


# --- Search (P04) -----------------------------------------------------------

_SEARCH_CONFIG = text("'french'::regconfig")
_SEARCH_TERMS_MAX = 16
_SEARCH_ANCHORED_MAX = 200
_TERM_RE = re.compile(r"[\w][\w.-]*", re.UNICODE)
_HEADLINE_OPTIONS = (
    "MaxWords=30, MinWords=8, MaxFragments=1, StartSel=, StopSel=, FragmentDelimiter= … "
)
_STATUS_ORDER = {
    VaultNoteStatus.VALIDATED.value: 0,
    VaultNoteStatus.PROPOSED.value: 1,
    VaultNoteStatus.DRAFT.value: 2,
    VaultNoteStatus.SUPERSEDED.value: 3,
    VaultNoteStatus.ARCHIVED.value: 4,
}
_REASON_ORDER = {
    VaultSearchReason.ANCHOR: 0,
    VaultSearchReason.LINKED: 1,
    VaultSearchReason.LEXICAL: 2,
}


def _search_terms(q: str | None) -> list[str]:
    """Lower-cased words of the query, deduplicated in order. Each word becomes
    its own `plainto_tsquery` (French stemming and stop words) and the words are
    OR-ed: a note matching some of the words still ranks, the more the better."""
    if not q:
        return []
    seen: dict[str, None] = {}
    for match in _TERM_RE.findall(q.lower()):
        term = match.strip(".-_")
        if len(term) >= 2:
            seen.setdefault(term, None)
    return list(seen)[:_SEARCH_TERMS_MAX]


def _tsquery(terms: list[str]) -> Any:
    query: Any = None
    for term in terms:
        part = func.plainto_tsquery(_SEARCH_CONFIG, term)
        query = part if query is None else query.op("||")(part)
    return query


def _coverage_rank(terms: list[str], tsquery: Any) -> Any:
    """Distinct query words matched, a word in the title or readable id
    (weight A) counting 3 and elsewhere 1, plus `ts_rank_cd` (normalised into
    [0, 1)) as a tie-breaker: covering more of the query beats repeating one
    word."""
    title_vector = func.ts_filter(VaultNoteModel.search_vector, literal_column("'{a}'::\"char\"[]"))
    coverage: Any = literal(0)
    for term in terms:
        part = func.plainto_tsquery(_SEARCH_CONFIG, term)
        coverage = coverage + case(
            (title_vector.op("@@")(part), 3),
            (VaultNoteModel.search_vector.op("@@")(part), 1),
            else_=0,
        )
    return coverage + func.ts_rank_cd(VaultNoteModel.search_vector, tsquery, 32)


def _normalize_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/")


def _requested_anchors(paths: list[str], task_id: uuid.UUID | None) -> tuple[set[str], list[str]]:
    """Anchors that match the request: the exact `path:` anchors plus every
    enclosing directory anchor (`path:services/` covers `services/api/x.py`),
    the task anchor; and the directory prefixes whose content also matches
    (a requested `docs/` matches a note anchored to `path:docs/a.md`)."""
    exact: set[str] = set()
    inside: list[str] = []
    for raw in paths:
        path = _normalize_path(raw)
        if not path:
            continue
        exact.add(f"path:{path}")
        parts = path.rstrip("/").split("/")
        for depth in range(1, len(parts)):
            exact.add("path:" + "/".join(parts[:depth]) + "/")
        if path.endswith("/"):
            inside.append(f"path:{path}")
    if task_id is not None:
        exact.add(f"task:{task_id}")
    return exact, inside


def _matched_anchors(note_anchors: list[str], exact: set[str], inside: list[str]) -> list[str]:
    return sorted(
        anchor
        for anchor in note_anchors
        if anchor in exact or any(anchor.startswith(prefix) for prefix in inside)
    )


def _search_filters(
    principal: Principal,
    scope: VaultScope | None,
    project_id: uuid.UUID | None,
    note_types: list[VaultNoteType],
    statuses: list[VaultNoteStatus],
    include_superseded: bool,
) -> list[Any]:
    """Visibility, scope, type and status clauses shared by every search branch.
    With a `project_id` the reader sees the studio notes plus that project's
    notes; without, every note their memberships allow."""
    filters: list[Any] = []
    if scope is VaultScope.PROJECT and project_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"error_code": "missing_project_id"}
        )
    if project_id is not None:
        ensure_project_access(principal, project_id, "read")
        project_clause = and_(
            VaultNoteModel.scope == VaultScope.PROJECT.value,
            VaultNoteModel.project_id == project_id,
        )
        if scope is VaultScope.PROJECT:
            filters.append(project_clause)
        elif scope is VaultScope.STUDIO:
            filters.append(VaultNoteModel.scope == VaultScope.STUDIO.value)
        else:
            filters.append(or_(VaultNoteModel.scope == VaultScope.STUDIO.value, project_clause))
    else:
        if scope is VaultScope.STUDIO:
            filters.append(VaultNoteModel.scope == VaultScope.STUDIO.value)
        if (visible := _tree_visibility_clause(principal)) is not None:
            filters.append(visible)
    if note_types:
        filters.append(VaultNoteModel.note_type.in_([value.value for value in note_types]))
    if statuses:
        filters.append(VaultNoteModel.status.in_([value.value for value in statuses]))
    else:
        hidden = [VaultNoteStatus.ARCHIVED.value]
        if not include_superseded:
            hidden.append(VaultNoteStatus.SUPERSEDED.value)
        filters.append(VaultNoteModel.status.not_in(hidden))
    return filters


async def search_notes(
    session: AsyncSession,
    principal: Principal,
    *,
    q: str | None,
    scope: VaultScope | None,
    project_id: uuid.UUID | None,
    note_types: list[VaultNoteType],
    statuses: list[VaultNoteStatus],
    include_superseded: bool,
    paths: list[str],
    task_id: uuid.UUID | None,
    limit: int,
    max_chars: int,
) -> VaultSearchResult:
    """Ranked search. Order: notes anchored to a requested path or task first,
    then notes one link away from them, then full-text matches; inside a group,
    by query coverage (title and readable id weigh most, `ts_rank_cd` breaks ties), then
    status (validated first), then most recently updated. Superseded and
    archived notes are left out unless asked for. Each hit is bounded: summary
    plus a short snippet, never the body; `max_chars` caps the whole answer."""
    # Access first: an outsider gets 403 whatever the criteria.
    filters = _search_filters(
        principal, scope, project_id, note_types, statuses, include_superseded
    )
    terms = _search_terms(q)
    exact, inside = _requested_anchors(paths, task_id)
    if not terms and not exact:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"error_code": "missing_search_criteria"}
        )
    tsquery = _tsquery(terms) if terms else None
    rank_col = (_coverage_rank(terms, tsquery) if tsquery is not None else literal(0.0)).label(
        "rank"
    )

    anchored: dict[uuid.UUID, tuple[VaultNoteModel, float]] = {}
    if exact or inside:
        anchor_clauses: list[Any] = []
        if exact:
            anchor_clauses.append(VaultNoteModel.anchors.overlap(sorted(exact)))
        for prefix in inside:
            element = func.unnest(VaultNoteModel.anchors).column_valued("anchor")
            anchor_clauses.append(
                exists(select(literal(1)).where(element.startswith(prefix, autoescape=True)))
            )
        rows = await session.execute(
            select(VaultNoteModel, rank_col)
            .where(*filters, or_(*anchor_clauses))
            .limit(_SEARCH_ANCHORED_MAX)
        )
        anchored = {note.id: (note, float(rank)) for note, rank in rows.all()}

    linked: dict[uuid.UUID, tuple[VaultNoteModel, float]] = {}
    if anchored:
        anchored_ids = list(anchored)
        link_rows = await session.execute(
            select(VaultNoteLinkModel.source_note_id, VaultNoteLinkModel.target_note_id).where(
                or_(
                    VaultNoteLinkModel.source_note_id.in_(anchored_ids),
                    VaultNoteLinkModel.target_note_id.in_(anchored_ids),
                )
            )
        )
        neighbour_ids = {
            other
            for source, target in link_rows.all()
            for other in (source, target)
            if other not in anchored
        }
        if neighbour_ids:
            rows = await session.execute(
                select(VaultNoteModel, rank_col).where(
                    *filters, VaultNoteModel.id.in_(neighbour_ids)
                )
            )
            linked = {note.id: (note, float(rank)) for note, rank in rows.all()}

    lexical: dict[uuid.UUID, tuple[VaultNoteModel, float]] = {}
    lexical_total = 0
    if tsquery is not None:
        lexical_clause = VaultNoteModel.search_vector.op("@@")(tsquery)
        known = set(anchored) | set(linked)
        rows = await session.execute(
            select(VaultNoteModel, rank_col)
            .where(*filters, lexical_clause)
            .order_by(rank_col.desc(), VaultNoteModel.updated_at.desc(), VaultNoteModel.id)
            .limit(limit + len(known))
        )
        lexical = {
            note.id: (note, float(rank)) for note, rank in rows.all() if note.id not in known
        }
        count_stmt = (
            select(func.count()).select_from(VaultNoteModel).where(*filters, lexical_clause)
        )
        if known:
            count_stmt = count_stmt.where(VaultNoteModel.id.not_in(known))
        lexical_total = int((await session.execute(count_stmt)).scalar_one())

    candidates: list[tuple[VaultSearchReason, VaultNoteModel, float]] = [
        *((VaultSearchReason.ANCHOR, note, rank) for note, rank in anchored.values()),
        *((VaultSearchReason.LINKED, note, rank) for note, rank in linked.values()),
        *((VaultSearchReason.LEXICAL, note, rank) for note, rank in lexical.values()),
    ]
    candidates.sort(
        key=lambda item: (
            _REASON_ORDER[item[0]],
            -item[2],
            _STATUS_ORDER.get(item[1].status, 9),
            -item[1].updated_at.timestamp(),
            str(item[1].id),
        )
    )
    total = len(anchored) + len(linked) + lexical_total

    page = candidates[:limit]
    snippets = await _snippets(session, [note for _, note, _ in page], tsquery)
    links_by_note = await _load_links_for_notes(session, [note.id for _, note, _ in page])
    items: list[VaultSearchHit] = []
    used = 0
    for reason, note, rank in page:
        snippet = snippets.get(note.id, "")
        cost = len(note.title) + len(note.summary) + len(snippet)
        if items and used + cost > max_chars:
            break
        used += cost
        items.append(
            VaultSearchHit(
                note=to_summary(note, links_by_note.get(note.id, [])),
                reason=reason,
                matched_anchors=_matched_anchors(list(note.anchors), exact, inside),
                rank=round(max(rank, 0.0), 6),
                snippet=snippet,
            )
        )
    return VaultSearchResult(items=items, total=total, truncated=total > len(items))


async def _snippets(
    session: AsyncSession, notes: list[VaultNoteModel], tsquery: Any
) -> dict[uuid.UUID, str]:
    """A short excerpt of each body around the matched words (`ts_headline`,
    computed only for the returned page); without a query, the body start when
    the note has no summary."""
    if not notes:
        return {}
    if tsquery is None:
        return {note.id: _clip(note.body) for note in notes if not note.summary.strip()}
    rows = await session.execute(
        select(
            VaultNoteModel.id,
            func.ts_headline(_SEARCH_CONFIG, VaultNoteModel.body, tsquery, _HEADLINE_OPTIONS),
        ).where(VaultNoteModel.id.in_([note.id for note in notes]))
    )
    return {note_id: _clip(headline or "") for note_id, headline in rows.all()}


def _clip(value: str) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= _SNIPPET_MAX:
        return collapsed
    return collapsed[: _SNIPPET_MAX - 1].rstrip() + "…"
