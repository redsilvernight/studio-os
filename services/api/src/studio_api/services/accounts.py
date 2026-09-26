"""Public registration and account recovery (A4, DU-0/A / DEC-0109).

Every public entry point answers the same way whatever the address: whether
an e-mail goes out is decided here, the response never says. Secrets are
256-bit random values; only their SHA-256 is stored (`account_tokens`), and
the plaintext exists only in the e-mail handed back to the caller for
background delivery.

Registration only asks for an address: the password and display name are
chosen when the verification link is consumed, by whoever holds the mailbox.
A stranger who registers someone else's address therefore never knows the
password of the account the owner activates, and never writes text into an
e-mail sent to that owner.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.account_token import AccountTokenModel, AccountTokenPurpose
from studio_api.db.models.user import UserModel
from studio_api.mailer import OutgoingEmail
from studio_api.security import hash_token
from studio_api.security_log import email_digest, security_event
from studio_api.services import event_stream
from studio_api.services import provisioning as provisioning_service
from studio_api.settings import Settings

SELF_REGISTERED_ROLE = "readonly"
"""DEC-0109: a self-registered User can never hold a privileged role; access
to a project only ever comes from an admin-granted membership."""


@dataclass(frozen=True)
class IssuedToken:
    user: UserModel
    secret: str


def new_account_secret() -> str:
    return secrets.token_urlsafe(32)


def keyed_request_hash(body: bytes, settings: Settings) -> str:
    """Idempotency fingerprint of a body that may carry a password: keyed
    (with a key derived from, not equal to, the JWT secret), so the stored
    hash cannot be brute-forced offline into the password."""
    key = hashlib.sha256(
        b"studio-os/account-request-hash/v1:" + settings.jwt_secret.encode("utf-8")
    ).digest()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


async def _issue(
    session: AsyncSession,
    user: UserModel,
    purpose: str,
    ttl: timedelta,
    cooldown: timedelta,
) -> IssuedToken | None:
    """New secret for `user`, expiring the outstanding ones of the same
    purpose. None (silently) inside the cooldown after the previous one."""
    now = datetime.now(UTC)
    latest = await session.execute(
        select(AccountTokenModel.created_at)
        .where(AccountTokenModel.user_id == user.id, AccountTokenModel.purpose == purpose)
        .order_by(AccountTokenModel.created_at.desc())
        .limit(1)
    )
    last_created = latest.scalar_one_or_none()
    if last_created is not None and now - last_created < cooldown:
        return None
    await _expire_outstanding(session, user.id, purpose)
    secret = new_account_secret()
    session.add(
        AccountTokenModel(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(secret),
            created_at=now,
            expires_at=now + ttl,
        )
    )
    return IssuedToken(user=user, secret=secret)


async def _expire_outstanding(session: AsyncSession, user_id: uuid.UUID, purpose: str) -> None:
    now = datetime.now(UTC)
    await session.execute(
        update(AccountTokenModel)
        .where(
            AccountTokenModel.user_id == user_id,
            AccountTokenModel.purpose == purpose,
            AccountTokenModel.consumed_at.is_(None),
            AccountTokenModel.expires_at > now,
        )
        .values(expires_at=now)
    )


async def _consume(session: AsyncSession, secret: str, purpose: str) -> AccountTokenModel | None:
    """Single conditional UPDATE: of two concurrent consumers of one secret,
    exactly one gets the row back."""
    now = datetime.now(UTC)
    result = await session.execute(
        update(AccountTokenModel)
        .where(
            AccountTokenModel.token_hash == hash_token(secret),
            AccountTokenModel.purpose == purpose,
            AccountTokenModel.consumed_at.is_(None),
            AccountTokenModel.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(AccountTokenModel)
    )
    return result.scalar_one_or_none()


def _invalid_token() -> HTTPException:
    return HTTPException(
        status.HTTP_400_BAD_REQUEST,
        detail={
            "error_code": "invalid_or_expired_token",
            "message": "this link is invalid, expired or already used",
        },
    )


def _cooldown(settings: Settings) -> timedelta:
    return timedelta(seconds=settings.account_email_cooldown_seconds)


def verification_email(settings: Settings, issued: IssuedToken) -> OutgoingEmail:
    link = f"{settings.public_base_url.rstrip('/')}/verify-email#token={issued.secret}"
    hours = settings.email_verification_ttl_minutes // 60
    return OutgoingEmail(
        to=issued.user.email,
        subject="Studio OS — confirmez votre adresse e-mail",
        body=(
            "Bonjour,\n\n"
            "Une inscription à Studio OS a été demandée pour cette adresse. Pour "
            "activer le compte et choisir votre mot de passe, ouvrez ce lien :\n\n"
            f"{link}\n\n"
            f"Il expire dans {hours} h et ne fonctionne qu'une fois. Si vous n'avez "
            "rien demandé, ignorez ce message : aucun compte ne sera activé.\n"
        ),
        kind="email_verification",
    )


def password_reset_email(settings: Settings, issued: IssuedToken) -> OutgoingEmail:
    link = f"{settings.public_base_url.rstrip('/')}/reset-password#token={issued.secret}"
    return OutgoingEmail(
        to=issued.user.email,
        subject="Studio OS — réinitialisation du mot de passe",
        body=(
            "Bonjour,\n\n"
            "Pour choisir un nouveau mot de passe Studio OS, ouvrez ce lien :\n\n"
            f"{link}\n\n"
            f"Il expire dans {settings.password_reset_ttl_minutes} min et ne fonctionne "
            "qu'une fois. Toutes vos sessions seront fermées. Si vous n'avez rien "
            "demandé, ignorez ce message : votre mot de passe reste inchangé.\n"
        ),
        kind="password_reset",
    )


async def _send_verification(
    session: AsyncSession, settings: Settings, user: UserModel
) -> list[OutgoingEmail]:
    issued = await _issue(
        session,
        user,
        AccountTokenPurpose.EMAIL_VERIFICATION,
        timedelta(minutes=settings.email_verification_ttl_minutes),
        _cooldown(settings),
    )
    await session.commit()
    return [verification_email(settings, issued)] if issued is not None else []


async def register(session: AsyncSession, settings: Settings, email: str) -> list[OutgoingEmail]:
    """Creates a `pending` readonly User without membership nor password, or
    re-sends the verification of a still-pending one. An active or disabled
    address gets nothing."""
    normalized = provisioning_service.normalize_email(email)
    user = await provisioning_service.get_user_by_email(session, normalized)
    if user is None:
        user = UserModel(
            display_name=normalized.split("@", 1)[0],
            email=normalized,
            role=SELF_REGISTERED_ROLE,
            email_verified_at=None,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            return []
    elif user.status != "pending":
        security_event("account.register", outcome="ignored", email_digest=email_digest(normalized))
        return []
    messages = await _send_verification(session, settings, user)
    security_event("account.register", outcome="success", email_digest=email_digest(normalized))
    return messages


async def resend_verification(
    session: AsyncSession, settings: Settings, email: str
) -> list[OutgoingEmail]:
    user = await provisioning_service.get_user_by_email(session, email)
    if user is None or user.status != "pending":
        return []
    return await _send_verification(session, settings, user)


async def verify_email(
    session: AsyncSession, secret: str, password: str, display_name: str
) -> dict[str, str]:
    """Consumes the secret and activates the still-pending account with the
    password and display name chosen now. Every other verification link of
    the account stops working."""
    password_hash = provisioning_service.hash_password(password)
    token = await _consume(session, secret, AccountTokenPurpose.EMAIL_VERIFICATION)
    user = await session.get(UserModel, token.user_id) if token is not None else None
    if user is None or user.status != "pending":
        await session.rollback()
        security_event("account.email_verified", outcome="failure")
        raise _invalid_token()
    user.email_verified_at = datetime.now(UTC)
    user.password_hash = password_hash
    user.display_name = display_name
    user.version += 1
    await _expire_outstanding(session, user.id, AccountTokenPurpose.EMAIL_VERIFICATION)
    await session.commit()
    security_event("account.email_verified", outcome="success", user_id=user.id)
    return {"status": "verified"}


async def forgot_password(
    session: AsyncSession, settings: Settings, email: str
) -> list[OutgoingEmail]:
    user = await provisioning_service.get_user_by_email(session, email)
    if user is None or user.status == "disabled":
        security_event(
            "credential.password_reset_requested",
            outcome="ignored",
            email_digest=email_digest(email),
        )
        return []
    issued = await _issue(
        session,
        user,
        AccountTokenPurpose.PASSWORD_RESET,
        timedelta(minutes=settings.password_reset_ttl_minutes),
        _cooldown(settings),
    )
    await session.commit()
    security_event("credential.password_reset_requested", outcome="success", user_id=user.id)
    return [password_reset_email(settings, issued)] if issued is not None else []


async def reset_password(session: AsyncSession, secret: str, new_password: str) -> dict[str, str]:
    """Consumes the secret, sets the password and revokes every session (A2).
    Owning the mailbox also proves the address: a pending User becomes
    verified. A User disabled meanwhile stays disabled."""
    password_hash = provisioning_service.hash_password(new_password)
    token = await _consume(session, secret, AccountTokenPurpose.PASSWORD_RESET)
    if token is None:
        await session.rollback()
        security_event("credential.password_reset", outcome="failure")
        raise _invalid_token()
    user = await session.get(UserModel, token.user_id)
    assert user is not None
    _apply_new_password(user, password_hash)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
        await _expire_outstanding(session, user.id, AccountTokenPurpose.EMAIL_VERIFICATION)
    await _expire_outstanding(session, user.id, AccountTokenPurpose.PASSWORD_RESET)
    await session.commit()
    event_stream.revalidate_user(user.id)
    security_event("credential.password_reset", outcome="success", user_id=user.id)
    return {"status": "password_reset"}


async def change_password(
    session: AsyncSession, user_id: uuid.UUID, current_password: str, new_password: str
) -> dict[str, str]:
    user = await session.get(UserModel, user_id)
    if (
        user is None
        or user.password_hash is None
        or not provisioning_service.check_password(current_password, user.password_hash)
    ):
        security_event("credential.password_changed", outcome="failure", user_id=user_id)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "invalid_current_password",
                "message": "the current password is incorrect",
            },
        )
    _apply_new_password(user, provisioning_service.hash_password(new_password))
    await session.commit()
    event_stream.revalidate_user(user.id)
    security_event("credential.password_changed", outcome="success", user_id=user.id)
    return {"status": "password_changed"}


def _apply_new_password(user: UserModel, password_hash: str) -> None:
    user.password_hash = password_hash
    provisioning_service.revoke_sessions_in_place(user)
