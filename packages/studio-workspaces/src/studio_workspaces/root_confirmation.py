from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from studio_contracts.local.workspace import WorkspaceRoots

from studio_workspaces.path_safety import workspace_binding_key


class RootConfirmationError(ValueError):
    pass


class ConfirmationMissing(RootConfirmationError):
    pass


class ConfirmationInvalid(RootConfirmationError):
    pass


class ConfirmationReused(RootConfirmationError):
    pass


class ConfirmationExpired(RootConfirmationError):
    pass


class ConfirmationMismatch(RootConfirmationError):
    pass


class StrayConfirmation(RootConfirmationError):
    pass


@dataclass
class _Entry:
    roots_hash: str
    expires_at: float


def roots_fingerprint(roots: WorkspaceRoots) -> str:
    canonical = roots.model_dump(mode="json")
    canonical["workspace_root"] = workspace_binding_key(canonical["workspace_root"])
    for repo in canonical.get("repo_roots", []):
        repo["path"] = workspace_binding_key(repo["path"])
    payload = repr(sorted(canonical.items())).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


Clock = Callable[[], float]


class RootConfirmationService:
    def __init__(self, ttl_seconds: float = 600.0, clock: Clock = time.monotonic) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, _Entry] = {}
        self._consumed: set[str] = set()

    def issue(self, target: WorkspaceRoots) -> str:
        confirmation_id = f"rc-{uuid4().hex}"
        expires_at = self._clock() + self._ttl_seconds
        with self._lock:
            self._pending[confirmation_id] = _Entry(roots_fingerprint(target), expires_at)
        return confirmation_id

    def consume(
        self,
        confirmation_id: str | None,
        current: WorkspaceRoots | None,
        new: WorkspaceRoots,
    ) -> None:
        if current == new:
            if confirmation_id is not None:
                raise StrayConfirmation("no root transition carries no confirmation id")
            return
        if confirmation_id is None:
            raise ConfirmationMissing("a root transition requires root_confirmation_id")
        with self._lock:
            if confirmation_id in self._consumed:
                raise ConfirmationReused("root confirmation ids are single-use")
            entry = self._pending.pop(confirmation_id, None)
            if entry is None:
                raise ConfirmationInvalid("unknown root confirmation id")
            self._consumed.add(confirmation_id)
            if self._clock() > entry.expires_at:
                raise ConfirmationExpired("root confirmation id has expired")
            if entry.roots_hash != roots_fingerprint(new):
                raise ConfirmationMismatch("root confirmation id is bound to other roots")

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @staticmethod
    def fresh_nonce() -> str:
        return secrets.token_urlsafe(8)
