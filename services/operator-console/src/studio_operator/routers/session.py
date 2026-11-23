from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from studio_operator.auth import (
    AttemptTracker,
    authenticate,
    confirm_enrollment,
    get_attempt_tracker,
    require_operator,
    start_enrollment,
)
from studio_operator.qr import qr_svg
from studio_operator.schemas import (
    EnrollmentConfirm,
    EnrollmentRequest,
    EnrollmentStart,
    LoginRequest,
    OperatorProfile,
    OperatorSession,
)
from studio_operator.secrets_store import SecretStore, get_secret_store
from studio_operator.settings import OperatorAccount, OperatorSettings, get_settings

router = APIRouter(prefix="/auth", tags=["session"])


@router.post(
    "/mfa",
    response_model=OperatorSession,
    description=(
        "Operator login (fiche C0): email + password + a 6-digit TOTP code. An "
        "unknown account, a wrong password and a missing MFA share one generic "
        "`403 operator_not_allowed` and one failure counter. A valid password with "
        "a wrong code answers `401 mfa_invalid` with the attempts left; the next "
        "one locks the account for the configured delay (`429 mfa_locked`). "
        "Passwords are bcrypt hashes from server configuration, compared in "
        "constant time. The returned token is signed with the console's own "
        "secret and is not accepted by the client API."
    ),
)
async def login(
    payload: LoginRequest,
    response: Response,
    settings: Annotated[OperatorSettings, Depends(get_settings)],
    tracker: Annotated[AttemptTracker, Depends(get_attempt_tracker)],
    store: Annotated[SecretStore, Depends(get_secret_store)],
) -> OperatorSession:
    account, token, expires_in = authenticate(
        settings, tracker, store, payload.email, payload.password, payload.code
    )
    response.headers["Cache-Control"] = "no-store"
    return OperatorSession(
        access_token=token,
        expires_in=expires_in,
        operator=OperatorProfile(email=account.email, display_name=account.display_name),
    )


@router.post(
    "/enrollment",
    response_model=EnrollmentStart,
    description=(
        "Fiche C0, first connection: a listed operator without an activated TOTP "
        "secret, proving the account password, receives the `otpauth://` URI, the "
        "Base32 secret and the same URI rendered as an SVG QR code. The secret "
        "stays pending for `expires_in` seconds and is activated only by a first "
        "valid 6-digit code (`POST /auth/enrollment/confirm`)."
    ),
)
async def enrollment(
    payload: EnrollmentRequest,
    response: Response,
    settings: Annotated[OperatorSettings, Depends(get_settings)],
    tracker: Annotated[AttemptTracker, Depends(get_attempt_tracker)],
    store: Annotated[SecretStore, Depends(get_secret_store)],
) -> EnrollmentStart:
    _account, secret, uri, ttl = start_enrollment(
        settings, tracker, store, payload.email, payload.password
    )
    response.headers["Cache-Control"] = "no-store"
    return EnrollmentStart(
        otpauth_uri=uri,
        secret=secret,
        qr_svg=qr_svg(uri),
        expires_in=ttl,
    )


@router.post(
    "/enrollment/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Confirm the pending enrollment with a first code: the secret becomes "
        "active and is stored outside configuration (state file). Wrong codes "
        "count against the same lockout as login."
    ),
)
async def enrollment_confirm(
    payload: EnrollmentConfirm,
    settings: Annotated[OperatorSettings, Depends(get_settings)],
    tracker: Annotated[AttemptTracker, Depends(get_attempt_tracker)],
    store: Annotated[SecretStore, Depends(get_secret_store)],
) -> Response:
    confirm_enrollment(settings, tracker, store, payload.email, payload.code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=OperatorProfile,
    description="Identity behind the console token, reloaded from server configuration.",
)
async def me(
    account: Annotated[OperatorAccount, Depends(require_operator)],
) -> OperatorProfile:
    return OperatorProfile(email=account.email, display_name=account.display_name)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Stateless logout: the console keeps no server-side session, the client "
        "drops its token. Present so the UI has a single place to call."
    ),
)
async def logout(
    _account: Annotated[OperatorAccount, Depends(require_operator)],
) -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)
