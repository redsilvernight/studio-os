from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from pydantic import field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

_CONFIG_FILE_ENV_VAR = "STUDIO_CLIENT_CONFIG_FILE"


def default_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "StudioOS" / "config.toml"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "studio-os" / "config.toml"


class ClientConfig(BaseSettings):
    """Bloc B client configuration (DEC-0024). Precedence: explicit
    constructor arguments > `STUDIO_CLIENT_*` environment variables > an
    optional TOML file > field defaults. Deliberately never reads the
    repo's `.env` (that file configures Bloc A: Postgres, MinIO)."""

    model_config = SettingsConfigDict(env_prefix="STUDIO_CLIENT_", extra="ignore")

    api_base_url: str
    machine_id: UUID | None = None
    connect_timeout: float = 10.0
    # >= idempotency.py's _PENDING_RECLAIM_SECONDS (30s) so a client never
    # times out while a legitimate idempotent creation is still in flight.
    read_timeout: float = 35.0
    # Kept low deliberately: a single retryable attempt can itself block up
    # to _POLL_TIMEOUT_SECONDS (5s) server-side (idempotency.py). At 5
    # attempts the worst case (5x5s poll + backoff) creeps close enough to
    # _PENDING_RECLAIM_SECONDS (30s) to risk colliding with the server's own
    # abandoned-reservation reclaim (DEC-0015) — 3 keeps the client's own
    # worst case (~15-17s) comfortably clear of that boundary.
    max_attempts: int = 3
    backoff_initial: float = 0.5
    backoff_max: float = 20.0
    verify_tls: bool = True

    @field_validator("api_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        toml_path = (
            Path(os.environ[_CONFIG_FILE_ENV_VAR])
            if _CONFIG_FILE_ENV_VAR in os.environ
            else default_config_path()
        )
        if toml_path.is_file():
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=toml_path))
        return tuple(sources)
