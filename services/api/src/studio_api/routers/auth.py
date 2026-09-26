"""Human dashboard authentication endpoints (DASH-4, DEC-0110)."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.session import get_session
from studio_api.deps import CurrentPrincipal
from studio_api.jwt_auth import access_token_lifetime_seconds, create_access_token
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED
from studio_api.security_log import email_digest, security_event
from studio_api.services import provisioning as provisioning_service
from studio_api.settings import Settings, get_settings

router = APIRouter(tags=["auth"])


class TokenRequest(BaseModel):
    email: str = Field(..., examples=["admin@example.com"])
    password: str = Field(..., examples=["super-secret"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Lifetime of `access_token` in seconds.")


class AuthIdentity(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    role: str
    machine_id: uuid.UUID


@router.post(
    "/auth/token",
    response_model=TokenResponse,
    description=(
        "Exchange human credentials for a short-lived dashboard JWT (15 minutes "
        "at most, no refresh token). A disabled or unverified account gets the "
        "same 401 as a wrong password."
    ),
    responses={
        401: {"description": "Invalid email or password."},
    },
    include_in_schema=True,
)
async def login(
    request: TokenRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = await provisioning_service.verify_user_password(session, request.email, request.password)
    if user is None:
        security_event(
            "auth.login",
            outcome="failure",
            request=http_request,
            level=logging.WARNING,
            email_digest=email_digest(request.email),
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    machine = await provisioning_service.get_or_create_dashboard_machine(session, user)
    security_event(
        "auth.login",
        outcome="success",
        request=http_request,
        user_id=user.id,
        machine_id=machine.id,
    )
    access_token = create_access_token(user, machine, settings)
    return TokenResponse(
        access_token=access_token, expires_in=access_token_lifetime_seconds(settings)
    )


@router.get(
    "/auth/me",
    response_model=AuthIdentity,
    description=(
        "Identity of the authenticated principal (JWT or machine token): the "
        "client's source for email and role, which the JWT no longer carries. "
        "Never subject to project access control."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def get_identity(principal: CurrentPrincipal) -> AuthIdentity:
    return AuthIdentity(
        user_id=principal.user.id,
        display_name=principal.user.display_name,
        email=principal.user.email,
        role=principal.role.value,
        machine_id=principal.machine.id,
    )
