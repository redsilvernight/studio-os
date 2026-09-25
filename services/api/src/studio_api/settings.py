from __future__ import annotations

from typing import Literal

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

    # Human dashboard JWT (DASH-4)
    jwt_secret: str = "change-me-in-production"
    jwt_access_token_expire_minutes: int = 480

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
