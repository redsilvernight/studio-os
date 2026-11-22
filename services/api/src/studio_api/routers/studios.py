"""Studios, invitations and membership management (`/api/v1/studios`, 0050).

Every studio route names its studio in the path and revalidates the caller's
membership of *that* studio (and its role there): `owner`/`admin` manage
members and invitations, only `owner` transfers ownership. The public
invitation preview never leaks more than the studio name, the invited role and
the inviter's display name; accepting a secret stays authenticated and
single-use.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.studio import (
    StudioInvitationModel,
    StudioMembershipModel,
    StudioModel,
    StudioRole,
)
from studio_api.db.models.user import UserModel
from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.mailer import EmailSender, OutgoingEmail, deliver, get_email_sender
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import studios as studios_service
from studio_api.services.authz import (
    Principal,
    ensure_studio_role,
)
from studio_api.settings import Settings, get_settings

router = APIRouter(prefix="/api/v1", tags=["studios"])

EmailAddress = Annotated[
    str,
    Field(
        ...,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+$",
        examples=["ada@example.com"],
    ),
]


class StudioSummary(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    plan: str
    status: str
    role: StudioRole


class StudioDetail(StudioSummary):
    deletion_scheduled_at: datetime | None = Field(
        default=None,
        description=(
            "When the studio is scheduled for deletion, or null. Always null "
            "until migration 0051 adds the column; clients may rely on the key."
        ),
    )


class StudioCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["Ada's Studio"])

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class InvitationCreateRequest(BaseModel):
    email: EmailAddress
    role: StudioRole = StudioRole.MEMBER


class InvitationRead(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    consumed_at: datetime | None
    invited_by_user_id: uuid.UUID | None
    created_at: datetime | None


class InvitationPreviewRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)


class InvitationPreviewResponse(BaseModel):
    state: studios_service.InvitationState
    studio_name: str | None = None
    role: str | None = None
    inviter_display_name: str | None = None


class InvitationAcceptRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)


class InvitationAccepted(BaseModel):
    studio_id: uuid.UUID
    role: str


class MemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: str
    granted_by_user_id: uuid.UUID | None
    created_at: datetime | None


class MemberRoleRequest(BaseModel):
    role: StudioRole


class TransferOwnershipRequest(BaseModel):
    user_id: uuid.UUID


def _summary(studio: StudioModel, role: StudioRole) -> StudioSummary:
    return StudioSummary(
        id=studio.id,
        slug=studio.slug,
        name=studio.name,
        plan=studio.plan,
        status=studio.status,
        role=role,
    )


def _invitation(invitation: StudioInvitationModel) -> InvitationRead:
    return InvitationRead(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        consumed_at=invitation.consumed_at,
        invited_by_user_id=invitation.invited_by_user_id,
        created_at=invitation.created_at,
    )


def _member(membership: StudioMembershipModel, user: UserModel) -> MemberRead:
    return MemberRead(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
        granted_by_user_id=membership.granted_by_user_id,
        created_at=membership.created_at,
    )


async def _studio_of(
    session: AsyncSession, principal: Principal, studio_id: uuid.UUID
) -> Principal:
    """The caller's Principal re-resolved in the studio named by the path."""
    return await studios_service.studio_principal(session, principal, studio_id)


