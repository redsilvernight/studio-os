"""Dedicated credentials for AI tools (DEC-0104 §2).

Each (workstation, tool) pair gets its own Studi'OS machine, created by the
Desktop on behalf of its owner and revoked when the tool is disconnected or
renewed. The Desktop's own credential never leaves its keyring.

`CredentialStore` keeps a small non-secret ledger next to the daemon data:
which machine each tool uses (id, name, fingerprint) and the revocations that
could not reach the server yet. It never holds a credential.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
from collections.abc import Callable, Coroutine
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from studio_client.harness.fsafe import FsError, atomic_write

_LEDGER_VERSION = 1


class ProvisionError(Exception):
    """The server did not create or revoke a machine. `reason` is a stable token;
    the message never carries a credential or a response body."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CredentialProvisioner(Protocol):
    def create(self, origin: str, display_name: str) -> tuple[str, str]:
        """A new machine owned by the Desktop's owner: (machine_id, credential)."""

    def revoke(self, origin: str, machine_id: str) -> None:
        """Idempotent: a machine that is already revoked or gone is a success."""


@dataclass(frozen=True)
class ToolCredential:
    adapter_id: str
    origin: str
    machine_id: str
    display_name: str
    credential_sha256: str
    created_at: str


@dataclass(frozen=True)
class PendingRevocation:
    origin: str
    machine_id: str


class CredentialStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def _load(self) -> tuple[dict[str, ToolCredential], list[PendingRevocation]]:
        try:
            body = json.loads(self._path.read_text(encoding="utf-8"))
            tools = {
                key: ToolCredential(**value) for key, value in dict(body.get("tools", {})).items()
            }
            pending = [PendingRevocation(**item) for item in list(body.get("pending", []))]
            return tools, pending
        except FileNotFoundError:
            return {}, []
        except (OSError, ValueError, TypeError, AttributeError):
            return {}, []

    def _save(self, tools: dict[str, ToolCredential], pending: list[PendingRevocation]) -> None:
        body = {
            "version": _LEDGER_VERSION,
            "tools": {key: asdict(value) for key, value in tools.items()},
            "pending": [asdict(item) for item in pending],
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self._path, json.dumps(body, indent=2).encode("utf-8"))
        except (OSError, FsError) as error:
            raise ProvisionError("ledger_unwritable") from error

    @staticmethod
    def _key(adapter_id: str, origin: str) -> str:
        return f"{adapter_id}@{origin}"

    def get(self, adapter_id: str, origin: str) -> ToolCredential | None:
        with self._lock:
            return self._load()[0].get(self._key(adapter_id, origin))

    def set(self, credential: ToolCredential) -> None:
        with self._lock:
            tools, pending = self._load()
            tools[self._key(credential.adapter_id, credential.origin)] = credential
            pending = [item for item in pending if item.machine_id != credential.machine_id]
            self._save(tools, pending)

    def forget(self, adapter_id: str, origin: str, machine_id: str) -> None:
        with self._lock:
            tools, pending = self._load()
            key = self._key(adapter_id, origin)
            if key in tools and tools[key].machine_id == machine_id:
                del tools[key]
                self._save(tools, pending)

    def add_pending(self, origin: str, machine_id: str) -> None:
        with self._lock:
            tools, pending = self._load()
            if all(item.machine_id != machine_id for item in pending):
                pending.append(PendingRevocation(origin, machine_id))
                self._save(tools, pending)

    def drop_pending(self, machine_id: str) -> None:
        with self._lock:
            tools, pending = self._load()
            kept = [item for item in pending if item.machine_id != machine_id]
            if len(kept) != len(pending):
                self._save(tools, kept)

    def pending(self) -> list[PendingRevocation]:
        with self._lock:
            return list(self._load()[1])


def revoke_or_defer(
    provisioner: CredentialProvisioner, store: CredentialStore, origin: str, machine_id: str
) -> bool:
    """Revoke now, or remember to retry. True when the revocation landed."""
    try:
        provisioner.revoke(origin, machine_id)
    except ProvisionError:
        with contextlib.suppress(ProvisionError):
            store.add_pending(origin, machine_id)
        return False
    with contextlib.suppress(ProvisionError):
        store.drop_pending(machine_id)
    return True


def retry_pending(provisioner: CredentialProvisioner, store: CredentialStore) -> None:
    for item in store.pending():
        revoke_or_defer(provisioner, store, item.origin, item.machine_id)


def tool_display_name(tool: str, host: Callable[[], str] = socket.gethostname) -> str:
    """`<WORKSTATION> · <Tool>`, as the machine appears in the dashboard."""
    try:
        name = host().strip() or "workstation"
    except OSError:
        name = "workstation"
    return f"{name.upper()[:60]} · {tool}"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ApiCredentialProvisioner:
    """Creates and revokes tool machines through the Studi'OS API with the
    Desktop's own credential (read from its keyring, never copied)."""

    def __init__(self, token_store_factory: Callable[[], object] | None = None) -> None:
        self._token_store_factory = token_store_factory

    def _client(self, origin: str):  # type: ignore[no-untyped-def]
        from studio_client.api_client import StudioApiClient
        from studio_client.config import ClientConfig
        from studio_client.tokens import KeyringTokenStore

        store = self._token_store_factory() if self._token_store_factory else KeyringTokenStore()
        return StudioApiClient(ClientConfig(api_base_url=origin), store)  # type: ignore[arg-type]

    def create(self, origin: str, display_name: str) -> tuple[str, str]:
        from studio_contracts.auth import MachineCreate

        async def run() -> tuple[str, str]:
            async with self._client(origin) as client:
                own = await client.get_own_machine()
                created = await client.create_machine(
                    MachineCreate(owner_user_id=own.owner_user_id, display_name=display_name)
                )
                return str(created.id), created.credential

        try:
            return _run(run())
        except Exception as error:  # noqa: BLE001 — mapped to a fixed token, no text kept
            raise ProvisionError(_reason(error)) from None

    def revoke(self, origin: str, machine_id: str) -> None:
        async def run() -> None:
            async with self._client(origin) as client:
                await client.revoke_machine(UUID(machine_id))

        try:
            _run(run())
        except Exception as error:  # noqa: BLE001 — mapped to a fixed token, no text kept
            if getattr(error, "status_code", None) == 404:
                return
            raise ProvisionError(_reason(error)) from None


def _reason(error: BaseException) -> str:
    status = getattr(error, "status_code", None)
    if status == 403:
        return "credential_forbidden"
    if status == 401:
        return "desktop_unauthenticated"
    if isinstance(status, int) and status >= 400:
        return "credential_server_error"
    return "credential_unreachable"


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine from synchronous code, even when a loop is running on
    this thread (the bridge dispatch is synchronous)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: dict[str, object] = {}

    def target() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as error:  # noqa: BLE001
            result["error"] = error

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result["value"]  # type: ignore[return-value]
