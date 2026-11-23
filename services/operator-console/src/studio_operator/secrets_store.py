"""Activated and pending TOTP secrets, kept outside configuration.

Operators are listed in server configuration, but an enrollment secret cannot
be written back into an environment variable. The console therefore keeps a
small JSON state file (no database table, no migration):

    {"active": {"email": "BASE32SECRET"},
     "pending": {"email": {"secret": "BASE32SECRET", "expires_at": 1234.5}}}

Writes are atomic (temp file + os.replace) and the file is created with mode
0600 on POSIX. `STUDIO_OPERATOR_SECRETS_PATH` points at it (a mounted volume in
production); losing the file only forces operators to enroll again.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends

from studio_operator.settings import OperatorSettings, get_settings


class SecretStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, dict[str, object]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"active": {}, "pending": {}}
        if not isinstance(raw, dict):
            return {"active": {}, "pending": {}}
        return {
            "active": dict(raw.get("active") or {}),
            "pending": dict(raw.get("pending") or {}),
        }

    def _write(self, state: dict[str, dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(state, stream, indent=2, sort_keys=True)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def active_secret(self, email: str) -> str | None:
        value = self._read()["active"].get(email.lower())
        return value if isinstance(value, str) and value else None

    def start_pending(self, email: str, secret: str, *, ttl_seconds: int) -> None:
        state = self._read()
        pending = dict(state["pending"])
        pending[email.lower()] = {
            "secret": secret,
            "expires_at": time.time() + ttl_seconds,
        }
        state["pending"] = pending
        self._write(state)

    def pending_secret(self, email: str, *, now: float | None = None) -> str | None:
        entry = self._read()["pending"].get(email.lower())
        if not isinstance(entry, dict):
            return None
        expires_at = entry.get("expires_at")
        secret = entry.get("secret")
        if not isinstance(expires_at, (int, float)) or not isinstance(secret, str):
            return None
        if expires_at < (time.time() if now is None else now):
            return None
        return secret

    def activate(self, email: str, secret: str) -> None:
        state = self._read()
        active = dict(state["active"])
        active[email.lower()] = secret
        pending = dict(state["pending"])
        pending.pop(email.lower(), None)
        state["active"] = active
        state["pending"] = pending
        self._write(state)

    def clear_pending(self, email: str) -> None:
        state = self._read()
        pending = dict(state["pending"])
        pending.pop(email.lower(), None)
        state["pending"] = pending
        self._write(state)


def get_secret_store(
    settings: Annotated[OperatorSettings, Depends(get_settings)],
) -> SecretStore:
    return _store(settings.secrets_path)


@lru_cache(maxsize=8)
def _store(path: str) -> SecretStore:
    return SecretStore(path)
