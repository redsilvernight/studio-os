"""Wave 1b: the Desktop's effective `server_origin` reaches the sidecar, validated, fail-closed."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.daemon.desktop_origin import (
    DESKTOP_ORIGIN_ENV,
    TOKEN_ENV,
    TOKEN_ORIGIN_ENV,
    DesktopOriginError,
    bind_env_token,
    desktop_client_config,
    validate_desktop_origin,
)
from studio_client.daemon.runtime import DaemonRuntime
from studio_client.daemon.service import DaemonController, main
from studio_client.tokens import EnvTokenStore
from studio_contracts.local.daemon_control import DaemonAction, DaemonControlRequest
from studio_contracts.local.identity import ProfileRef

ORIGIN_A = "https://a.example"
ORIGIN_B = "https://b.example"


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


@pytest.fixture(autouse=True)
def _clean_desktop_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (DESKTOP_ORIGIN_ENV, TOKEN_ENV, TOKEN_ORIGIN_ENV):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://studio.example.com", "https://studio.example.com"),
        ("https://Studio.Example.com:443", "https://studio.example.com"),
        ("https://studio.example.com/", "https://studio.example.com"),
        ("https://studio.example.com:8443", "https://studio.example.com:8443"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("http://localhost:8000", "http://localhost:8000"),
    ],
)
def test_valid_origins_are_normalised(raw: str, expected: str) -> None:
    assert validate_desktop_origin(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "https://tauri.localhost.",
        "http://ipc.localhost",
        "tauri://localhost",
        "https://user:pw@studio.example.com",
        "https://studio.example.com/api/v1",
        "https://studio.example.com?x=1",
        "https://studio.example.com#frag",
        "http://studio.example.com",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://a.example --flag",
        "https://*.example.com",
        "https://studio.example.com:99999",
    ],
)
def test_invalid_origins_are_refused(raw: str) -> None:
    with pytest.raises(DesktopOriginError):
        validate_desktop_origin(raw)


def test_an_over_long_origin_is_refused() -> None:
    with pytest.raises(DesktopOriginError):
        validate_desktop_origin("https://" + "a" * 3000 + ".example")


def test_no_desktop_origin_means_the_sidecar_keeps_its_own_config() -> None:
    assert desktop_client_config() is None


def test_desktop_origin_drives_the_client_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DESKTOP_ORIGIN_ENV, ORIGIN_B)
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", f"{ORIGIN_A}/api/v1")
    config = desktop_client_config()
    assert config is not None
    assert config.api_base_url == ORIGIN_B


def test_invalid_desktop_origin_is_an_error_not_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DESKTOP_ORIGIN_ENV, "http://tauri.localhost")
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", f"{ORIGIN_A}/api/v1")
    with pytest.raises(DesktopOriginError):
        desktop_client_config()


def test_main_refuses_to_start_on_an_invalid_desktop_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv(DESKTOP_ORIGIN_ENV, "https://studio.example.com/api")
    assert main() == 2


def test_unbound_env_token_is_dropped_when_it_was_not_configured_for_the_desktop_origin() -> None:
    env = {TOKEN_ENV: "secret-token"}
    bind_env_token(ORIGIN_B, ORIGIN_A, env)
    assert TOKEN_ENV not in env
    assert TOKEN_ORIGIN_ENV not in env


def test_unbound_env_token_is_dropped_without_a_configured_origin() -> None:
    env = {TOKEN_ENV: "secret-token"}
    bind_env_token(ORIGIN_A, None, env)
    assert TOKEN_ENV not in env


def test_env_token_configured_for_the_same_origin_is_bound_to_it() -> None:
    env = {TOKEN_ENV: "secret-token"}
    bind_env_token(ORIGIN_A, ORIGIN_A, env)
    assert env[TOKEN_ORIGIN_ENV] == ORIGIN_A
    assert env[TOKEN_ENV] == "secret-token"


def test_explicitly_bound_env_token_is_left_to_the_store() -> None:
    env = {TOKEN_ENV: "secret-token", TOKEN_ORIGIN_ENV: ORIGIN_A}
    bind_env_token(ORIGIN_B, ORIGIN_A, env)
    assert env == {TOKEN_ENV: "secret-token", TOKEN_ORIGIN_ENV: ORIGIN_A}


def test_no_env_token_changes_nothing() -> None:
    env: dict[str, str] = {}
    bind_env_token(ORIGIN_A, ORIGIN_A, env)
    assert env == {}


def test_a_credential_bound_to_origin_a_is_never_served_to_origin_b(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TOKEN_ENV, "token-for-a")
    monkeypatch.setenv(TOKEN_ORIGIN_ENV, ORIGIN_A)
    store = EnvTokenStore()
    assert store.get_token(ORIGIN_A) == "token-for-a"
    assert store.get_token(ORIGIN_B) is None


def test_desktop_switch_a_to_b_strips_an_unbound_token_before_the_store_reads_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", f"{ORIGIN_A}/api/v1")
    monkeypatch.setenv(TOKEN_ENV, "token-for-a")
    monkeypatch.setenv(DESKTOP_ORIGIN_ENV, ORIGIN_B)
    config = desktop_client_config()
    assert config is not None
    assert EnvTokenStore().get_token(ORIGIN_B) is None
    assert EnvTokenStore().get_token(config.api_base_url) is None


def test_desktop_on_the_configured_origin_keeps_the_token_bound_to_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", f"{ORIGIN_A}/api/v1")
    monkeypatch.setenv(TOKEN_ENV, "token-for-a")
    monkeypatch.setenv(DESKTOP_ORIGIN_ENV, ORIGIN_A)
    config = desktop_client_config()
    assert config is not None
    store = EnvTokenStore()
    assert store.get_token(ORIGIN_A) == "token-for-a"
    assert store.get_token(ORIGIN_B) is None


def controller_for(origin: str, root: Path) -> DaemonController:
    return DaemonController(
        ClientConfig(api_base_url=origin, profile_id="main", machine_id=uuid4()),
        data_root=root,
    )


def control(origin: str) -> DaemonControlRequest:
    return DaemonControlRequest(
        action=DaemonAction.START,
        profile=ProfileRef(profile_id="main", server_origin=origin),
    )


def test_a_sidecar_on_the_desktop_origin_accepts_the_renderer_profile(tmp_path: Path) -> None:
    daemon = controller_for(ORIGIN_B, tmp_path)
    assert daemon._profile().server_origin == ORIGIN_B
    assert daemon.control(control(ORIGIN_B)).outcome.value != "identity_mismatch"


def test_a_sidecar_on_origin_a_refuses_a_renderer_on_origin_b(tmp_path: Path) -> None:
    answer = controller_for(ORIGIN_A, tmp_path).control(control(ORIGIN_B))
    assert answer.outcome.value == "identity_mismatch"


def test_the_two_origins_use_distinct_outboxes_and_locks(tmp_path: Path) -> None:
    first = DaemonRuntime(
        ClientConfig(api_base_url=ORIGIN_A, profile_id="main", machine_id=uuid4()),
        data_root=tmp_path,
    )
    second = DaemonRuntime(
        ClientConfig(api_base_url=ORIGIN_B, profile_id="main", machine_id=first.binding.machine_id),
        data_root=tmp_path,
    )
    assert first.outbox_path != second.outbox_path
