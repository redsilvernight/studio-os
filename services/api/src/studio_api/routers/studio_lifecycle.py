"""Studio export and deletion routes (0051).

Kept apart from the member/invitation routes (`routers/studios.py`): this
module owns the owner-only lifecycle — export an archive, request a deletion
with a grace window, cancel it. Both actions are refused to every role but the
studio `owner`; a studio of another tenant answers a plain 404.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN, RESP_404_NOT_FOUND
from studio_api.services import studio_deletion as deletion_service
from studio_api.services import studio_export as export_service
from studio_api.settings import get_settings
from studio_api.storage.provider import get_storage

router = APIRouter(prefix="/api/v1/studios", tags=["studios"])


class DeletionConfirmation(BaseModel):
    """The owner retypes the studio slug: a destructive action needs a
    deliberate, non-replayable confirmation."""

    confirmation: str


@router.post(
    "/{studio_id}/exports",
    status_code=status.HTTP_201_CREATED,
    description=(
        "Export the whole studio as a dated ZIP archive (all projects, tasks, "
        "decisions, roadmaps, members, file metadata and the stored files), "
        "written to object storage. `owner` only; never blocked by a plan or "
        "quota overage (read-only recovery path). The archive is downloadable "
        "through `GET /studios/{studio_id}/exports/{export_id}`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def create_export(
    studio_id: UUID,
    session: DbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    export = await export_service.create_export(
        session, get_storage(), get_settings(), principal, studio_id
    )
    return {
        "id": export.id,
        "studio_id": export.studio_id,
        "created_at": export.created_at,
        "expires_at": export.expires_at,
    }


@router.get(
    "/{studio_id}/exports/{export_id}",
    description=(
        "Short-lived presigned download link of one export archive (at most "
        "15 minutes). `owner` only; an export of another studio or an expired "
        "one answers 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_export(
    studio_id: UUID,
    export_id: UUID,
    session: DbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    export = await export_service.get_export(session, principal, studio_id, export_id)
    url, expires_at = export_service.download_url(get_storage(), get_settings(), export)
    return {"download_url": url, "expires_at": expires_at}


@router.post(
    "/{studio_id}/deletion",
    description=(
        "Request the deletion of the studio: the body must retype the studio "
        "slug (`409 invalid_confirmation` otherwise). The studio becomes "
        "read-only (`status = pending_deletion`) for a configurable grace "
        "window (7 days by default) and is really purged once it elapses. "
        "`owner` only; never allowed on the internal studio. Idempotent: "
        "asking again keeps the first schedule."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        "409": {"description": "The retyped slug does not match (`invalid_confirmation`)."},
    },
)
async def request_deletion(
    studio_id: UUID,
    body: DeletionConfirmation,
    session: DbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    studio = await deletion_service.request_deletion(
        session, get_settings(), principal, studio_id, body.confirmation
    )
    return {
        "deletion_requested_at": studio.deletion_requested_at,
        "deletion_scheduled_at": studio.deletion_scheduled_at,
    }


@router.delete(
    "/{studio_id}/deletion",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Cancel a deletion during the grace window: the schedule is cleared "
        "and the studio returns to `active`. `owner` only; idempotent when "
        "nothing is scheduled."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def cancel_deletion(
    studio_id: UUID,
    session: DbSession,
    principal: CurrentPrincipal,
) -> None:
    await deletion_service.cancel_deletion(session, principal, studio_id)
