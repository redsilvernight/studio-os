from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from studio_operator.auth import (
    AttemptTracker,
    authenticate,
    get_attempt_tracker,
    require_operator,
)
from studio_operator.schemas import MfaRequest, OperatorProfile, OperatorSession
from studio_operator.settings import OperatorAccount, OperatorSettings, get_settings

router = APIRouter(prefix="/auth", tags=["session"])


@router.post(
    "/mfa",
    response_model=OperatorSession,
    description=(
        "Operator login (fiche C0): the account must be listed in server "
        "configuration *and* have a TOTP secret, otherwise `403 "
        "operator_not_allowed` (the two cases are deliberately indistinguishable). "
        "A wrong code answers `401 mfa_invalid` with the attempts left; the "
        "next one locks the account for the configured delay (`429 mfa_locked`). "
        "The returned token is signed with the console's own secret and is "
        "not accepted by the client API."
    ),
)
async def login(
    payload: MfaRequest,
    response: Response,
    settings: Annotated[OperatorSettings, Depends(get_settings)],
    tracker: Annotated[AttemptTracker, Depends(get_attempt_tracker)],
) -> OperatorSession:
    account, token, expires_in = authenticate(settings, tracker, payload.email, payload.code)
    response.headers["Cache-Control"] = "no-store"
    return OperatorSession(
        access_token=token,
        expires_in=expires_in,
        operator=OperatorProfile(email=account.email, display_name=account.display_name),
    )


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
