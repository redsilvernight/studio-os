from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
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


class GitWatchConfig(BaseModel):
    """One watched Git repository and the Studio OS project its events belong
    to. `repo_path` is made absolute and normalised at load time so relative
    or mixed-separator spellings collapse to one identity (the Git watcher's
    persisted baseline key derives from it)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_path: Path
    project_id: UUID

    @field_validator("repo_path")
    @classmethod
    def _absolute_repo_path(cls, value: Path) -> Path:
        return Path(os.path.abspath(value.expanduser()))


_LEGACY_GIT_REPO_KEY = "git_watch_repo_path"
_LEGACY_GIT_PROJECT_KEY = "git_watch_project_id"
_LEGACY_GIT_KEYS = (_LEGACY_GIT_REPO_KEY, _LEGACY_GIT_PROJECT_KEY)


class ClientConfig(BaseSettings):
    """Bloc B client configuration (DEC-0024). Precedence: explicit
    constructor arguments > `STUDIO_CLIENT_*` environment variables > an
    optional TOML file > field defaults. Deliberately never reads the
    repo's `.env` (that file configures Bloc A: Postgres, MinIO)."""

    model_config = SettingsConfigDict(env_prefix="STUDIO_CLIENT_", extra="ignore")

    api_base_url: str
    profile_id: str = "default"
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
    heartbeat_interval_seconds: float = 30.0
    # Spreads concurrent machines' heartbeats instead of a synchronized
    # thundering herd hitting the server every interval at once.
    heartbeat_jitter_ratio: float = 0.1
    # Canonical Git watching: one entry per repository (`[[git_watches]]` in
    # TOML, a JSON array in `STUDIO_CLIENT_GIT_WATCHES`). The historical
    # `git_watch_repo_path` + `git_watch_project_id` pair is still accepted as
    # input and normalised into a single entry (`_normalise_git_watches`);
    # mixing both formats is rejected. No entry means no Git watcher.
    git_watches: tuple[GitWatchConfig, ...] = ()
    # Legacy single-repo input only, declared so the env source still reads
    # `STUDIO_CLIENT_GIT_WATCH_*`. Always None once loaded: folded into
    # `git_watches` by `_normalise_git_watches`.
    git_watch_repo_path: Path | None = None
    git_watch_project_id: UUID | None = None
    git_watch_interval_seconds: float = 30.0
    # A Godot watcher is disabled unless both its pattern and project id are
    # set — most daemon runs have no Godot to watch.
    godot_watch_process_pattern: str | None = None
    godot_watch_project_id: UUID | None = None
    godot_watch_interval_seconds: float = 10.0
    # Local knowledge adapters (DEC-0042, roadmap step 8.2). The vault path
    # is a machine-local setting — never a product constant — and the scope
    # defaults to deny-all: nothing is exposable until the operator lists
    # vault-relative prefixes (e.g. '["projects/my-slug/", "conventions/"]',
    # JSON in env/TOML for the tuple field).
    knowledge_vault_path: Path | None = None
    knowledge_graph_dir: Path | None = None
    knowledge_source_root: Path | None = None
    knowledge_scope_allow: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _normalise_git_watches(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        legacy_repo = data.get(_LEGACY_GIT_REPO_KEY)
        legacy_project = data.get(_LEGACY_GIT_PROJECT_KEY)
        if legacy_repo is None and legacy_project is None:
            return data
        if data.get("git_watches"):
            raise ValueError(
                "git_watches and the legacy git_watch_repo_path/git_watch_project_id "
                "are both set; migrate to git_watches only"
            )
        if legacy_repo is None or legacy_project is None:
            raise ValueError("git_watch_repo_path and git_watch_project_id must be set together")
        data = {k: v for k, v in data.items() if k not in _LEGACY_GIT_KEYS}
        data["git_watches"] = [{"repo_path": legacy_repo, "project_id": legacy_project}]
        return data

    @field_validator("git_watches")
    @classmethod
    def _reject_duplicate_repos(
        cls, value: tuple[GitWatchConfig, ...]
    ) -> tuple[GitWatchConfig, ...]:
        seen: set[str] = set()
        for watch in value:
            identity = os.path.normcase(watch.repo_path)
            if identity in seen:
                raise ValueError(f"git_watches lists the repository {watch.repo_path} twice")
            seen.add(identity)
        return value

    def git_repo_for_project(self, project_id: UUID) -> Path | None:
        """First watched repository declared for `project_id`, if any."""
        for watch in self.git_watches:
            if watch.project_id == project_id:
                return watch.repo_path
        return None

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
