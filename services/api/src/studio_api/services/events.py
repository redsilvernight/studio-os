from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.events import EventCreate, EventEnvelope, EventType

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session_factory
from studio_api.services import event_stream
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_project_access,
    has_project_access,
    load_project_scope,
    project_visibility_clause,
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
    party's stored response. The project write check (DEC-0100 §12) runs
    first, for the same reason and so an inaccessible project's `event_id`
    replay never reveals whether it exists.

    Only for the public creation path (`POST /events`, `studio_emit_event`).
    Server-internal code that calls `create_event` directly (e.g. the
    `resource.conflict` event in `routers/claims.py`) is exempt — it is
    trusted code, not client input. `actor_type="system"` IS a legitimate
    client submission here too (git/godot watchers, DEC-0032, replayed
    through the outbox like any other event) — restricted to
    `actor_id == machine.id`, the machine self-attributing its own
    automated event.
    """
    ensure_project_access(principal, event_in.project_id, "write")
    ensure_can_write(principal, "event")
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
        if agent is None or agent.machine_id != machine.id:
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


def publish_event(event: EventModel) -> None:
    """Realtime fan-out of a *committed* event (`seq` is assigned by then)."""
    event_stream.publish(
        event_stream.StreamEvent(
            seq=event.seq,
            project_id=event.project_id,
            envelope=EventEnvelope.model_validate(event),
        )
    )


async def stage_event(session: AsyncSession, event_in: EventCreate) -> EventModel:
    """Insert the event in the caller's transaction (flush only, no commit) so a
    unit of work and its audit trail become durable atomically. The caller
    commits, refreshes the row and calls `publish_event`. Server-internal use;
    idempotent on `event_id` like `create_event`."""
    existing = await session.get(EventModel, event_in.event_id)
    if existing is not None:
        return existing
    event = _new_event_row(event_in)
    session.add(event)
    await session.flush()
    return event


async def create_event(session: AsyncSession, event_in: EventCreate) -> EventModel:
    """Idempotent on `event_id`: a replay (offline queue retry, at-least-once
    delivery) returns the already-stored row instead of inserting a duplicate."""
    existing = await session.get(EventModel, event_in.event_id)
    if existing is not None:
        return existing

    event = _new_event_row(event_in)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    publish_event(event)
    return event


def _as_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(value)


async def list_events_after(
    session: AsyncSession,
    principal: Principal,
    project_id: UUID | str,
    after_seq: int | None,
    limit: int = 500,
) -> list[EventModel]:
    """Realtime catch-up (DEC-0018): `seq` is a strictly monotonic identity
    column, unlike `server_timestamp` which can collide under concurrent
    writes — safe to use as a no-loss/no-duplicate resume cursor."""
    ensure_project_access(principal, _as_uuid(project_id))
    stmt = (
        select(EventModel)
        .where(EventModel.project_id == project_id)
        .order_by(EventModel.seq.asc())
        .limit(limit)
    )
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
) -> list[EventModel]:
    stmt = select(EventModel).order_by(EventModel.server_timestamp.desc()).limit(limit)
    if project_id is not None:
        ensure_project_access(principal, _as_uuid(project_id))
        stmt = stmt.where(EventModel.project_id == project_id)
    elif (visible := project_visibility_clause(principal, EventModel.project_id)) is not None:
        stmt = stmt.where(visible)
    if task_id is not None:
        # A task of an inaccessible project answers the project 403, not an
        # empty listing (DEC-0100 §8); an unknown task filters to nothing.
        await tasks_service.read_task(session, principal, _as_uuid(task_id))
        stmt = stmt.where(EventModel.task_id == task_id)
    if since is not None:
        stmt = stmt.where(EventModel.server_timestamp >= since)
    if event_type is not None:
        stmt = stmt.where(EventModel.event_type == event_type.value)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def authorize_stream(principal: Principal, project_id: UUID) -> None:
    """Opening check of `GET /events/stream`, run before the response starts
    so an inaccessible project is a plain 403 (DEC-0100 §9)."""
    ensure_project_access(principal, project_id)


async def stream_access_still_valid(
    machine_id: UUID, project_id: UUID, jwt_auth_version: int | None = None
) -> bool:
    """Periodic revalidation of an open stream (DEC-0100 §9, DEC-0110): the
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
        scope = await load_project_scope(session, user.id, Role(user.role))
    return has_project_access(
        Principal(machine=machine, user=user, role=Role(user.role), project_scope=scope),
        project_id,
    )
