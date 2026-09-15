from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from studio_client.config import ClientConfig, default_config_path


def test_requires_api_base_url() -> None:
    with pytest.raises(ValidationError):
        ClientConfig()


def test_strips_trailing_slash() -> None:
    config = ClientConfig(api_base_url="https://vps.example.com/")
    assert config.api_base_url == "https://vps.example.com"


def test_env_used_when_init_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://from-env.example.com")
    config = ClientConfig()
    assert config.api_base_url == "https://from-env.example.com"


def test_init_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://from-env.example.com")
    config = ClientConfig(api_base_url="https://from-init.example.com")
    assert config.api_base_url == "https://from-init.example.com"


def test_toml_file_used_when_env_and_init_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('api_base_url = "https://from-toml.example.com"\n')
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(toml_path))

    config = ClientConfig()

    assert config.api_base_url == "https://from-toml.example.com"


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('api_base_url = "https://from-toml.example.com"\n')
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(toml_path))
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://from-env.example.com")

    config = ClientConfig()

    assert config.api_base_url == "https://from-env.example.com"


def test_missing_toml_file_is_silently_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(tmp_path / "does-not-exist.toml"))
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://from-env.example.com")

    config = ClientConfig()

    assert config.api_base_url == "https://from-env.example.com"


def test_default_config_path_is_platform_specific() -> None:
    assert default_config_path().name == "config.toml"


def test_defaults_cover_idempotency_reclaim_window() -> None:
    """The default read timeout must not be shorter than the server's
    `_PENDING_RECLAIM_SECONDS` (30s, `services/api/src/studio_api/services/
    idempotency.py`) — otherwise a client would time out while a legitimate
    idempotent creation is still being processed by another request."""
    config = ClientConfig(api_base_url="https://vps.example.com")
    assert config.read_timeout >= 30.0
