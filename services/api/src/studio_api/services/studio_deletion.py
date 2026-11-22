"""Deletion lifecycle of a studio (0051).

A deletion is a two-step contract:

- `request_deletion` (owner only, slug retyped as confirmation) starts a grace
  window: the studio turns read-only (`status = pending_deletion`) and
  `deletion_scheduled_at` is set. Everything stays readable, an export can
  still be produced, and `cancel_deletion` undoes the request.
- `purge_due_studios` is the irreversible step: called by the daemon or
  `studio-admin studios purge-due` once the grace window elapsed, it removes
  the studio's object-storage files and every database row it owns. The
  internal studio is never purged.

The row deletion is driven by the live PostgreSQL catalog instead of a
hand-written list: every table carrying `studio_id`, and every table reaching a
doomed row through a foreign key, is deleted child-before-parent. A table added
later (a new migration) is therefore covered without touching this module.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.studio import PENDING_DELETION_STATUS, StudioModel
from studio_api.db.models.transfer import TransferModel
from studio_api.services.authz import Principal
from studio_api.services.studio_export import get_owned_studio
from studio_api.settings import Settings
from studio_api.storage.provider import StorageProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StudioPurgeResult:
    """What one purge removed, for the CLI/daemon log."""

    studio_id: uuid.UUID
    slug: str
    objects_deleted: int
    backup_purge_at: datetime


@dataclass(frozen=True)
class _FkEdge:
    child_table: str
    child_column: str
    parent_table: str


_FK_EDGES = text(
    """
    SELECT c.relname AS child_table, a.attname AS child_column, p.relname AS parent_table
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    JOIN pg_class p ON p.oid = con.confrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY (con.conkey)
    WHERE con.contype = 'f' AND n.nspname = 'public'
    ORDER BY c.relname, a.attname
    """
)

_STUDIO_SCOPED_TABLES = text(
    """
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid
    WHERE n.nspname = 'public' AND c.relkind = 'r'
      AND a.attname = 'studio_id' AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY c.relname
    """
)

_TABLES_WITH_ID = text(
    """
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid
    WHERE n.nspname = 'public' AND c.relkind = 'r'
      AND a.attname = 'id' AND a.attnum > 0 AND NOT a.attisdropped
    """
)


def _alias(table: str) -> str:
    """A stable SQL alias derived from a trusted catalog identifier."""
    return "_" + "".join(char if char.isalnum() or char == "_" else "_" for char in table)


def _predicate_templates(edges: list[_FkEdge], studio_tables: set[str]) -> dict[str, str | None]:
    """SQL template deleting, for each table, the rows owned by one studio.

    A table is doomed when it carries `studio_id`, or when one of its foreign
    keys points at a doomed row. The template uses `{a}` as the alias of the
    row being deleted; nested subqueries reuse it with their own alias (SQL
    scoping makes the shadowing harmless). Self-references are skipped: a
    single DELETE already removes both ends of the pair."""
    by_child: dict[str, list[_FkEdge]] = {}
    for edge in edges:
        if edge.child_table == edge.parent_table:
            continue
        by_child.setdefault(edge.child_table, []).append(edge)
    memo: dict[str, str | None] = {}

    def build(table: str, stack: frozenset[str]) -> str | None:
        if table in memo:
            return memo[table]
        if table in stack:
            return None
        clauses: list[str] = []
        if table in studio_tables:
            clauses.append("{a}.studio_id = :studio_id")
        for edge in by_child.get(table, ()):
            parent = build(edge.parent_table, stack | {table})
            if parent is None:
                continue
            alias = _alias(edge.parent_table)
            nested = parent.replace("{a}", alias)
            clauses.append(
                f'{{a}}."{edge.child_column}" IN ('
                f'SELECT {alias}.id FROM "{edge.parent_table}" {alias} WHERE {nested})'
            )
        template = " OR ".join(clauses) if clauses else None
        memo[table] = template
        return template

    # Every table reachable from (or into) a doomed one, not only the parents
    # visited while building a studio-scoped table: a project-scoped table with
    # no studio-scoped child (roadmaps, events, claims, …) is otherwise missed.
    all_tables = studio_tables | {edge.child_table for edge in edges}
    for table in sorted(all_tables):
        build(table, frozenset())
    return memo


def _delete_order(edges: list[_FkEdge], targets: set[str]) -> list[str]:
    """Child-before-parent order restricted to `targets` (Kahn on the FK graph
    read parent -> children). A cycle that is not a self-reference cannot be
    ordered safely and is a schema bug: refuse instead of deleting blindly."""
    children: dict[str, set[str]] = {}
    for edge in edges:
        if edge.child_table == edge.parent_table:
            continue
        children.setdefault(edge.parent_table, set()).add(edge.child_table)
    remaining = set(targets)
    order: list[str] = []
    while remaining:
        ready = sorted(table for table in remaining if not (children.get(table, set()) & remaining))
        if not ready:
            raise RuntimeError(
                "cyclic foreign keys prevent a safe studio purge: " + ", ".join(sorted(remaining))
            )
        for table in ready:
            order.append(table)
            remaining.discard(table)
    return order


async def _delete_studio_rows(session: AsyncSession, studio_id: uuid.UUID) -> None:
    """Delete every row the studio owns, then the `studios` row itself."""
    edges = [
        _FkEdge(str(row[0]), str(row[1]), str(row[2]))
        for row in (await session.execute(_FK_EDGES)).all()
    ]
    studio_tables = {str(row[0]) for row in (await session.execute(_STUDIO_SCOPED_TABLES)).all()}
    id_tables = {str(row[0]) for row in (await session.execute(_TABLES_WITH_ID)).all()}
    templates = _predicate_templates(edges, studio_tables)
    # A predicate can only reach a parent through its `id`; a table without one
    # (a pure join table) is always deleted by its own `studio_id` or not at
    # all — no current table references one.
    targets = {table for table, template in templates.items() if template is not None}
    for table in _delete_order(edges, targets):
        if table not in id_tables and table not in studio_tables:  # pragma: no cover
            continue
        template = templates[table]
        if template is None:  # pragma: no cover - `targets` guarantees a template
            continue
        await session.execute(
            text(f'DELETE FROM "{table}" AS t WHERE {template.replace("{a}", "t")}'),
            {"studio_id": studio_id},
        )
    await session.execute(
        text("DELETE FROM studios WHERE id = :studio_id"), {"studio_id": studio_id}
    )


async def _delete_studio_objects(
    session: AsyncSession, storage: StorageProvider, studio_id: uuid.UUID
) -> int:
    """Remove the studio's files: transfer objects (metadata keys) and every
    archive/leftover under `studios/{studio_id}/`."""
    transfer_keys = list(
        (
            await session.execute(
                select(TransferModel.object_key).where(TransferModel.studio_id == studio_id)
            )
        )
        .scalars()
        .all()
    )
    for object_key in transfer_keys:
        await storage.delete_object(object_key)
    return len(transfer_keys) + await storage.delete_prefix(f"studios/{studio_id}/")


async def request_deletion(
    session: AsyncSession,
    settings: Settings,
    principal: Principal,
    studio_id: uuid.UUID,
    confirmation: str,
    now: datetime | None = None,
) -> StudioModel:
    """Start the grace window. Idempotent: asking twice keeps the first
    schedule instead of extending it silently."""
    studio = await get_owned_studio(session, principal, studio_id)
    if studio.is_internal:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "studio_internal",
                "message": "the internal studio cannot be deleted",
            },
        )
    if confirmation != studio.slug:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "invalid_confirmation",
                "message": "the studio slug must be retyped exactly",
            },
        )
    if studio.deletion_scheduled_at is None:
        requested_at = now or datetime.now(UTC)
        studio.deletion_requested_at = requested_at
        studio.deletion_scheduled_at = requested_at + timedelta(days=settings.deletion_grace_days)
        studio.status = PENDING_DELETION_STATUS
        studio.version += 1
        await session.commit()
        await session.refresh(studio)
    return studio


async def cancel_deletion(
    session: AsyncSession, principal: Principal, studio_id: uuid.UUID
) -> StudioModel:
    """Cancel during the grace window: clears the schedule and returns the
    studio to `active`. Idempotent when nothing is scheduled."""
    studio = await get_owned_studio(session, principal, studio_id)
    if studio.deletion_scheduled_at is not None:
        studio.deletion_requested_at = None
        studio.deletion_scheduled_at = None
        studio.status = "active"
        studio.version += 1
        await session.commit()
        await session.refresh(studio)
    return studio


async def purge_due_studios(
    session: AsyncSession,
    storage: StorageProvider,
    settings: Settings,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> list[StudioPurgeResult]:
    """Irreversible purge of every studio whose grace window elapsed.

    One studio per transaction (a storage or SQL failure only stops the current
    one, the next run resumes the rest). The internal studio is never selected,
    even if a row was scheduled by hand. The backup purge date is logged: the
    database backup itself is rotated by the host, this states the announced
    retention after which the studio is gone from backups too."""
    cutoff = now or datetime.now(UTC)
    due = list(
        (
            await session.execute(
                select(StudioModel)
                .where(
                    StudioModel.deletion_scheduled_at.is_not(None),
                    StudioModel.deletion_scheduled_at <= cutoff,
                    StudioModel.is_internal.is_(False),
                )
                .order_by(StudioModel.deletion_scheduled_at, StudioModel.id)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    results: list[StudioPurgeResult] = []
    for studio in due:
        if studio.is_internal:  # defense in depth, never purged
            logger.warning("studio purge skipped: %s is the internal studio", studio.id)
            continue
        backup_purge_at = cutoff + timedelta(days=settings.deletion_backup_retention_days)
        if dry_run:
            results.append(StudioPurgeResult(studio.id, studio.slug, 0, backup_purge_at))
            continue
        try:
            objects_deleted = await _delete_studio_objects(session, storage, studio.id)
        except (BotoCoreError, ClientError) as exc:
            logger.error(
                "studio %s (%s) purge aborted: object storage unavailable",
                studio.id,
                studio.slug,
                exc_info=exc,
            )
            await session.rollback()
            raise
        await _delete_studio_rows(session, studio.id)
        await session.commit()
        logger.info(
            "studio %s (%s) purged: %s object(s) deleted; database backups still "
            "contain its data until %s (%s-day retention)",
            studio.id,
            studio.slug,
            objects_deleted,
            backup_purge_at.isoformat(),
            settings.deletion_backup_retention_days,
        )
        results.append(StudioPurgeResult(studio.id, studio.slug, objects_deleted, backup_purge_at))
    return results
