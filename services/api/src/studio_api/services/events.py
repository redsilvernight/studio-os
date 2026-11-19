from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.coordination import COORDINATION_EVENT_PREFIX
from studio_contracts.events import EventCreate, EventEnvelope, EventType

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.library import LibraryResourceModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session_factory
from studio_api.services import event_stream
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_project_access,
    ensure_project_in_studio,
    has_any_project,
    owns_agent,
    project_access_for_user,
    project_visibility_clause,
    studio_role_for_user,
)


async def resolve_event_identity(
    session: AsyncSession, principal: Principal, event_in: EventCreate
) -> EventCreate:
    """Binds a client-submitted event to the identity of the authenticated
    machine, per TECH/04_AUTH_SYNC_CONTRACT.md (DEC-0035) — a caller can
    never attribute an event to a machine, user or agent it doesn't hold,
    even by replaying an existing `event_id` (the replay itself is rejected
    here before `create_event`'s idempotent short-circuit is ever reached,
    so an already-stored event's recorded identity is never touched). The
    role write-gate (DEC-0036: `readonly` never writes shared state) is
    checked here too, ahead of that same idempotent short-circuit, so a
    replay by an unauthorized caller can never consume/observe a third
    party's stored response. The project write check (DEC-0103 §12) runs
    first, for the same reason and so an inaccessible project's `event_id`
    replay never reveals whether it exists.

    Only for the public creation path (`POST /events`, `studio_emit_event`).
    It always requires a project: a `None` `project_id` (contract v2,
    Studio-scope `library.*`) is server-internal only and answers `422`
    here. Server-internal code that calls `create_event` directly (e.g. the
    `resource.conflict` event in `routers/claims.py`, `_emit_library_event`
    for Studio scope) is exempt — it is trusted code, not client input.
    `actor_type="system"` IS a legitimate client submission here too (git/godot
    watchers, DEC-0032, replayed through the outbox like any other event) —
    restricted to `actor_id == machine.id`, the machine self-attributing its
    own automated event.
    """
    if event_in.project_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "project_required",
                "message": "POST /events always requires a project_id; "
                "project-less library.* events are emitted by the server only",
            },
        )
    await ensure_project_in_studio(session, principal, event_in.project_id, "write")
    ensure_can_write(principal, "event")
    if event_in.event_type.value.startswith(COORDINATION_EVENT_PREFIX):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "coordination_reserved",
                "message": "coordination.* events are emitted only through "
                "POST /api/v1/coordination (studio_coordinate)",
            },
        )
    machine = principal.machine
    if event_in.machine_id is not None and event_in.machine_id != machine.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "machine_id_mismatch",
                "message": "machine_id does not match the authenticated machine",
            },
        )

    if event_in.actor_type == "user":
        if event_in.actor_id != machine.owner_user_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "actor_id_mismatch",
                    "message": "actor_id must be the authenticated machine's owner "
                    "for actor_type=user",
                },
            )
    elif event_in.actor_type == "agent":
        agent = await session.get(AgentModel, event_in.actor_id)
        if not owns_agent(agent, machine):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "actor_not_owned",
                    "message": "actor_id must be an agent attached to the authenticated machine",
                },
            )
    elif event_in.actor_type == "system":
        # A machine self-attributing an automated event to itself (git/godot
        # watchers, DEC-0032) — the same actor_id=machine.id shape as the
        # server-internal resource.conflict event, just arriving through the
        # public replay path instead of a direct create_event() call.
        if event_in.actor_id != machine.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "actor_not_owned",
                    "message": "actor_id must be the authenticated machine's own id "
                    "for actor_type=system",
                },
            )

    return event_in.model_copy(update={"machine_id": machine.id})


def _new_event_row(event_in: EventCreate) -> EventModel:
    return EventModel(
        id=event_in.event_id,
        event_type=event_in.event_type.value,
        project_id=event_in.project_id,
        task_id=event_in.task_id,
        machine_id=event_in.machine_id,
        actor_type=event_in.actor_type,
        actor_id=event_in.actor_id,
        client_timestamp=event_in.client_timestamp,
        server_timestamp=datetime.now(UTC),
        payload=event_in.payload,
        schema_version=event_in.schema_version,
    )


def _library_resource_id(event: EventModel) -> UUID | None:
    """The library resource a project-less Studio `library.*` event is about
    (its payload's `resource_id`), or `None` when it cannot be parsed."""
    raw = (event.payload or {}).get("resource_id")
    if not isinstance(raw, str):
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


async def event_studio_id(session: AsyncSession, event: EventModel) -> UUID | None:
    """The studio an event belongs to (DEC-0382). Events carry no `studio_id`
    of their own: a project event borrows its project's, a project-less Studio
    `library.*` event its library resource's. `None` means unresolved — such an
    event is never delivered to a stream (fail-closed)."""
    if event.project_id is not None:
        project_studio: UUID | None = await session.scalar(
            select(ProjectModel.studio_id).where(ProjectModel.id == event.project_id)
        )
        return project_studio
    resource_id = _library_resource_id(event)
    if resource_id is None:
        return None
    resource_studio: UUID | None = await session.scalar(
        select(LibraryResourceModel.studio_id).where(LibraryResourceModel.id == resource_id)
    )
    return resource_studio


