from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from studio_contracts.project_context import DEFAULT_MAX_CHARS
from studio_contracts.sync import (
    SYNC_DEFAULT_LIMIT,
    SyncResult,
)

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_ACTOR_NOT_OWNED,
)
from studio_api.services import sync as sync_service

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.get(
    "",
    response_model=SyncResult,
    description=(
        "Resynchronise one work session (C2): what changed since the last "
        "sync that concerns this work, as a compact bounded answer. "
        "`session_id` selects the session (its task is used, its stored "
        "cursor is the default start); without it, `agent_id` + `task_id` "
        "is a stateless lookup persisting nothing. `ack` acknowledges the "
        "highest processed `seq`: the stored cursor advances monotonically "
        "to it (a stale replay changes nothing), and `next_cursor` in the "
        "answer is what to ack next. `files` scopes claim overlap to "
        "declared paths. `limit`/`max_chars` bound the answer (same budget "
        "as `prepare_context`); the remainder surfaces as per-`why` "
        "`overflow` counters, and a truncated scan sets `resync` (see "
        "`prepare_context` — raw history is never dumped). An empty answer "
        "serialises to well under 300 characters. Own-machine events are "
        "excluded; items are ids only, `seq` ascending, then live "
        "overlapping claims. `422 invalid_sync_input` on bad identity or "
        "bounds; `404 session_not_found` on unknown or ended session; `409 "
        "actor_not_owned` when `agent_id` is not on the caller's machine."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_ACTOR_NOT_OWNED,
    },
)
async def get_sync(
    session: DbSession,
    principal: CurrentPrincipal,
    session_id: UUID | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    task_id: UUID | None = Query(default=None),
    ack: int | None = Query(default=None),
    files: list[str] | None = Query(default=None),
    limit: int = Query(default=SYNC_DEFAULT_LIMIT),
    max_chars: int = Query(default=DEFAULT_MAX_CHARS),
) -> SyncResult:
    return await sync_service.sync(
        session,
        principal,
        session_id=session_id,
        agent_id=agent_id,
        task_id=task_id,
        ack=ack,
        files=files,
        limit=limit,
        max_chars=max_chars,
    )
