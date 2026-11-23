"""TOTP (RFC 6238) verification, stdlib only.

The console stores no secret: each operator's Base32 secret is part of the
server configuration. A six-digit code is accepted for the current 30 s step
and one step on either side (clock skew).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct
import time

DIGITS = 6
STEP_SECONDS = 30
_WINDOW_STEPS = 1


def _decode_secret(secret: str) -> bytes:
    normalized = secret.strip().replace(" ", "").upper()
    padding = "=" * (-len(normalized) % 8)
    return base64.b32decode(normalized + padding, casefold=True)


def _hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10**digits:0{digits}d}"


def totp(secret: str, *, at: float | None = None, digits: int = DIGITS) -> str:
    """Code valid at `at` (epoch seconds) for a Base32 `secret`."""
    counter = int((time.time() if at is None else at) // STEP_SECONDS)
    return _hotp(_decode_secret(secret), counter, digits)


def verify_totp(secret: str, code: str, *, at: float | None = None) -> bool:
    """True when `code` matches `secret` at `at`, one step of skew allowed."""
    normalized = code.strip().replace(" ", "")
    if len(normalized) != DIGITS or not normalized.isdigit():
        return False
    try:
        key = _decode_secret(secret)
    except (binascii.Error, ValueError):
        return False
    now = time.time() if at is None else at
    counter = int(now // STEP_SECONDS)
    for skew in range(-_WINDOW_STEPS, _WINDOW_STEPS + 1):
        target = counter + skew
        if target < 0:
            continue
        candidate = _hotp(key, target)
        if hmac.compare_digest(candidate, normalized):
            return True
    return False