async def events_in_studio(
    session: AsyncSession, events: list[EventModel], studio_id: UUID
) -> list[EventModel]:
    """The subset of `events` owned by `studio_id`, resolved in two batched
    lookups (projects then library resources) so a replay backlog or a listing
    never pays one query per row. Events whose studio cannot be resolved are
    dropped (fail-closed), never broadcast."""
    project_ids = {event.project_id for event in events if event.project_id is not None}
    resource_ids = {
        resource_id
        for event in events
        if event.project_id is None and (resource_id := _library_resource_id(event)) is not None
    }
    studios: dict[UUID, UUID] = {}
    if project_ids:
        rows = await session.execute(
            select(ProjectModel.id, ProjectModel.studio_id).where(ProjectModel.id.in_(project_ids))
        )
        studios.update({row.id: row.studio_id for row in rows})
    if resource_ids:
        rows = await session.execute(
            select(LibraryResourceModel.id, LibraryResourceModel.studio_id).where(
                LibraryResourceModel.id.in_(resource_ids)
            )
        )
        studios.update({row.id: row.studio_id for row in rows})

    def _owner(event: EventModel) -> UUID | None:
        key = event.project_id if event.project_id is not None else _library_resource_id(event)
        return None if key is None else studios.get(key)

    return [event for event in events if _owner(event) == studio_id]


async def publish_event(
    session: AsyncSession, event: EventModel, studio_id: UUID | None = None
) -> None:
    """Realtime fan-out of a *committed* event (`seq` is assigned by then).
    The event's studio is resolved from its project (or library resource) so
    every open stream can drop the events of another studio (DEC-0382)."""
    resolved = studio_id if studio_id is not None else await event_studio_id(session, event)
    event_stream.publish(
        event_stream.StreamEvent(
            seq=event.seq,
            project_id=event.project_id,
            studio_id=resolved,
            envelope=EventEnvelope.model_validate(event),
        )
    )


async def _insert_and_notify(session: AsyncSession, event_in: EventCreate) -> EventModel:
    """Flush the new row, then queue a NOTIFY carrying its `seq` in the same
    transaction (DEC-0156): PostgreSQL delivers it to every listening process
    at commit only, never on rollback."""
    event = _new_event_row(event_in)
    session.add(event)
    await session.flush()
    # `seq` is read server-side: it is an identity column the ORM may not
    # have fetched back yet at this point.
    await session.execute(
        text("SELECT pg_notify(:channel, seq::text) FROM events WHERE id = :id"),
        {"channel": event_stream.NOTIFY_CHANNEL, "id": event.id},
    )
    return event


async def stage_event(session: AsyncSession, event_in: EventCreate) -> EventModel:
    """Insert the event in the caller's transaction (flush only, no commit) so a
    unit of work and its audit trail become durable atomically. The caller
    commits, refreshes the row and calls `publish_event`. Server-internal use;
    idempotent on `event_id` like `create_event`."""
    existing = await session.get(EventModel, event_in.event_id)
    if existing is not None:
        return existing
    return await _insert_and_notify(session, event_in)


async def create_event(session: AsyncSession, event_in: EventCreate) -> EventModel:
    """Idempotent on `event_id`: a replay (offline queue retry, at-least-once
    delivery) returns the already-stored row instead of inserting a duplicate,
    and notifies nobody."""
    existing = await session.get(EventModel, event_in.event_id)
    if existing is not None:
        return existing

    event = await _insert_and_notify(session, event_in)
    await session.commit()
    await session.refresh(event)
    await publish_event(session, event)
    return event


def _as_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(value)


