"""Studio creation, invitations and membership management (0050).

A self-registered account becomes `owner` of its own studio when its address
is verified, unless a pending invitation targets that address: then it joins
the inviting studio with the invited role instead. Invitation secrets follow
the account-token rule (256-bit random value, only its SHA-256 stored,
expiring, single use) and studio management follows the studio-role ranking of
`services/authz.py`: `owner`/`admin` manage members, only `owner` transfers
ownership, and a studio always keeps at least one owner.

Every manager operation names its studio in the path, so it is checked
against the caller's membership of THAT studio (and the caller's role there),
never against an implicitly resolved active studio.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.studio import (
    StudioInvitationModel,
    StudioMembershipModel,
    StudioModel,
    StudioRole,
)
from studio_api.db.models.user import UserModel
from studio_api.mailer import OutgoingEmail
from studio_api.security import hash_token
from studio_api.services.authz import (
    Principal,
    forbidden,
    is_studio_manager,
    studio_role_for_user,
)
from studio_api.services.provisioning import ensure_not_self, normalize_email
from studio_api.settings import Settings

INVITATION_TTL = timedelta(days=7)
"""How long an invitation link stays usable. Expired and consumed links both
answer 410, never 404: a stranger cannot tell a burned link from an unknown
one."""

INVITABLE_ROLES = frozenset({StudioRole.ADMIN, StudioRole.MEMBER, StudioRole.VIEWER})
"""Roles an invitation may grant. `owner` is deliberately absent: ownership
changes hands only through `transfer-ownership`, which also demotes the
current owner, so a studio never ends up without one."""

InvitationState = Literal["valid", "expired", "used", "unknown"]


@dataclass(frozen=True)
class IssuedInvitation:
    invitation: StudioInvitationModel
    secret: str
    studio_name: str


@dataclass(frozen=True)
class InvitationPreview:
    state: InvitationState
    studio_name: str | None = None
    role: str | None = None
    inviter_display_name: str | None = None


def new_invitation_secret() -> str:
    return secrets.token_urlsafe(32)


def _slug_base(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return slug[:48].strip("-") or "studio"


def _slug_candidate(base: str, attempt: int) -> str:
    suffix = "" if attempt == 1 else f"-{attempt}"
    return f"{base[: 64 - len(suffix)].rstrip('-')}{suffix}"


async def _insert_studio(session: AsyncSession, user: UserModel, name: str) -> StudioModel:
    """Insert a studio named after `name`, its creator as `owner`. The slug is
    derived from the name and made unique by suffixing (`-2`, `-3`, ...); the
    insert runs in a savepoint so a concurrent claim of the same slug retries
    instead of aborting the caller's transaction."""
    base = _slug_base(name)
    display_name = name.strip() or base
    for attempt in range(1, 51):
        studio = StudioModel(
            id=uuid.uuid4(), slug=_slug_candidate(base, attempt), name=display_name
        )
        try:
            async with session.begin_nested():
                session.add(studio)
                await session.flush()
        except IntegrityError:
            continue
        await session.execute(
            pg_insert(StudioMembershipModel)
            .values(
                studio_id=studio.id,
                user_id=user.id,
                role=StudioRole.OWNER.value,
                granted_by_user_id=user.id,
            )
            .on_conflict_do_nothing()
        )
        return studio
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        detail={"error_code": "studio_slug_unavailable", "message": "no free studio slug"},
    )


async def create_studio(session: AsyncSession, user: UserModel, name: str) -> StudioModel:
    """Create a studio on demand (`POST /studios`), its creator as `owner`.
    The caller commits."""
    return await _insert_studio(session, user, name)


async def create_studio_for_user(session: AsyncSession, user: UserModel) -> StudioModel:
    """Create the personal studio of a freshly verified account, with the
    account as its `owner`, named after its display name. The caller commits."""
    return await _insert_studio(session, user, user.display_name)


async def list_user_studios(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[StudioModel, StudioRole]]:
    """Every studio the account belongs to, oldest membership first, with its
    role there."""
    result = await session.execute(
        select(StudioModel, StudioMembershipModel.role)
        .join(StudioMembershipModel, StudioMembershipModel.studio_id == StudioModel.id)
        .where(StudioMembershipModel.user_id == user_id)
        .order_by(StudioMembershipModel.created_at, StudioModel.id)
    )
    return [(studio, StudioRole(role)) for studio, role in result.all()]


