from __future__ import annotations

import hashlib
import secrets


def generate_machine_token() -> str:
    """Opaque credential (DEC-0003) — only its hash is ever stored, so revoking a
    machine is a single row update, never a key-rotation exercise."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
