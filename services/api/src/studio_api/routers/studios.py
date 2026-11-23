from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from studio_api.db.models.studio import StudioMembershipModel, StudioModel
from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN, RESP_404_NOT_FOUND
from studio_api.services import entitlements as entitlements_service
from studio_api.services.authz import forbidden
from studio_api.services.entitlements import StudioEntitlements, StudioSummary

router = APIRouter(prefix="/api/v1/studios", tags=["studios"])


@router.get(
    "",
    response_model=list[StudioSummary],
    description=(
        "Studios the authenticated user is a member of, oldest first. "
        "Each entry carries the studio `id`, `name`, `slug`, its `plan` "
        "code (resolved by the plans module, falling back to the default "
        "plan when the stored code is unknown), its `status` (`active` or "
        "`suspended`) and the caller's own `role` in that studio. Isolation "
        "is absolute: a studio the caller is not a member of never appears, "
        "even for the instance operator."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_studios(
    session: DbSession, principal: CurrentPrincipal
) -> list[StudioSummary]:
    return await entitlements_service.list_studios_for_user(session, principal.user.id)


@router.get(
    "/{studio_id}/entitlements",
    response_model=StudioEntitlements,
    description=(
        "Plan, declarative limits and measured counters of one studio, for "
        "any member (`viewer` included): this is a read, never blocked by a "
        "limit. `limits` is exactly what the plan declares (`max_value: "
        "null` means unlimited); `counters` is the studio consumption fed by "
        "the phase-M measurements (storage, SSE) and direct counts (projects, "
        "members, machines). `upgrade_url` is the subscription screen used by "
        "every `plan_limit_reached` refusal."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_studio_entitlements(
    studio_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> StudioEntitlements:
    studio = await session.get(StudioModel, studio_id)
    if studio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "studio not found")
    member = await session.scalar(
        select(StudioMembershipModel.studio_id).where(
            StudioMembershipModel.studio_id == studio_id,
            StudioMembershipModel.user_id == principal.user.id,
        )
    )
    if member is None:
        raise forbidden("studio", "read")
    entitlements = await entitlements_service.studio_entitlements(session, studio_id)
    # The counters are a cache: persist the refreshed values, the response is a read.
    await session.commit()
    return entitlements
