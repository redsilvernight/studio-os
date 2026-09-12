from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.idempotency import IdempotencyKeyModel


def hash_request(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


async def get_replayed_response(
    session: AsyncSession, idempotency_key: str, endpoint: str
) -> dict[str, Any] | None:
    result = await session.execute(
        select(IdempotencyKeyModel).where(
            IdempotencyKeyModel.idempotency_key == idempotency_key,
            IdempotencyKeyModel.endpoint == endpoint,
        )
    )
    row = result.scalar_one_or_none()
    return row.response_body if row is not None else None


async def store_response(
    session: AsyncSession,
    idempotency_key: str,
    endpoint: str,
    request_hash: str,
    response_status: int,
    response_body: dict[str, Any],
) -> None:
    """Best-effort: a race on the same key is fine — the loser's write conflicts
    on the unique constraint and the caller falls back to the replay path."""
    session.add(
        IdempotencyKeyModel(
            idempotency_key=idempotency_key,
            endpoint=endpoint,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
            created_at=datetime.now(UTC),
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()


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
    transfers creation routes."""
    if idempotency_key is None:
        return await create()

    replayed = await get_replayed_response(session, idempotency_key, endpoint)
    if replayed is not None:
        return cast(ModelT, response_model.model_validate(replayed))  # type: ignore[attr-defined]

    result = await create()
    body = await request.body()
    dumped = result.model_dump(mode="json")  # type: ignore[attr-defined]
    await store_response(
        session, idempotency_key, endpoint, hash_request(body), status_code, dumped
    )
    return result
