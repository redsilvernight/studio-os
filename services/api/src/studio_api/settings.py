from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STUDIO_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://studio:studio@localhost:5432/studio"

    s3_endpoint_url: str = "http://localhost:9000"
    # Endpoint baked into presigned URLs — must be reachable from client machines,
    # not the in-cluster service name. See docs/DECISIONS.md DEC-0004.
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "studio-transfers"
    s3_access_key: str = "studio"
    s3_secret_key: str = "studio-dev-secret"
    s3_region: str = "us-east-1"
    presigned_url_ttl_seconds: int = 900

    transfer_max_size_bytes: int = 20 * 1024**3
    transfer_project_quota_bytes: int = 100 * 1024**3
    multipart_abandon_after_days: int = 7

    heartbeat_interval_seconds: int = 30
    heartbeat_offline_after_seconds: int = 90

    # CORS / middleware
    cors_origins: str = ""
    request_id_header: str = "x-request-id"
    rate_limit_requests_per_minute: int = 120
    rate_limit_burst: int = 20
    # /api/v1/auth/* (login): stricter, always per client IP.
    auth_rate_limit_requests_per_minute: int = 10
    auth_rate_limit_burst: int = 5
    # Comma-separated IPs/CIDRs of reverse proxies (Caddy) whose
    # X-Forwarded-For is honored. Empty: the header is ignored.
    trusted_proxies: str = ""

    # Logging
    log_format: str = "text"  # "text" or "json"
    log_level: str = "INFO"

    # Deployment environment. Fail-closed: anything but an explicit "dev" or
    # "test" is production, where a weak JWT secret refuses to start.
    environment: Literal["production", "dev", "test"] = "production"

    # Human dashboard JWT (DASH-4, DEC-0110: 15 min at most, out of range refuses to start)
    jwt_secret: str = "change-me-in-production"
    jwt_access_token_expire_minutes: int = Field(default=15, ge=1, le=15)

    # Public registration (A4, DEC-0109): closed by default. OFF on every
    # exposed instance until the C4 gate; enabling it in production also
    # requires the SMTP e-mail backend (checked at startup).
    public_registration_enabled: bool = False
    # Base URL of the dashboard, used to build the links sent by e-mail
    # (`<base>/verify-email#token=…`, `<base>/reset-password#token=…`).
    public_base_url: str = "http://localhost:5173"
    email_verification_ttl_minutes: int = Field(default=24 * 60, ge=5, le=7 * 24 * 60)
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=24 * 60)
    # Minimum delay between two e-mails of the same kind to one User
    # (resend / forgot flooding); extra requests get the same 202, silently.
    account_email_cooldown_seconds: int = Field(default=60, ge=0)

    # Outgoing e-mail (A4). "disabled": nothing is sent and password recovery
    # is unavailable; "file": each message is written as .eml under
    # `email_file_dir` (local dev, never production); "smtp": real delivery.
    # Secrets are env-only, never logged, never returned by the API.
    email_backend: Literal["disabled", "file", "smtp"] = "disabled"
    email_from: str | None = None
    email_file_dir: str = ".studio-mail"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    # "starttls" (port 587), "tls" (implicit, port 465) or "none" (local relay only).
    smtp_security: Literal["starttls", "tls", "none"] = "starttls"
    smtp_timeout_seconds: float = 10.0

    # GitHub integration, Studio Producer (etape 9.1, DEC-0059) — secrets are
    # env-only, never logged, never returned by the API.
    github_webhook_secret: str | None = None
    github_token: str | None = None
    github_webhook_max_body_bytes: int = 1_048_576
    github_webhook_rate_limit_per_minute: int = 600
    github_webhook_rate_limit_burst: int = 60
    github_reconcile_runs_limit: int = 30


def get_settings() -> Settings:
    return Settings()
