from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from studio_client.api_client import StudioApiClient
    from studio_client.config import ClientConfig
    from studio_client.errors import (
        AuthenticationError,
        ConflictError,
        ForbiddenError,
        NotFoundError,
        QuotaError,
        ServerError,
        StudioApiError,
        TransferError,
        TransportError,
    )
    from studio_client.knowledge import (
        GraphifyGraphProvider,
        GraphProvider,
        KnowledgeError,
        ScopePolicy,
        VaultMemoryProvider,
    )
    from studio_client.tokens import (
        EnvTokenStore,
        KeyringTokenStore,
        MemoryTokenStore,
        MissingMachineToken,
        TokenStore,
    )
    from studio_client.transfers import TransferClient

# Lazy re-exports (PEP 562): importing a lightweight submodule such as
# `studio_client.knowledge` must not drag in the token stores, the HTTP client
# or the transfer client — the local-only knowledge MCP server imports the
# package and stays free of credential and network machinery (DEC-0047).
_MODULE_BY_NAME = {
    "StudioApiClient": "studio_client.api_client",
    "ClientConfig": "studio_client.config",
    "StudioApiError": "studio_client.errors",
    "AuthenticationError": "studio_client.errors",
    "ForbiddenError": "studio_client.errors",
    "NotFoundError": "studio_client.errors",
    "ConflictError": "studio_client.errors",
    "QuotaError": "studio_client.errors",
    "ServerError": "studio_client.errors",
    "TransferError": "studio_client.errors",
    "TransportError": "studio_client.errors",
    "TokenStore": "studio_client.tokens",
    "EnvTokenStore": "studio_client.tokens",
    "KeyringTokenStore": "studio_client.tokens",
    "MemoryTokenStore": "studio_client.tokens",
    "MissingMachineToken": "studio_client.tokens",
    "TransferClient": "studio_client.transfers",
    "KnowledgeError": "studio_client.knowledge",
    "ScopePolicy": "studio_client.knowledge",
    "VaultMemoryProvider": "studio_client.knowledge",
    "GraphProvider": "studio_client.knowledge",
    "GraphifyGraphProvider": "studio_client.knowledge",
}

__all__ = [
    "StudioApiClient",
    "ClientConfig",
    "StudioApiError",
    "AuthenticationError",
    "ForbiddenError",
    "NotFoundError",
    "ConflictError",
    "QuotaError",
    "ServerError",
    "TransferError",
    "TransportError",
    "TokenStore",
    "EnvTokenStore",
    "KeyringTokenStore",
    "MemoryTokenStore",
    "MissingMachineToken",
    "TransferClient",
    "KnowledgeError",
    "ScopePolicy",
    "VaultMemoryProvider",
    "GraphProvider",
    "GraphifyGraphProvider",
]


def __getattr__(name: str) -> Any:
    module_name = _MODULE_BY_NAME.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value: Any = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return list(__all__)
