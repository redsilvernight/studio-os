from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.daemon import machine_identity
from studio_client.daemon.machine_identity import resolve_machine_id

ORIGIN = "https://studio.example"


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


class MemoryTokens:
    def __init__(self, token: str | None) -> None:
        self.token = token

    def get_token(self, origin: str) -> str | None:
        return self.token if origin == ORIGIN else None

    def set_token(self, origin: str, token: str) -> None:
        self.token = token

    def clear_token(self, origin: str) -> None:
        self.token = None


def config() -> ClientConfig:
    return ClientConfig(api_base_url=f"{ORIGIN}/api/v1", profile_id="main")


def fake_server(monkeypatch: pytest.MonkeyPatch, answers: list[UUID | Exception]) -> list[str]:
    calls: list[str] = []

    async def fetch(_config: ClientConfig, store: MemoryTokens) -> UUID:
        calls.append(store.token or "")
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(machine_identity, "_fetch", fetch)
    return calls


def test_no_credential_means_no_identity(tmp_path: Path, monkeypatch) -> None:
    calls = fake_server(monkeypatch, [uuid4()])
    assert resolve_machine_id(config(), tmp_path, token_store=MemoryTokens(None)) is None
    assert calls == []


def test_identity_is_fetched_once_then_served_from_cache(tmp_path: Path, monkeypatch) -> None:
    machine_id = uuid4()
    calls = fake_server(monkeypatch, [machine_id])
    tokens = MemoryTokens("secret-a")

    assert resolve_machine_id(config(), tmp_path, token_store=tokens) == machine_id
    assert resolve_machine_id(config(), tmp_path, token_store=tokens) == machine_id
    assert calls == ["secret-a"]
    cached = next((tmp_path / "identity").iterdir()).read_text(encoding="utf-8")
    assert "secret-a" not in cached


def test_a_new_credential_invalidates_the_cached_identity(tmp_path: Path, monkeypatch) -> None:
    first, second = uuid4(), uuid4()
    calls = fake_server(monkeypatch, [first, second])
    tokens = MemoryTokens("secret-a")
    assert resolve_machine_id(config(), tmp_path, token_store=tokens) == first

    tokens.token = "secret-b"

    assert resolve_machine_id(config(), tmp_path, token_store=tokens) == second
    assert calls == ["secret-a", "secret-b"]


def test_unreachable_server_without_cache_yields_no_identity(tmp_path: Path, monkeypatch) -> None:
    fake_server(monkeypatch, [OSError("offline")])
    assert resolve_machine_id(config(), tmp_path, token_store=MemoryTokens("secret-a")) is None