async def get_user_studio(
    session: AsyncSession, user_id: uuid.UUID, studio_id: uuid.UUID
) -> tuple[StudioModel, StudioRole]:
    """The studio and the account's role there. A studio the account does not
    belong to answers the same 403 as an unknown one (no existence oracle)."""
    studio = await session.get(StudioModel, studio_id)
    role = await studio_role_for_user(session, user_id, studio_id)
    if studio is None or role is None:
        raise forbidden("studio", "read")
    return studio, role


async def studio_principal(
    session: AsyncSession, principal: Principal, studio_id: uuid.UUID
) -> Principal:
    """Re-resolve the caller's role in the studio named by the path. Unlike an
    implicit active studio, the path id is explicit, so any studio the caller
    belongs to is accepted; a foreign or unknown id answers the same 403."""
    role = await studio_role_for_user(session, principal.user.id, studio_id)
    if role is None:
        raise forbidden("studio", "read")
    return replace(principal, studio_id=studio_id, studio_role=role, project_scope=frozenset())


async def _pending_invitation(session: AsyncSession, email: str) -> StudioInvitationModel | None:
    now = datetime.now(UTC)
    result = await session.execute(
        select(StudioInvitationModel)
        .where(
            func.lower(StudioInvitationModel.email) == normalize_email(email),
            StudioInvitationModel.consumed_at.is_(None),
            StudioInvitationModel.expires_at > now,
        )
        .order_by(StudioInvitationModel.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _consume(session: AsyncSession, invitation_id: uuid.UUID) -> StudioInvitationModel | None:
    """Single conditional UPDATE: of two concurrent consumers of one secret,
    exactly one gets the row back."""
    now = datetime.now(UTC)
    result = await session.execute(
        update(StudioInvitationModel)
        .where(
            StudioInvitationModel.id == invitation_id,
            StudioInvitationModel.consumed_at.is_(None),
            StudioInvitationModel.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(StudioInvitationModel)
    )
    return result.scalar_one_or_none()


async def _join(
    session: AsyncSession, user: UserModel, invitation: StudioInvitationModel
) -> StudioMembershipModel:
    await session.execute(
        pg_insert(StudioMembershipModel)
        .values(
            studio_id=invitation.studio_id,
            user_id=user.id,
            role=invitation.role,
            granted_by_user_id=invitation.invited_by_user_id,
        )
        .on_conflict_do_nothing()
    )
    membership = await session.get(StudioMembershipModel, (invitation.studio_id, user.id))
    assert membership is not None
    if membership.role != StudioRole.OWNER.value and membership.role != invitation.role:
        membership.role = invitation.role
    return membership


async def provision_verified_account(session: AsyncSession, user: UserModel) -> uuid.UUID:
    """Give a just-verified account its place in a studio: join the studio that
    invited its address when a pending invitation exists, otherwise create its
    own studio as `owner`. Returns the studio id. The caller commits."""
    invitation = await _pending_invitation(session, user.email)
    if invitation is not None:
        consumed = await _consume(session, invitation.id)
        if consumed is not None:
            membership = await _join(session, user, consumed)
            return membership.studio_id
    return (await create_studio_for_user(session, user)).id


def invitation_gone(error_code: str) -> HTTPException:
    messages = {
        "invitation_unknown": "this invitation does not exist",
        "invitation_expired": "this invitation has expired",
        "invitation_used": "this invitation has already been used",
    }
    return HTTPException(
        status.HTTP_410_GONE,
        detail={
            "error_code": error_code,
            "message": messages.get(error_code, "this invitation is unusable"),
        },
    )


def owner_required() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "owner_required",
            "message": "only a studio owner may perform this action",
        },
    )


def last_owner_required() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "error_code": "last_owner_required",
            "message": "a studio must keep at least one owner",
        },
    )


def _invalid_role(role: str) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"error_code": "invalid_role", "message": f"role {role!r} is not valid"},
    )


def _not_a_member(user_id: uuid.UUID) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        detail={"error_code": "not_found", "message": f"user {user_id} is not a studio member"},
    )


def _invitation_not_found(invitation_id: uuid.UUID) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        detail={
            "error_code": "not_found",
            "message": f"invitation {invitation_id} not found",
        },
    )


