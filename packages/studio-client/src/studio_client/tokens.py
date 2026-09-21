from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

import keyring
import keyring.errors

_ENV_VAR = "STUDIO_CLIENT_MACHINE_TOKEN"
_ENV_ORIGIN_VAR = "STUDIO_CLIENT_MACHINE_TOKEN_ORIGIN"
_DEFAULT_KEYRING_SERVICE = "studio-os"


def origin_of(api_base_url: str) -> str:
    """`https://vps.example.com:8443/anything` -> `https://vps.example.com:8443` —
    the keyring/env lookup key, so distinct VPS targets never collide."""
    parsed = urlparse(api_base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


class MissingMachineToken(RuntimeError):
    def __init__(self, origin: str) -> None:
        super().__init__(
            f"No machine token found for {origin!r}. Enroll this machine first: "
            "run `studio-admin machine create` on the server (or POST /api/v1/machines "
            "from an admin machine), then store the printed token with "
            "`studio-client login` or the STUDIO_CLIENT_MACHINE_TOKEN environment variable."
        )
        self.origin = origin


@runtime_checkable
class TokenStore(Protocol):
    def get_token(self, origin: str) -> str | None: ...
    def set_token(self, origin: str, token: str) -> None: ...
    def clear_token(self, origin: str) -> None: ...


class EnvTokenStore:
    """Reads `STUDIO_CLIENT_MACHINE_TOKEN` (CI/tests/headless override,
    symmetric with `STUDIO_MCP_MACHINE_TOKEN` from DEC-0023). Read-only:
    there is no file to persist to, so writes are a programming error.

    `STUDIO_CLIENT_MACHINE_TOKEN_ORIGIN` binds the token to one server origin:
    when set, the token is never returned for any other origin (fail closed)."""

    def get_token(self, origin: str) -> str | None:
        bound = os.environ.get(_ENV_ORIGIN_VAR)
        if bound and bound.rstrip("/").lower() != origin.rstrip("/").lower():
            return None
        return os.environ.get(_ENV_VAR) or None

    def set_token(self, origin: str, token: str) -> None:
        del origin, token
        raise NotImplementedError(
            "EnvTokenStore is read-only; set STUDIO_CLIENT_MACHINE_TOKEN instead"
        )

    def clear_token(self, origin: str) -> None:
        del origin
        raise NotImplementedError(
            "EnvTokenStore is read-only; unset STUDIO_CLIENT_MACHINE_TOKEN instead"
        )


class KeyringTokenStore:
    """OS credential store: Credential Manager (Windows), Keychain (macOS),
    SecretService (Linux) — via the `keyring` package. Default store for
    `resolve_token` (DEC-0024)."""

    def __init__(self, service_name: str = _DEFAULT_KEYRING_SERVICE) -> None:
        self._service_name = service_name

    def get_token(self, origin: str) -> str | None:
        try:
            return keyring.get_password(self._service_name, origin)
        except keyring.errors.KeyringError:
            return None

    def set_token(self, origin: str, token: str) -> None:
        keyring.set_password(self._service_name, origin, token)

    def clear_token(self, origin: str) -> None:
        try:
            keyring.delete_password(self._service_name, origin)
        except keyring.errors.PasswordDeleteError:
            pass


class MemoryTokenStore:
    """In-process only — tests, never production."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def get_token(self, origin: str) -> str | None:
        return self._tokens.get(origin)

    def set_token(self, origin: str, token: str) -> None:
        self._tokens[origin] = token

    def clear_token(self, origin: str) -> None:
        self._tokens.pop(origin, None)


def resolve_token(origin: str, *, stores: Sequence[TokenStore] | None = None) -> str:
    """Ordered resolution: `EnvTokenStore` always first (explicit override
    wins), then the given stores (default: a single `KeyringTokenStore`).
    Raises `MissingMachineToken` if none of them has one."""
    ordered: list[TokenStore] = [EnvTokenStore()]
    ordered.extend(stores if stores is not None else [KeyringTokenStore()])
    for store in ordered:
        token = store.get_token(origin)
        if token:
            return token
    raise MissingMachineToken(origin)
