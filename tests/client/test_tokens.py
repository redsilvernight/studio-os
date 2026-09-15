from __future__ import annotations

import keyring
import keyring.errors
import pytest
from studio_client.tokens import (
    EnvTokenStore,
    KeyringTokenStore,
    MemoryTokenStore,
    MissingMachineToken,
    origin_of,
    resolve_token,
)


def test_origin_of_strips_path_and_query() -> None:
    assert origin_of("https://vps.example.com:8443/anything?x=1") == "https://vps.example.com:8443"


def test_env_token_store_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_MACHINE_TOKEN", "secret-token")
    assert EnvTokenStore().get_token("https://any.example.com") == "secret-token"


def test_env_token_store_absent_returns_none() -> None:
    assert EnvTokenStore().get_token("https://any.example.com") is None


def test_env_token_store_is_read_only() -> None:
    store = EnvTokenStore()
    with pytest.raises(NotImplementedError):
        store.set_token("https://any.example.com", "x")
    with pytest.raises(NotImplementedError):
        store.clear_token("https://any.example.com")


def test_memory_token_store_roundtrip() -> None:
    store = MemoryTokenStore()
    store.set_token("https://a.example.com", "tok-a")
    assert store.get_token("https://a.example.com") == "tok-a"
    store.clear_token("https://a.example.com")
    assert store.get_token("https://a.example.com") is None


def test_keyring_token_store_returns_none_on_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(service_name: str, username: str) -> str:
        raise keyring.errors.KeyringError("no backend available")

    monkeypatch.setattr(keyring, "get_password", _raise)

    assert KeyringTokenStore().get_token("https://a.example.com") is None


def test_keyring_token_store_clear_ignores_missing_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(service_name: str, username: str) -> None:
        raise keyring.errors.PasswordDeleteError("not found")

    monkeypatch.setattr(keyring, "delete_password", _raise)

    KeyringTokenStore().clear_token("https://a.example.com")  # must not raise


def test_resolve_token_prefers_env_over_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_MACHINE_TOKEN", "from-env")
    store = MemoryTokenStore()
    store.set_token("https://a.example.com", "from-store")

    assert resolve_token("https://a.example.com", stores=[store]) == "from-env"


def test_resolve_token_falls_back_to_store() -> None:
    store = MemoryTokenStore()
    store.set_token("https://a.example.com", "from-store")

    assert resolve_token("https://a.example.com", stores=[store]) == "from-store"


def test_resolve_token_raises_when_missing() -> None:
    with pytest.raises(MissingMachineToken):
        resolve_token("https://a.example.com", stores=[MemoryTokenStore()])
