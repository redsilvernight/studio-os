from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from studio_contracts.auth import Role, User, UserCreate

from studio_api.db.models.user import UserModel
from studio_api.deps import CurrentMachine, DbSession, require_roles
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN
from studio_api.services import provisioning as provisioning_service

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get(
    "",
    response_model=list[User],
    description=(
        "Admin user directory, used to pick who to add to a project. "
        "Requires the admin role: any other role gets `403 forbidden` "
        "before any lookup. `q` filters on a case-insensitive substring of "
        "the display name or email; results are sorted by display name "
        "then email and capped by `limit`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_users(
    session: DbSession,
    _admin: Annotated[UserModel, Depends(require_roles(Role.ADMIN))],
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[User]:
    users = await provisioning_service.list_users(session, q, limit)
    return [User.model_validate(u) for u in users]


@router.post(
    "",
    response_model=User,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Provision a new user with a role (`admin`, `developer`, "
        "`agent`, or `readonly` — the role alone decides what the "
        "user's machines may do). Requires the admin role. Emails are "
        "unique: reusing one fails with 409. Deliberately "
        "not replayable: no `Idempotency-Key`. The very first (admin) "
        "user is created out of band, never through this endpoint."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def create_user(
    user_in: UserCreate,
    session: DbSession,
    machine: CurrentMachine,
    _owner: Annotated[UserModel, Depends(require_roles(Role.ADMIN))],
) -> User:
    user = await provisioning_service.create_user(
        session, user_in.display_name, user_in.email, user_in.role.value
    )
    return User.model_validate(user)
