from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
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

    # Plans and limits (DEC-0401/DEC-0402): the single subscription screen every
    # `plan_limit_reached` response points at. Relative path = dashboard route.
    billing_upgrade_url: str = "/settings/subscription"

    # Execution snapshots (DEC-0199): kept this long after capture, then purged.
    execution_snapshot_retention_days: int = Field(default=90, ge=1, le=3650)

    # Cross-process realtime fan-out (DEC-0156): the API listens for events
    # committed by other processes (mcp, workers) and relays them over SSE.
    realtime_listener_enabled: bool = True

    # Infrastructure cost measurements (phase M): sizes and counts only, never
    # content. 0 disables the collector; retention bounds the table.
    infra_measure_interval_seconds: int = Field(default=900, ge=0, le=86400)
    infra_measure_retention_days: int = Field(default=180, ge=90, le=3650)
    # Directory holding the database backups, when the host has one (optional).
    infra_backup_dir: str | None = None

    # Hourly HTTP counters (operator console C1/C3): request count, 5xx and
    # latency percentiles, persisted through `infra_measurements`. Numbers
    # only, never a path or a body. 0 disables persistence.
    http_measure_enabled: bool = True
    http_measure_flush_seconds: int = Field(default=300, ge=0, le=86400)

    heartbeat_interval_seconds: int = 30
    heartbeat_offline_after_seconds: int = 90

    # Launch expiry (DEC-0173 base). An overdue non-terminal launch whose
    # linked work session is still open with activity newer than this window
    # is prolonged by this window instead of being expired; past it, the
    # server expires the launch and closes the session + releases claims.
    launch_activity_grace_seconds: int = Field(default=900, ge=60, le=86400)

    # Session presence (C1, DEC-0157): derived at read from last_activity_at,
    # never stored, never a heartbeat. A session with no activity past the
    # idle threshold reads `idle`; past the expire threshold it reads
    # `expired` (effective closing is L2, l2-resume).
    session_idle_after_seconds: int = 1800
    session_expire_after_seconds: int = 28800

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

    # C1 version negotiation: oldest served and newest known client build
    # per family. Raised by ops without a redeploy; clients below the
    # minimum get 426 client_upgrade_required, clients without headers
    # (pre-C1) keep working untouched.
    api_version: str = "1"
    desktop_minimum_version: str = "0.1.0"
    daemon_minimum_version: str = "0.1.0"
    dashboard_minimum_version: str = "0.1.0"
    desktop_latest_version: str = "0.1.0"
    daemon_latest_version: str = "0.1.0"
    dashboard_latest_version: str = "0.1.0"

    # Human dashboard JWT (DASH-4, DEC-0110: 15 min at most, out of range refuses to start)
    jwt_secret: str = "change-me-in-production"
    jwt_access_token_expire_minutes: int = Field(default=15, ge=1, le=15)
    # Desktop refresh token (DEC-0142): sliding idle window, capped by an
    # absolute lifetime after which the password is asked again.
    refresh_token_sliding_days: int = Field(default=30, ge=1, le=90)
    refresh_token_absolute_days: int = Field(default=90, ge=1, le=90)

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

    # Anti-abuse on public self-registration (S5). Sliding-window quotas, in
    # memory per process: at most `registration_ip_limit` registrations from
    # one client IP and `registration_domain_limit` for one e-mail domain
    # within `registration_limit_window_seconds`. 0 disables a scope.
    # A multi-replica deployment needs a shared store (DEC-0106).
    registration_ip_limit: int = Field(default=10, ge=0, le=100_000)
    registration_domain_limit: int = Field(default=50, ge=0, le=100_000)
    registration_limit_window_seconds: int = Field(default=3600, ge=60, le=86_400)
    # Comma-separated, lower-case domains; subdomains are covered. Replaces
    # the built-in list entirely, so an operator can extend or shorten it.
    registration_disposable_email_domains: str = (
        "10minutemail.com,guerrillamail.com,mailinator.com,sharklasers.com,"
        "tempmail.com,throwawaymail.com,trashmail.com,yopmail.com"
    )
    # Bot-protection hook. No provider is wired in this build: leaving it off
    # accepts every request, turning it on fails closed (503) until an
    # implementation is registered in `registration_guard`.
    registration_bot_protection_enabled: bool = False

    @field_validator("registration_disposable_email_domains")
    @classmethod
    def _normalize_disposable_domains(cls, value: str) -> str:
        domains: list[str] = []
        for raw in value.split(","):
            domain = raw.strip().lower()
            if not domain:
                continue
            if "@" in domain or "/" in domain or " " in domain or "." not in domain:
                raise ValueError(f"invalid disposable e-mail domain: {raw.strip()!r}")
            if domain not in domains:
                domains.append(domain)
        return ",".join(domains)

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