async def invite(
    session: AsyncSession, principal: Principal, email: str, role: str
) -> IssuedInvitation:
    """Issue one invitation for the studio named by the principal,
    invalidating earlier pending ones for the same address. The answer never
    depends on whether the address already has an account."""
    if not is_studio_manager(principal):
        raise forbidden("studio_invitation", "write")
    try:
        invited_role = StudioRole(role)
    except ValueError:
        raise _invalid_role(role) from None
    if invited_role not in INVITABLE_ROLES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "invalid_role", "message": "owner is granted by transfer only"},
        )
    studio = await session.get(StudioModel, principal.studio_id)
    if studio is None:
        raise forbidden("studio", "write")
    normalized = normalize_email(email)
    now = datetime.now(UTC)
    await session.execute(
        update(StudioInvitationModel)
        .where(
            StudioInvitationModel.studio_id == principal.studio_id,
            func.lower(StudioInvitationModel.email) == normalized,
            StudioInvitationModel.consumed_at.is_(None),
            StudioInvitationModel.expires_at > now,
        )
        .values(expires_at=now)
    )
    secret = new_invitation_secret()
    invitation = StudioInvitationModel(
        studio_id=principal.studio_id,
        email=normalized,
        role=invited_role.value,
        token_hash=hash_token(secret),
        expires_at=now + INVITATION_TTL,
        invited_by_user_id=principal.user.id,
    )
    session.add(invitation)
    await session.flush()
    await session.refresh(invitation)
    return IssuedInvitation(invitation=invitation, secret=secret, studio_name=studio.name)


def invitation_email(
    settings: Settings, invitation: StudioInvitationModel, secret: str, studio_name: str
) -> OutgoingEmail:
    link = f"{settings.public_base_url.rstrip('/')}/invitations#token={secret}"
    return OutgoingEmail(
        to=invitation.email,
        subject=f"Studio OS — invitation à rejoindre {studio_name}",
        body=(
            "Bonjour,\n\n"
            f"Vous êtes invité·e à rejoindre le studio « {studio_name} » sur "
            f"Studio OS avec le rôle {invitation.role}.\n\n"
            "Pour accepter, ouvrez ce lien :\n\n"
            f"{link}\n\n"
            f"Il expire dans {INVITATION_TTL.days} jours et ne fonctionne qu'une "
            "fois. Si vous n'attendiez rien, ignorez ce message.\n"
        ),
        kind="studio_invitation",
    )


async def list_invitations(
    session: AsyncSession, studio_id: uuid.UUID
) -> list[StudioInvitationModel]:
    result = await session.execute(
        select(StudioInvitationModel)
        .where(StudioInvitationModel.studio_id == studio_id)
        .order_by(StudioInvitationModel.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_invitation(
    session: AsyncSession, studio_id: uuid.UUID, invitation_id: uuid.UUID
) -> None:
    result = await session.execute(
        delete(StudioInvitationModel)
        .where(
            StudioInvitationModel.id == invitation_id,
            StudioInvitationModel.studio_id == studio_id,
        )
        .returning(StudioInvitationModel.id)
    )
    if result.scalar_one_or_none() is None:
        raise _invitation_not_found(invitation_id)
    await session.commit()


async def _find_invitation(session: AsyncSession, secret: str) -> StudioInvitationModel | None:
    result = await session.execute(
        select(StudioInvitationModel).where(StudioInvitationModel.token_hash == hash_token(secret))
    )
    return result.scalar_one_or_none()


async def preview_invitation(session: AsyncSession, secret: str) -> InvitationPreview:
    """Public, non-consuming view of an invitation: enough for the landing
    page to name the studio and role, and nothing else. Unknown secrets answer
    `unknown` with every field null."""
    invitation = await _find_invitation(session, secret)
    if invitation is None:
        return InvitationPreview(state="unknown")
    if invitation.consumed_at is not None:
        state: InvitationState = "used"
    elif invitation.expires_at <= datetime.now(UTC):
        state = "expired"
    else:
        state = "valid"
    studio_name = await session.scalar(
        select(StudioModel.name).where(StudioModel.id == invitation.studio_id)
    )
    inviter = (
        await session.get(UserModel, invitation.invited_by_user_id)
        if invitation.invited_by_user_id is not None
        else None
    )
    return InvitationPreview(
        state=state,
        studio_name=studio_name,
        role=invitation.role,
        inviter_display_name=inviter.display_name if inviter is not None else None,
    )


async def accept_invitation(
    session: AsyncSession, user: UserModel, secret: str
) -> StudioMembershipModel:
    """Consume the secret and join its studio with the invited role. Unknown,
    expired and already consumed secrets answer 410 with their own code; an
    invitation for another address answers 403 without being consumed."""
    invitation = await _find_invitation(session, secret)
    if invitation is None:
        raise invitation_gone("invitation_unknown")
    if invitation.consumed_at is not None:
        raise invitation_gone("invitation_used")
    if invitation.expires_at <= datetime.now(UTC):
        raise invitation_gone("invitation_expired")
    if normalize_email(invitation.email) != normalize_email(user.email):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "invitation_email_mismatch",
                "message": "this invitation was issued for another address",
            },
        )
    consumed = await _consume(session, invitation.id)
    if consumed is None:
        # Lost the race against a concurrent consumer: report why, never a 500.
        await session.rollback()
        current = await _find_invitation(session, secret)
        if current is not None and current.consumed_at is not None:
            raise invitation_gone("invitation_used")
        raise invitation_gone("invitation_expired")
    membership = await _join(session, user, consumed)
    await session.commit()
    return membership