async def list_events_after(
    session: AsyncSession,
    principal: Principal,
    project_id: UUID | str | None,
    after_seq: int | None,
    limit: int = 500,
    include_global: bool = False,
) -> list[EventModel]:
    """Realtime catch-up (DEC-0018): `seq` is a strictly monotonic identity
    column, unlike `server_timestamp` which can collide under concurrent
    writes — safe to use as a no-loss/no-duplicate resume cursor.

    With a `project_id`, the backlog carries that project's events; the
    project-less Studio `library.*` events (contract v2: one global event
    instead of a per-project fan-out) join in only with
    `include_global=True` — deployed readers parse `project_id` as a
    non-null UUID, so the default stays a pure per-project channel. Without
    a `project_id`, only the project-less events — readable by any
    authenticated principal."""
    stmt = select(EventModel).order_by(EventModel.seq.asc()).limit(limit)
    if project_id is not None:
        ensure_project_access(principal, _as_uuid(project_id))
        visible = project_visibility_clause(principal, EventModel.project_id)
        if include_global:
            stmt = stmt.where(
                or_(
                    EventModel.project_id == project_id,
                    EventModel.project_id.is_(None),
                )
            )
        else:
            stmt = stmt.where(EventModel.project_id == project_id)
        if visible is not None:
            stmt = stmt.where(visible)
    else:
        stmt = stmt.where(EventModel.project_id.is_(None))
    if after_seq is not None:
        stmt = stmt.where(EventModel.seq > after_seq)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_events(
    session: AsyncSession,
    principal: Principal,
    project_id: UUID | str | None = None,
    task_id: UUID | str | None = None,
    since: datetime | None = None,
    limit: int = 100,
    event_type: EventType | None = None,
    until: datetime | None = None,
    offset: int = 0,
    include_global: bool = False,
) -> list[EventModel]:
    stmt = (
        select(EventModel)
        .order_by(EventModel.server_timestamp.desc(), EventModel.seq.desc())
        .limit(limit)
        .offset(offset)
    )
    if project_id is not None:
        ensure_project_access(principal, _as_uuid(project_id))
        if include_global:
            stmt = stmt.where(
                or_(
                    EventModel.project_id == project_id,
                    EventModel.project_id.is_(None),
                )
            )
        else:
            stmt = stmt.where(EventModel.project_id == project_id)
        visible = project_visibility_clause(principal, EventModel.project_id)
        if visible is not None:
            stmt = stmt.where(visible)
    elif (visible := project_visibility_clause(principal, EventModel.project_id)) is not None:
        # `project_visibility_clause` already keeps project-less rows for a
        # principal with at least one membership; contract v2 goes one step
        # further — a project-less row is always a Studio-scope `library.*`
        # event (enforced by `ck_events_project_scope`), shared data with no
        # inter-project leak, so an authenticated principal with no
        # membership at all still reads those, just never another
        # project's rows.
        if not has_any_project(principal):
            stmt = stmt.where(EventModel.project_id.is_(None))
        else:
            stmt = stmt.where(visible)
    if task_id is not None:
        # A task of an inaccessible project answers the project 403, not an
        # empty listing (DEC-0103 §8); an unknown task filters to nothing.
        await tasks_service.read_task(session, principal, _as_uuid(task_id))
        stmt = stmt.where(EventModel.task_id == task_id)
    if since is not None:
        stmt = stmt.where(EventModel.server_timestamp >= since)
    if until is not None:
        stmt = stmt.where(EventModel.server_timestamp < until)
    if event_type is not None:
        stmt = stmt.where(EventModel.event_type == event_type.value)
    result = await session.execute(stmt)
    events = list(result.scalars().all())
    if any(event.project_id is None for event in events):
        # A project-less row is a Studio `library.*` event (ck_events_project_scope):
        # it belongs to the studio of its library resource, so another studio's
        # rows never join this listing (DEC-0382).
        events = await events_in_studio(session, events, principal.studio_id)
    return events


async def authorize_stream(
    session: AsyncSession, principal: Principal, project_id: UUID | None
) -> None:
    """Opening check of `GET /events/stream`, run before the response starts
    so an inaccessible project is a plain 403 (DEC-0103 §9). A project-less
    (global, Studio `library.*` only) stream needs no project check — any
    authenticated principal may open it. A project of another studio answers
    like an unknown one."""
    if project_id is None:
        return
    await ensure_project_in_studio(session, principal, project_id)


async def stream_global_access_still_valid(
    machine_id: UUID,
    jwt_auth_version: int | None = None,
    studio_id: UUID | None = None,
) -> bool:
    """Periodic revalidation of a project-less (global) stream: same
    credential/state checks as `stream_access_still_valid`, but no project
    membership — Studio `library.*` events stay visible for as long as its
    credential is valid and, when `studio_id` is given, the user is still a
    member of that studio (losing it ends the stream, DEC-0382)."""
    async with get_session_factory()() as session:
        machine = await session.get(MachineModel, machine_id)
        if machine is None or machine.credential_revoked_at is not None:
            return False
        user = await session.get(UserModel, machine.owner_user_id)
        if user is None or not user.is_active:
            return False
        if jwt_auth_version is not None and user.auth_version != jwt_auth_version:
            return False
        if studio_id is not None:
            return await studio_role_for_user(session, user.id, studio_id) is not None
    return True


async def stream_access_still_valid(
    machine_id: UUID, project_id: UUID, jwt_auth_version: int | None = None
) -> bool:
    """Periodic revalidation of an open stream (DEC-0103 §9, DEC-0110): the
    request's session is closed for the connection's lifetime, so this
    reloads the machine, its owner's state, role and memberships on a
    short-lived session of its own. A revoked credential, a disabled or
    unverified owner, a revoked JWT session or a lost membership closes the
    stream."""
    async with get_session_factory()() as session:
        machine = await session.get(MachineModel, machine_id)
        if machine is None or machine.credential_revoked_at is not None:
            return False
        user = await session.get(UserModel, machine.owner_user_id)
        if user is None or not user.is_active:
            return False
        if jwt_auth_version is not None and user.auth_version != jwt_auth_version:
            return False
        return await project_access_for_user(session, user.id, project_id)
