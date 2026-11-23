"""Operator passwords: bcrypt hashes stored in server configuration.

The console never stores a plaintext password. Configuration carries the
bcrypt hash (`$2b$…`), verification goes through `bcrypt.checkpw` which
compares in constant time. bcrypt only reads the first 72 bytes: longer
inputs are refused instead of silently truncated.

`python -c "from studio_operator.passwords import hash_password; print(hash_password('…'))"`
produces a hash to paste into `STUDIO_OPERATOR_OPERATORS`.
"""

from __future__ import annotations

import bcrypt

MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 12

# Compared against when the account is unknown, so a missing operator costs the
# same bcrypt work as a wrong password (no cheap timing oracle).
DUMMY_HASH = "$2b$12$TD6rno8QcN1naWtzviaSFu/.Xrx3866vr47myOq2uw4DHD663iAP2"


def hash_password(password: str, *, rounds: int = 12) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password longer than bcrypt's {MAX_PASSWORD_BYTES}-byte limit")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=rounds)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time verification; False on any malformed or missing hash."""
    candidate = password.encode("utf-8")
    if len(candidate) > MAX_PASSWORD_BYTES:
        return False
    encoded = password_hash or DUMMY_HASH
    try:
        return bcrypt.checkpw(candidate, encoded.encode("ascii"))
    except (ValueError, TypeError):
        return False
