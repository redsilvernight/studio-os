"""Public registration and account recovery (A4, DU-0/A / DEC-0109)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import AfterValidator, BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.session import get_session
from studio_api.deps import CurrentPrincipal
from studio_api.mailer import EmailSender, OutgoingEmail, deliver, get_email_sender
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, ErrorResponses
from studio_api.security import hash_token
from studio_api.services import accounts as accounts_service
from studio_api.services import idempotency as idempotency_service
from studio_api.settings import Settings, get_settings

router = APIRouter(tags=["auth"])

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_BYTES = 72

REQUIRED_IDEMPOTENCY_KEY_DESCRIPTION = (
    "Required. Caller-generated unique value per intended request: replaying "
    "the same key with the identical body returns the original response "
    "without sending a second e-mail; a different body is "
    "`409 idempotency_key_payload_mismatch`."
)


def _password(value: str) -> str:
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError(f"password must be at most {PASSWORD_MAX_BYTES} bytes")
    return value


NewPassword = Annotated[
    str,
    AfterValidator(_password),
    Field(description=f"{PASSWORD_MIN_LENGTH} characters to {PASSWORD_MAX_BYTES} UTF-8 bytes."),
]


class EmailField(BaseModel):
    email: str = Field(
        ...,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+$",
        examples=["ada@example.com"],
    )


class TokenBody(BaseModel):
    token: str = Field(..., min_length=16, max_length=256)


class VerifyEmailRequest(TokenBody):
    password: NewPassword
    display_name: str = Field(..., min_length=1, max_length=100)

    @field_validator("display_name")
    @classmethod
    def _strip_display_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("display_name must not be blank")
        return stripped


class ResetPasswordRequest(TokenBody):
    new_password: NewPassword


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., max_length=PASSWORD_MAX_BYTES * 4)
    new_password: NewPassword


class AcceptedResponse(BaseModel):
    status: str = Field(
        "accepted",
        description="Always `accepted`, whether or not an e-mail was sent.",
    )


class AccountActionResponse(BaseModel):
    status: str = Field(..., examples=["verified", "password_reset", "password_changed"])


def _unavailable(error_code: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail={"error_code": error_code})


def _require_registration(settings: Settings) -> None:
    if not settings.public_registration_enabled:
        raise _unavailable("registration_unavailable")


def _require_recovery(sender: EmailSender) -> None:
    if not sender.enabled:
        raise _unavailable("password_recovery_unavailable")


def _require_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail={"error_code": "idempotency_key_required"}
        )
    return idempotency_key


async def _accepted(
    session: AsyncSession,
    request: Request,
    settings: Settings,
    idempotency_key: str,
    endpoint: str,
    background: BackgroundTasks,
    sender: EmailSender,
    produce: Callable[[], Awaitable[list[OutgoingEmail]]],
) -> AcceptedResponse:
    """Runs `produce` once per key; its e-mails go out after the response, so
    neither the body nor the latency depends on the address."""

    async def _create() -> dict[str, Any]:
        for message in await produce():
            background.add_task(deliver, sender, message)
        return AcceptedResponse(status="accepted").model_dump(mode="json")

    body = await idempotency_service.run_idempotent_dict(
        session,
        idempotency_key,
        endpoint,
        accounts_service.keyed_request_hash(await request.body(), settings),
        _create,
        status.HTTP_202_ACCEPTED,
    )
    return AcceptedResponse.model_validate(body)


async def _terminal(
    session: AsyncSession,
    request: Request,
    settings: Settings,
    token: str,
    endpoint: str,
    consume: Callable[[], Awaitable[dict[str, str]]],
) -> AccountActionResponse:
    """Single-use secrets: the secret's hash is the idempotency key, so an
    identical replay returns the original terminal result without a second
    consumption, and a different body for the same secret is a 409."""
    body = await idempotency_service.run_idempotent_dict(
        session,
        hash_token(token),
        endpoint,
        accounts_service.keyed_request_hash(await request.body(), settings),
        consume,
    )
    return AccountActionResponse.model_validate(body)


_UNAVAILABLE_REGISTRATION: ErrorResponses = {
    404: {"description": "`registration_unavailable`: public registration is closed."}
}
_UNAVAILABLE_RECOVERY: ErrorResponses = {
    404: {"description": "`password_recovery_unavailable`: no e-mail backend configured."}
}
_KEY_ERRORS: ErrorResponses = {
    400: {"description": "`idempotency_key_required`."},
    409: {"description": "`idempotency_key_payload_mismatch` / `idempotency_key_in_progress`."},
}
_TOKEN_ERRORS: ErrorResponses = {
    400: {"description": "`invalid_or_expired_token`: unknown, expired or already used."},
    409: {"description": "`idempotency_key_payload_mismatch`: same secret, different body."},
}


@router.post(
    "/auth/register",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    description=(
        "Public self-registration, only when the instance enables it. Body: the "
        "address only. Creates a `pending` `readonly` User without password nor "
        "project membership and e-mails a single-use verification link; the "
        "password and display name are chosen when that link is consumed. The "
        "answer is identical whether or not the address already has an account."
    ),
    responses={**_UNAVAILABLE_REGISTRATION, **_KEY_ERRORS},
)
async def register(
    payload: EmailField,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=REQUIRED_IDEMPOTENCY_KEY_DESCRIPTION
    ),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    sender: EmailSender = Depends(get_email_sender),
) -> AcceptedResponse:
    _require_registration(settings)
    key = _require_key(idempotency_key)
    return await _accepted(
        session,
        request,
        settings,
        key,
        "POST /auth/register",
        background,
        sender,
        lambda: accounts_service.register(session, settings, payload.email),
    )


@router.post(
    "/auth/resend-verification",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    description=(
        "Send a new verification link to a still-pending account (earlier links "
        "stop working). Same answer for any address."
    ),
    responses={**_UNAVAILABLE_REGISTRATION, **_KEY_ERRORS},
)
async def resend_verification(
    payload: EmailField,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=REQUIRED_IDEMPOTENCY_KEY_DESCRIPTION
    ),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    sender: EmailSender = Depends(get_email_sender),
) -> AcceptedResponse:
    _require_registration(settings)
    key = _require_key(idempotency_key)
    return await _accepted(
        session,
        request,
        settings,
        key,
        "POST /auth/resend-verification",
        background,
        sender,
        lambda: accounts_service.resend_verification(session, settings, payload.email),
    )


@router.post(
    "/auth/verify-email",
    response_model=AccountActionResponse,
    description=(
        "Consume a verification secret and activate the pending account with the "
        "password and display name given here; every other verification link of "
        "the account stops working. Replaying the same body returns the same "
        "result."
    ),
    responses={**_UNAVAILABLE_REGISTRATION, **_TOKEN_ERRORS},
)
async def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AccountActionResponse:
    _require_registration(settings)
    return await _terminal(
        session,
        request,
        settings,
        payload.token,
        "POST /auth/verify-email",
        lambda: accounts_service.verify_email(
            session, payload.token, payload.password, payload.display_name
        ),
    )


@router.post(
    "/auth/forgot-password",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    description=(
        "E-mail a single-use password reset link. Same answer for any address; "
        "a disabled account gets nothing."
    ),
    responses={**_UNAVAILABLE_RECOVERY, **_KEY_ERRORS},
)
async def forgot_password(
    payload: EmailField,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=REQUIRED_IDEMPOTENCY_KEY_DESCRIPTION
    ),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    sender: EmailSender = Depends(get_email_sender),
) -> AcceptedResponse:
    _require_recovery(sender)
    key = _require_key(idempotency_key)
    return await _accepted(
        session,
        request,
        settings,
        key,
        "POST /auth/forgot-password",
        background,
        sender,
        lambda: accounts_service.forgot_password(session, settings, payload.email),
    )


@router.post(
    "/auth/reset-password",
    response_model=AccountActionResponse,
    description=(
        "Consume a reset secret and set a new password; every session and JWT "
        "of the account is revoked. Replaying the same body returns the same "
        "result."
    ),
    responses={**_UNAVAILABLE_RECOVERY, **_TOKEN_ERRORS},
)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    sender: EmailSender = Depends(get_email_sender),
) -> AccountActionResponse:
    _require_recovery(sender)
    return await _terminal(
        session,
        request,
        settings,
        payload.token,
        "POST /auth/reset-password",
        lambda: accounts_service.reset_password(session, payload.token, payload.new_password),
    )


@router.post(
    "/auth/change-password",
    response_model=AccountActionResponse,
    description=(
        "Change the caller's password (current password required). Every "
        "session and JWT of the account is revoked, including the caller's: "
        "log in again."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        400: {"description": "`invalid_current_password`."},
    },
)
async def change_password(
    payload: ChangePasswordRequest,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_session),
) -> AccountActionResponse:
    body = await accounts_service.change_password(
        session, principal.user.id, payload.current_password, payload.new_password
    )
    return AccountActionResponse.model_validate(body)