async def list_members(
    session: AsyncSession, studio_id: uuid.UUID
) -> list[tuple[StudioMembershipModel, UserModel]]:
    result = await session.execute(
        select(StudioMembershipModel, UserModel)
        .join(UserModel, UserModel.id == StudioMembershipModel.user_id)
        .where(StudioMembershipModel.studio_id == studio_id)
        .order_by(StudioMembershipModel.created_at, StudioMembershipModel.user_id)
    )
    return [(membership, user) for membership, user in result.all()]


async def _membership(
    session: AsyncSession, studio_id: uuid.UUID, user_id: uuid.UUID
) -> StudioMembershipModel:
    membership = await session.get(StudioMembershipModel, (studio_id, user_id))
    if membership is None:
        raise _not_a_member(user_id)
    return membership


async def _owner_count(session: AsyncSession, studio_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(StudioMembershipModel)
            .where(
                StudioMembershipModel.studio_id == studio_id,
                StudioMembershipModel.role == StudioRole.OWNER.value,
            )
        )
        or 0
    )


async def _ensure_owner_target_allowed(
    session: AsyncSession, principal: Principal, membership: StudioMembershipModel
) -> None:
    """Changing an owner needs an owner, and never removes the last one."""
    if membership.role != StudioRole.OWNER.value:
        return
    if principal.studio_role is not StudioRole.OWNER:
        raise owner_required()
    if await _owner_count(session, principal.studio_id) <= 1:
        raise last_owner_required()


async def update_member_role(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID, role: str
) -> StudioMembershipModel:
    if not is_studio_manager(principal):
        raise forbidden("studio_member", "write")
    try:
        new_role = StudioRole(role)
    except ValueError:
        raise _invalid_role(role) from None
    if new_role is StudioRole.OWNER and principal.studio_role is not StudioRole.OWNER:
        raise owner_required()
    ensure_not_self(principal.user, user_id, "update_studio_role")
    membership = await _membership(session, principal.studio_id, user_id)
    await _ensure_owner_target_allowed(session, principal, membership)
    if membership.role != new_role.value:
        membership.role = new_role.value
        membership.granted_by_user_id = principal.user.id
        await session.commit()
        await session.refresh(membership)
    return membership


async def remove_member(session: AsyncSession, principal: Principal, user_id: uuid.UUID) -> None:
    if not is_studio_manager(principal):
        raise forbidden("studio_member", "write")
    ensure_not_self(principal.user, user_id, "remove_studio_member")
    membership = await _membership(session, principal.studio_id, user_id)
    await _ensure_owner_target_allowed(session, principal, membership)
    await session.delete(membership)
    await session.commit()


async def transfer_ownership(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID
) -> StudioMembershipModel:
    """Promote `user_id` to `owner` and demote the caller to `admin` in the
    same commit: the studio never has zero owners."""
    if principal.studio_role is not StudioRole.OWNER:
        raise owner_required()
    ensure_not_self(principal.user, user_id, "transfer_ownership")
    target = await _membership(session, principal.studio_id, user_id)
    if target.role != StudioRole.OWNER.value:
        target.role = StudioRole.OWNER.value
        target.granted_by_user_id = principal.user.id
        await session.flush()
    actor = await _membership(session, principal.studio_id, principal.user.id)
    if actor.role == StudioRole.OWNER.value:
        actor.role = StudioRole.ADMIN.value
        actor.granted_by_user_id = principal.user.id
    await session.commit()
    await session.refresh(target)
    return target
