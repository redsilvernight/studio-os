"""Redaction of harness MCP entries.

A tool's user configuration holds its dedicated credential in clear text
(DEC-0104 §2). Everything Studi'OS derives from such an entry — hashes, plans,
backups, logs, errors — works on the *redacted* form computed here, so the
credential only ever exists in the harness's own file and in memory.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

TOKEN_MARK = "<token>"  # noqa: S105 — a marker, never a value
SECRET_MARK = "<secret>"  # noqa: S105 — a marker, never a value
_SECRET_CONTAINERS = ("headers", "env")
_BEARER = "Bearer "


def is_reference(value: str) -> bool:
    """A value that names a secret (`${VAR}`, `{env:VAR}`) instead of holding one."""
    return "${" in value or "{env:" in value


def _redact_value(value: Any) -> Any:
    if not isinstance(value, str) or is_reference(value):
        return value
    if value.startswith(_BEARER):
        return _BEARER + TOKEN_MARK
    return SECRET_MARK


def redact(entry: Any) -> Any:
    """`entry` with every literal header or environment value masked."""
    if isinstance(entry, dict):
        out: dict[str, Any] = {}
        for key, value in entry.items():
            if key in _SECRET_CONTAINERS and isinstance(value, dict):
                out[key] = {name: _redact_value(item) for name, item in value.items()}
            else:
                out[key] = redact(value)
        return out
    if isinstance(entry, list):
        return [redact(item) for item in entry]
    return entry


def holds_secret(entry: Any) -> bool:
    return redact(entry) != entry


def canonical(entry: Any) -> bytes:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def redacted_hash(entry: Any) -> str:
    return hashlib.sha256(canonical(redact(entry))).hexdigest()


def bearer_token(entry: Any) -> str | None:
    """The literal Bearer credential an entry carries, or None."""
    if not isinstance(entry, dict):
        return None
    headers = entry.get("headers")
    if not isinstance(headers, dict):
        return None
    value = headers.get("Authorization")
    if not isinstance(value, str) or not value.startswith(_BEARER) or is_reference(value):
        return None
    token = value[len(_BEARER) :].strip()
    return token or None


def fingerprint(token: str) -> str:
    """One-way identity of a credential (as `machine_identity` already keeps)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