@router.get(
    "/studios",
    response_model=list[StudioSummary],
    description=(
        "Studios the caller belongs to, oldest membership first, each with the "
        "caller's `role` there (`owner|admin|member|viewer`). This is how a "
        "client picks the value it later sends as `X-Studio-Id`."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_studios(session: DbSession, principal: CurrentPrincipal) -> list[StudioSummary]:
    rows = await studios_service.list_user_studios(session, principal.user.id)
    return [_summary(studio, role) for studio, role in rows]


@router.post(
    "/studios",
    response_model=StudioSummary,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Create a studio; the caller becomes its `owner`. The slug is derived "
        "from the name, lower-cased, and made unique by suffixing (`-2`, ...). "
        "`Idempotency-Key` is optional: replaying the same key with the same "
        "body returns the original studio instead of creating a second one."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def create_studio(
    payload: StudioCreateRequest,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> StudioSummary:
    async def _create() -> dict[str, Any]:
        studio = await studios_service.create_studio(session, principal.user, payload.name)
        await session.commit()
        return _summary(studio, StudioRole.OWNER).model_dump(mode="json")

    body = await idempotency_service.run_idempotent_dict(
        session,
        idempotency_key,
        "POST /studios",
        idempotency_service.hash_request(await request.body()),
        _create,
        status.HTTP_201_CREATED,
        studio_id=idempotency_service.INSTANCE_SCOPE,
    )
    return StudioSummary.model_validate(body)


@router.get(
    "/studios/{studio_id}",
    response_model=StudioDetail,
    description=(
        "One studio the caller belongs to, with the caller's `role` there. "
        "Another studio answers the same `403 forbidden` as an unknown one. "
        "`deletion_scheduled_at` is always null until migration 0051."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def get_studio(
    studio_id: uuid.UUID, session: DbSession, principal: CurrentPrincipal
) -> StudioDetail:
    studio, role = await studios_service.get_user_studio(session, principal.user.id, studio_id)
    return StudioDetail(**_summary(studio, role).model_dump(), deletion_scheduled_at=None)


@router.post(
    "/studios/{studio_id}/invitations",
    response_model=InvitationRead,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Invite one address to the studio (`owner`/`admin` only). The role is "
        "`admin`, `member` or `viewer` — ownership is granted by "
        "`transfer-ownership` only. The response never reveals whether the "
        "address already has an account; the single-use secret is sent by "
        "e-mail only. A new invitation for the same address invalidates the "
        "previous pending one."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def create_invitation(
    studio_id: uuid.UUID,
    payload: InvitationCreateRequest,
    request: Request,
    background: BackgroundTasks,
    session: DbSession,
    principal: CurrentPrincipal,
    settings: Settings = Depends(get_settings),
    sender: EmailSender = Depends(get_email_sender),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> InvitationRead:
    actor = await _studio_of(session, principal, studio_id)
    ensure_studio_role(actor, StudioRole.ADMIN)

    async def _create() -> dict[str, Any]:
        issued = await studios_service.invite(session, actor, payload.email, payload.role.value)
        message: OutgoingEmail = studios_service.invitation_email(
            settings, issued.invitation, issued.secret, issued.studio_name
        )
        background.add_task(deliver, sender, message)
        await session.commit()
        return _invitation(issued.invitation).model_dump(mode="json")

    body = await idempotency_service.run_idempotent_dict(
        session,
        idempotency_key,
        "POST /studios/{studio_id}/invitations",
        idempotency_service.hash_request(await request.body()),
        _create,
        status.HTTP_201_CREATED,
        studio_id=actor.studio_id,
    )
    return InvitationRead.model_validate(body)


@router.get(
    "/studios/{studio_id}/invitations",
    response_model=list[InvitationRead],
    description=(
        "Invitations issued for this studio, newest first, consumed and "
        "expired ones included for auditing (`owner`/`admin` only). Secrets "
        "are never returned: only their hash is stored."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_invitations(
    studio_id: uuid.UUID, session: DbSession, principal: CurrentPrincipal
) -> list[InvitationRead]:
    actor = await _studio_of(session, principal, studio_id)
    ensure_studio_role(actor, StudioRole.ADMIN)
    return [
        _invitation(invitation)
        for invitation in await studios_service.list_invitations(session, studio_id)
    ]


@router.delete(
    "/studios/{studio_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Revoke a pending invitation (`owner`/`admin` only). The link stops "
        "working immediately; the row is removed. Unknown id: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def delete_invitation(
    studio_id: uuid.UUID,
    invitation_id: uuid.UUID,
    session: DbSession,
    principal: CurrentPrincipal,
) -> None:
    actor = await _studio_of(session, principal, studio_id)
    ensure_studio_role(actor, StudioRole.ADMIN)
    await studios_service.delete_invitation(session, studio_id, invitation_id)


@router.post(
    "/invitations/preview",
    response_model=InvitationPreviewResponse,
    description=(
        "Public, non-consuming preview of an invitation link: `state` is "
        "`valid`, `expired`, `used` or `unknown`. Only the studio name, the "
        "invited role and the inviter's display name are returned, all null "
        "when the secret is unknown. Nothing else is ever disclosed and the "
        "secret is not consumed."
    ),
)
async def preview_invitation(
    payload: InvitationPreviewRequest, session: DbSession
) -> InvitationPreviewResponse:
    preview = await studios_service.preview_invitation(session, payload.token)
    return InvitationPreviewResponse(
        state=preview.state,
        studio_name=preview.studio_name,
        role=preview.role,
        inviter_display_name=preview.inviter_display_name,
    )


@router.post(
    "/invitations/accept",
    response_model=InvitationAccepted,
    description=(
        "Consume an invitation secret and join its studio with the invited "
        "role. Requires an authenticated caller whose account e-mail is the "
        "invited address (`403 invitation_email_mismatch`, nothing consumed, "
        "otherwise). A secret works once; unknown, expired and already "
        "consumed secrets answer `410` with `invitation_unknown`, "
        "`invitation_expired` or `invitation_used`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def accept_invitation(
    payload: InvitationAcceptRequest, session: DbSession, principal: CurrentPrincipal
) -> InvitationAccepted:
    membership = await studios_service.accept_invitation(session, principal.user, payload.token)
    return InvitationAccepted(studio_id=membership.studio_id, role=membership.role)


@router.get(
    "/studios/{studio_id}/members",
    response_model=list[MemberRead],
    description=(
        "Members of the studio and their role, oldest grant first. Readable by "
        "every member of that studio, including `viewer`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_members(
    studio_id: uuid.UUID, session: DbSession, principal: CurrentPrincipal
) -> list[MemberRead]:
    actor = await _studio_of(session, principal, studio_id)
    ensure_studio_role(actor, StudioRole.VIEWER)
    rows = await studios_service.list_members(session, studio_id)
    return [_member(membership, user) for membership, user in rows]


@router.patch(
    "/studios/{studio_id}/members/{user_id}",
    response_model=MemberRead,
    description=(
        "Change a member's role (`owner`/`admin` only). Promoting to `owner` "
        "requires an `owner`; demoting or removing the last `owner` answers "
        "`409 last_owner_required`. A caller can never change its own role "
        "(`403 self_modification_forbidden`)."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def update_member_role(
    studio_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberRoleRequest,
    session: DbSession,
    principal: CurrentPrincipal,
) -> MemberRead:
    actor = await _studio_of(session, principal, studio_id)
    ensure_studio_role(actor, StudioRole.ADMIN)
    membership = await studios_service.update_member_role(
        session, actor, user_id, payload.role.value
    )
    user = await session.get(UserModel, user_id)
    assert user is not None
    return _member(membership, user)


@router.delete(
    "/studios/{studio_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Remove a member from the studio (`owner`/`admin` only). Removing the "
        "last `owner` answers `409 last_owner_required`; a caller can never "
        "remove itself this way (`403 self_modification_forbidden`)."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def remove_member(
    studio_id: uuid.UUID,
    user_id: uuid.UUID,
    session: DbSession,
    principal: CurrentPrincipal,
) -> None:
    actor = await _studio_of(session, principal, studio_id)
    ensure_studio_role(actor, StudioRole.ADMIN)
    await studios_service.remove_member(session, actor, user_id)


@router.post(
    "/studios/{studio_id}/transfer-ownership",
    response_model=MemberRead,
    description=(
        "Transfer ownership (`owner` only): the target becomes `owner` and the "
        "caller becomes `admin` in the same commit, so the studio never has "
        "zero owners. Targeting another studio member is required (404 "
        "otherwise); transferring to oneself is refused."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def transfer_ownership(
    studio_id: uuid.UUID,
    payload: TransferOwnershipRequest,
    session: DbSession,
    principal: CurrentPrincipal,
) -> MemberRead:
    actor = await _studio_of(session, principal, studio_id)
    membership = await studios_service.transfer_ownership(session, actor, payload.user_id)
    user = await session.get(UserModel, payload.user_id)
    assert user is not None
    return _member(membership, user)
