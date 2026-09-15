"""Human dashboard authentication endpoint (DASH-4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.session import get_session
from studio_api.jwt_auth import create_access_token
from studio_api.services import provisioning as provisioning_service
from studio_api.settings import Settings, get_settings

router = APIRouter(tags=["auth"])


class TokenRequest(BaseModel):
    email: str = Field(..., examples=["admin@example.com"])
    password: str = Field(..., examples=["super-secret"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post(
    "/auth/token",
    response_model=TokenResponse,
    description="Exchange human credentials for a short-lived dashboard JWT.",
    responses={
        401: {"description": "Invalid email or password."},
    },
    include_in_schema=True,
)
async def login(
    request: TokenRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = await provisioning_service.verify_user_password(session, request.email, request.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    machine = await provisioning_service.get_or_create_dashboard_machine(session, user)
    access_token = create_access_token(user, machine, settings)
    return TokenResponse(access_token=access_token)
