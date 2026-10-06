from __future__ import annotations

import base64
import json
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
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
) -> str:
    return content_hash(
        title=title,
        summary=summary,
        body=body,
        status=VaultNoteStatus(status),
        tags=tags,
        links=links,
    )


def authorize_create(principal: Principal, note_in: VaultNoteCreate) -> None:
    """Scope then role check of a note creation, run ahead of the idempotency
    replay short-circuit (DEC-0036, DEC-0103 §12)."""
    _authorize_scope_write(principal, note_in.scope.value, note_in.project_id, note_in.status.value)


def _authorize_scope_write(
    principal: Principal, scope: str, project_id: uuid.UUID | None, target_status: str
) -> None:
    if scope == VaultScope.PROJECT.value:
        if project_id is None:
            raise forbidden("project", "write")
        ensure_project_access(principal, project_id, "write")
        ensure_can_write(principal, "vault_note")
        return
    ensure_can_write(principal, "vault_note")
    if target_status in _ADMIN_ONLY_STATUSES and principal.role != Role.ADMIN:
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
        content_hash=_compute_hash(
            note_in.title,
            note_in.summary,
            note_in.body,
            note_in.status.value,
            note_in.tags,
            note_in.links,
        ),
        author_type=VaultActorType.USER.value,
        author_id=principal.user.id,
    )
    session.add(note)
    await session.flush()
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
    note = await _lock_note(session, note_id)
    target_status = note_in.status.value if note_in.status is not None else note.status
    _authorize_scope_write(principal, note.scope, note.project_id, target_status)
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
    note.version += 1
    note.content_hash = _compute_hash(
        note.title, note.summary, note.body, note.status, list(note.tags), links
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
        stmt = stmt.where(VaultNoteModel.slug.like(f"{prefix}%"))
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
