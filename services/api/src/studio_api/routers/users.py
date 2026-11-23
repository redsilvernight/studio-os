from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from studio_contracts.auth import User, UserCreate
from studio_contracts.projects import ProjectMember

from studio_api.db.models.studio import StudioRole
from studio_api.deps import CurrentMachine, DbSession, require_operator, require_studio_role
from studio_api.openapi_meta import (
    RESP_401_UNAUTHORIZED,
    RESP_402_PLAN_LIMIT,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
)
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services.authz import Principal

OperatorPrincipal = Annotated[Principal, Depends(require_operator)]

router = APIRouter(prefix="/api/v1/users", tags=["users"])
studio_router = APIRouter(prefix="/api/v1/studio", tags=["studio"])


@router.get(
    "",
    response_model=list[User],
    description=(
        "Instance user directory (every account). Requires the instance "
        "operator (`is_operator`): anyone else gets `403 forbidden` before any "
        "lookup. To pick who to add to a project, a studio `owner`/`admin` uses "
        "`GET /studio/members`. `q` filters on a case-insensitive substring of "
        "the display name or email; results are sorted by display name "
        "then email and capped by `limit`. Each User carries its derived "
        "account `status` (`pending`, `active`, `disabled`)."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_users(
    session: DbSession,
    _operator: OperatorPrincipal,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[User]:
    users = await provisioning_service.list_users(session, q, limit)
    return [User.model_validate(u) for u in users]


@studio_router.get(
    "/members",
    response_model=list[User],
    description=(
        "Directory of the accounts that are members of the active studio, used "
        "to pick who to add to a project. Requires `owner` or `admin` of the "
        "active studio (`403 forbidden` otherwise, before any lookup); never "
        "lists another studio's accounts. Same filters, order and `status` as "
        "`GET /users`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_studio_members(
    session: DbSession,
    principal: Annotated[Principal, Depends(require_studio_role(StudioRole.ADMIN))],
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[User]:
    users = await provisioning_service.list_users(session, q, limit, principal.studio_id)
    return [User.model_validate(u) for u in users]


@router.post(
    "",
    response_model=User,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Provision a new user with a role (`admin`, `developer`, "
        "`agent`, or `readonly` — the role alone decides what the "
        "user's machines may do). Requires the instance operator. The email is "
        "stored trimmed and lower-cased and is unique regardless of case: "
        "reusing one fails with 409. Deliberately "
        "not replayable: no `Idempotency-Key`. The very first (admin) "
        "user is created out of band, never through this endpoint. Joining "
        "the studio is a member write: a full studio answers `402 "
        "plan_limit_reached` (the account directory stays readable)."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_402_PLAN_LIMIT, **RESP_403_FORBIDDEN},
)
async def create_user(
    user_in: UserCreate,
    session: DbSession,
    machine: CurrentMachine,
    _operator: OperatorPrincipal,
) -> User:
    user = await provisioning_service.create_user(
        session, user_in.display_name, user_in.email, user_in.role.value
    )
    return User.model_validate(user)


_SELF_403 = (
    "Targeting your own account: `403 {error_code: self_modification_forbidden}`, "
    "checked before any lookup."
)


@router.post(
    "/{user_id}/disable",
    response_model=User,
    description=(
        "Disable an account (operator only; idempotent). Every JWT of the User "
        "is revoked (`auth_version` bumped), every machine it owns is refused "
        "while it stays disabled, and its open event streams close. "
        + _SELF_403
        + " Unknown user: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def disable_user(user_id: UUID, session: DbSession, operator: OperatorPrincipal) -> User:
    provisioning_service.ensure_not_self(operator.user, user_id, "disable")
    user = await provisioning_service.get_user_or_404(session, user_id)
    return User.model_validate(await provisioning_service.disable_account(session, user))


@router.post(
    "/{user_id}/enable",
    response_model=User,
    description=(
        "Lift a deactivation (operator only; idempotent). Earlier JWTs stay "
        "invalid; the User's machines work again. An account whose email is "
        "not verified stays `pending`: activation requires verification. "
        + _SELF_403
        + " Unknown user: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def enable_user(user_id: UUID, session: DbSession, operator: OperatorPrincipal) -> User:
    provisioning_service.ensure_not_self(operator.user, user_id, "enable")
    user = await provisioning_service.get_user_or_404(session, user_id)
    return User.model_validate(await provisioning_service.enable_account(session, user))


@router.post(
    "/{user_id}/revoke-sessions",
    response_model=User,
    description=(
        "Revoke every dashboard session (JWT) of a User (operator only): "
        "`auth_version` is bumped, machine tokens are untouched. "
        + _SELF_403
        + " Unknown user: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def revoke_user_sessions(
    user_id: UUID, session: DbSession, operator: OperatorPrincipal
) -> User:
    provisioning_service.ensure_not_self(operator.user, user_id, "revoke_sessions")
    user = await provisioning_service.get_user_or_404(session, user_id)
    return User.model_validate(await provisioning_service.revoke_sessions_of(session, user))


@router.get(
    "/{user_id}/memberships",
    response_model=list[ProjectMember],
    description=(
        "Projects a User can access (operator only), oldest grant first. Access "
        "is granted or removed with `PUT`/`DELETE "
        "/projects/{project_id}/members/{user_id}`. Unknown user: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def list_user_memberships(
    user_id: UUID, session: DbSession, _operator: OperatorPrincipal
) -> list[ProjectMember]:
    user = await provisioning_service.get_user_or_404(session, user_id)
    memberships = await projects_service.list_user_memberships(session, user.id)
    return [
        ProjectMember.model_validate(m).model_copy(
            update={"user_display_name": user.display_name, "user_email": user.email}
        )
        for m in memberships
    ]
