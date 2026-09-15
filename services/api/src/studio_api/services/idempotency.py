from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.idempotency import IdempotencyKeyModel, IdempotencyStatus

_POLL_INTERVAL_SECONDS = 0.05
_POLL_TIMEOUT_SECONDS = 5.0
_PENDING_RECLAIM_SECONDS = 30.0


def hash_request(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


async def _get_row(
    session: AsyncSession, idempotency_key: str, endpoint: str
) -> IdempotencyKeyModel | None:
    """`populate_existing()` forces a fresh read of every mapped column.
    Without it, a session that already loaded this row (e.g. a poller in
    `_await_completion` re-querying the same row across iterations) gets back
    the identity-mapped Python object as it was on first load — `status`
    would never appear to flip from pending to completed."""
    result = await session.execute(
        select(IdempotencyKeyModel)
        .where(
            IdempotencyKeyModel.idempotency_key == idempotency_key,
            IdempotencyKeyModel.endpoint == endpoint,
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def _reserve(
    session: AsyncSession, idempotency_key: str, endpoint: str, request_hash: str
) -> bool:
    """Atomically claims (idempotency_key, endpoint) for this request.

    The unique constraint on (idempotency_key, endpoint) makes this race-safe
    across processes: two truly concurrent requests both attempt this insert,
    Postgres allows exactly one of them through, and the loser gets 0 rows
    affected (`ON CONFLICT DO NOTHING`) instead of an exception."""
    stmt = (
        pg_insert(IdempotencyKeyModel)
        .values(
            idempotency_key=idempotency_key,
            endpoint=endpoint,
            request_hash=request_hash,
            status=IdempotencyStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_idempotency_endpoint")
        .returning(IdempotencyKeyModel.id)
    )
    result = await session.execute(stmt)
    won = result.scalar_one_or_none() is not None
    await session.commit()
    return won


async def _reclaim_if_abandoned(
    session: AsyncSession, idempotency_key: str, endpoint: str, request_hash: str
) -> bool:
    """A `pending` reservation older than `_PENDING_RECLAIM_SECONDS` almost
    certainly belongs to a request whose process crashed between `_reserve`
    and `_complete`/`_release` (a crash runs no Python cleanup code, so
    `_release`'s `except Exception` path never fires) — DEC-0015. Without
    this, such a key would be blocked forever. The `WHERE status=pending AND
    created_at<cutoff` guard makes the UPDATE itself the race-safe check: at
    most one of several callers retrying the same abandoned key concurrently
    can match and reclaim it. The threshold is generous relative to the
    business creations this guards (single-row inserts) so it never reclaims
    a request that is merely still running."""
    cutoff = datetime.now(UTC) - timedelta(seconds=_PENDING_RECLAIM_SECONDS)
    stmt = (
        update(IdempotencyKeyModel)
        .where(
            IdempotencyKeyModel.idempotency_key == idempotency_key,
            IdempotencyKeyModel.endpoint == endpoint,
            IdempotencyKeyModel.status == IdempotencyStatus.PENDING,
            IdempotencyKeyModel.created_at < cutoff,
        )
        .values(request_hash=request_hash, created_at=datetime.now(UTC))
        .returning(IdempotencyKeyModel.id)
    )
    result = await session.execute(stmt)
    reclaimed = result.scalar_one_or_none() is not None
    await session.commit()
    return reclaimed


async def _await_completion(
    session: AsyncSession, idempotency_key: str, endpoint: str
) -> IdempotencyKeyModel:
    """Another request already reserved this key and is running the business
    creation; poll the row until it flips to `completed`. Bounded so a
    reservation whose owner crashed mid-creation cannot hang callers forever."""
    elapsed = 0.0
    while elapsed < _POLL_TIMEOUT_SECONDS:
        row = await _get_row(session, idempotency_key, endpoint)
        if row is not None and row.status == IdempotencyStatus.COMPLETED:
            return row
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        elapsed += _POLL_INTERVAL_SECONDS
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        detail={"error_code": "idempotency_key_in_progress"},
    )


async def _resolve_existing(
    session: AsyncSession, idempotency_key: str, endpoint: str
) -> IdempotencyKeyModel:
    row = await _get_row(session, idempotency_key, endpoint)
    if row is not None and row.status == IdempotencyStatus.COMPLETED:
        return row
    return await _await_completion(session, idempotency_key, endpoint)


async def _complete(
    session: AsyncSession,
    idempotency_key: str,
    endpoint: str,
    response_status: int,
    response_body: dict[str, Any],
) -> None:
    row = await _get_row(session, idempotency_key, endpoint)
    if row is None:
        return
    row.status = IdempotencyStatus.COMPLETED
    row.response_status = response_status
    row.response_body = response_body
    await session.commit()


async def _release(session: AsyncSession, idempotency_key: str, endpoint: str) -> None:
    """A failed business creation must not leave the key blocked (roadmap
    'Securiser l'idempotence sous concurrence', critere d'acceptation) —
    drop the reservation so an identical retry can win it and proceed.

    `create()` can fail with the session's transaction already aborted (e.g.
    an `IntegrityError` from a bad FK) — a plain `SELECT` in that state raises
    `PendingRollbackError`, masking the original error and leaving the
    reservation `pending` for `_PENDING_RECLAIM_SECONDS`. Roll back first;
    the reservation itself was committed independently in `_reserve`, so
    nothing legitimate is lost."""
    await session.rollback()
    row = await _get_row(session, idempotency_key, endpoint)
    if row is not None and row.status == IdempotencyStatus.PENDING:
        await session.delete(row)
        await session.commit()


def _reject_payload_mismatch() -> None:
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        detail={"error_code": "idempotency_key_payload_mismatch"},
    )


async def run_idempotent_dict(
    session: AsyncSession,
    idempotency_key: str | None,
    endpoint: str,
    request_hash: str,
    create: Callable[[], Awaitable[dict[str, Any]]],
    response_status: int = 200,
) -> dict[str, Any]:
    """Core reservation/replay logic, independent of FastAPI's `Request` and
    of any particular Pydantic response model — the piece `run_idempotent`
    (HTTP) and MCP tools (`studio_mcp.tools.*`, DEC-0027) both build on, so
    the atomic-reservation guarantee is never duplicated between the two
    call paths (.claude/rules/mcp-tools.md, .claude/rules/python-conventions.md).

    `endpoint` occupies the same `(idempotency_key, endpoint)` unique
    constraint as HTTP routes — callers MUST use a namespace distinct from
    the `"METHOD /path"` strings used by HTTP routers (e.g. `"MCP
    studio_create_task"`, never `"POST /tasks"`) or an unrelated collision on
    `idempotency_key` between an HTTP client and an MCP client would either
    corrupt the unique constraint's semantics or spuriously fail on
    `request_hash` mismatch, since the two callers hash their payload
    differently. This is intentional and documented (DEC-0027, DEC-0024): the
    Bloc B offline outbox replays exclusively via HTTP and never touches MCP
    write tools, so the two spaces are never meant to interoperate."""
    if idempotency_key is None:
        return await create()

    won = await _reserve(session, idempotency_key, endpoint, request_hash)
    if not won:
        won = await _reclaim_if_abandoned(session, idempotency_key, endpoint, request_hash)
    if not won:
        row = await _resolve_existing(session, idempotency_key, endpoint)
        if row.request_hash != request_hash:
            _reject_payload_mismatch()
        return cast(dict[str, Any], row.response_body)

    try:
        result = await create()
    except Exception:
        await _release(session, idempotency_key, endpoint)
        raise

    await _complete(session, idempotency_key, endpoint, response_status, result)
    return result


async def run_idempotent[ModelT](
    session: AsyncSession,
    request: Request,
    idempotency_key: str | None,
    endpoint: str,
    response_model: type[ModelT],
    create: Callable[[], Awaitable[ModelT]],
    status_code: int,
) -> ModelT:
    """Shared replay logic for a POST that supports the `Idempotency-Key`
    header (.claude/rules/contracts.md) — used by tasks/claims/decisions/
    transfers/sessions/ai-work/projects creation routes. Thin wrapper over
    `run_idempotent_dict`: hashes the raw HTTP request body and (de)serializes
    the Pydantic `response_model` around the dict-based core, so the HTTP
    behavior is unchanged (DEC-0015) while the reservation/replay primitives
    stay in one place (DEC-0027).

    (idempotency_key, endpoint) is reserved in the database *before* the
    business creation runs, so at most one caller ever runs `create()` for a
    given pair — the previous implementation ran `create()` first and only
    deduplicated afterwards, letting two concurrent requests each create a
    business row. `request_hash` is enforced: replaying a key with a
    different request body is a client error (409), not a silent replay of
    the first response nor a second resource — see DEC-0015. A `pending`
    reservation abandoned by a crashed owner is reclaimed after
    `_PENDING_RECLAIM_SECONDS` rather than blocking the key forever."""
    if idempotency_key is None:
        return await create()

    request_hash = hash_request(await request.body())

    async def _create_dict() -> dict[str, Any]:
        result = await create()
        return cast(dict[str, Any], result.model_dump(mode="json"))  # type: ignore[attr-defined]

    dumped = await run_idempotent_dict(
        session, idempotency_key, endpoint, request_hash, _create_dict, status_code
    )
    return cast(ModelT, response_model.model_validate(dumped))  # type: ignore[attr-defined]
