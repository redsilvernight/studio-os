from __future__ import annotations

import re
import uuid
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import Field
from sqlalchemy import select
from studio_contracts.common import ContractModel

from studio_api.db.models.studio import StudioMembershipModel, StudioModel
from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    RESP_401_UNAUTHORIZED,
    RESP_402_PLAN_LIMIT,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
)
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
async def list_studios(session: DbSession, principal: CurrentPrincipal) -> list[StudioSummary]:
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


class StudioCreate(ContractModel):
    name: str = Field(min_length=1, max_length=80)


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "studio"
    return f"{base}-{uuid.uuid4().hex[:6]}"


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=StudioSummary,
    description=(
        "Creates a studio on the default plan; the caller becomes its `owner`. "
        "Creating one past the account's `studios_per_account` ceiling answers "
        "`402 plan_limit_reached`; listing studios is never blocked."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_402_PLAN_LIMIT},
)
async def create_studio(
    payload: StudioCreate, session: DbSession, principal: CurrentPrincipal
) -> StudioSummary:
    await entitlements_service.enforce_studios_per_account(session, principal.user.id)
    plan = await entitlements_service.default_plan_code(session)
    studio = StudioModel(name=payload.name.strip(), slug=_slug(payload.name), plan=plan)
    session.add(studio)
    await session.flush()
    session.add(
        StudioMembershipModel(
            studio_id=studio.id,
            user_id=principal.user.id,
            role="owner",
            granted_by_user_id=principal.user.id,
        )
    )
    await session.commit()
    return StudioSummary(
        id=studio.id,
        name=studio.name,
        slug=studio.slug,
        plan=studio.plan,
        status=studio.status,
        role="owner",
    )
