"""Operator console settings: the operator list lives in server configuration.

There is no operator table and no console migration: an operator is allowed
in only when they are listed here *and* carry a TOTP secret. A listed
operator without `totp_secret` is refused (MFA is mandatory, fiche C0).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

GIB = 1024**3

DEFAULT_JWT_SECRETS = frozenset(
    {"change-me-in-production", "change-me-to-a-long-random-string-min-32-bytes"}
)
MIN_JWT_SECRET_BYTES = 32


class OperatorAccount(BaseModel):
    """One operator allowed into the console, from server configuration."""

    email: str
    display_name: str
    # Base32 RFC 4648 secret. Absent/empty: the operator is listed but MFA is
    # not configured, so the console refuses them instead of degrading to a
    # password-only login.
    totp_secret: str | None = None

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("operator email must look like an address")
        return email

    @property
    def has_mfa(self) -> bool:
        return bool(self.totp_secret and self.totp_secret.strip())


class PlanQuota(BaseModel):
    """Illustrative per-plan limits (M-seuils, DEC-0387); configuration-driven
    so the definitive values land without a code change."""

    storage_bytes: int = Field(ge=0)
    members: int = Field(ge=0)


def _default_plan_quotas() -> dict[str, PlanQuota]:
    return {
        "free": PlanQuota(storage_bytes=2 * GIB, members=5),
        "pro": PlanQuota(storage_bytes=100 * GIB, members=25),
    }


class OperatorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STUDIO_OPERATOR_", env_file=".env", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://studio:studio@localhost:5432/studio"
    environment: Literal["production", "dev", "test"] = "production"

    # Own token: never the core API's `STUDIO_JWT_SECRET`, so a console token
    # cannot be replayed against the client API and vice versa.
    jwt_secret: str = "change-me-in-production"
    token_ttl_minutes: int = Field(default=15, ge=1, le=15)

    operators: list[OperatorAccount] = Field(default_factory=list)

    mfa_max_attempts: int = Field(default=3, ge=1, le=10)
    mfa_lockout_minutes: int = Field(default=15, ge=1, le=1440)

    # Platform capacity and alert thresholds (illustrations, DEC-0387).
    storage_capacity_bytes: int = Field(default=570 * GIB, ge=0)
    storage_alert_percent: int = Field(default=70, ge=1, le=100)
    usage_alert_percent: int = Field(default=90, ge=1, le=100)
    plan_quotas: dict[str, PlanQuota] = Field(default_factory=_default_plan_quotas)

    def operator(self, email: str) -> OperatorAccount | None:
        wanted = email.strip().lower()
        for account in self.operators:
            if account.email == wanted:
                return account
        return None

    def quota_for(self, plan: str) -> PlanQuota | None:
        return self.plan_quotas.get(plan)


def is_weak_jwt_secret(secret: str) -> bool:
    return secret in DEFAULT_JWT_SECRETS or len(secret.encode()) < MIN_JWT_SECRET_BYTES


@lru_cache
def get_settings() -> OperatorSettings:
    return OperatorSettings()
