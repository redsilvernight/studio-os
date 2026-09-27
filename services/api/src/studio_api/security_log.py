"""Security event log (A1): authentication outcomes and credential changes,
emitted on the `studio.security` logger without any secret.

Events carry a fixed name, an outcome and a few non-secret fields. Emails are
logged as a short SHA-256 digest (correlation without the address);
tokens, passwords and JWTs are never passed in. `RedactingFilter` is a second
line of defence installed on every handler by `configure_logging`: it masks
anything shaped like a credential that reaches any log record by mistake.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from starlette.requests import Request

logger = logging.getLogger("studio.security")

SECURITY_EVENT_ATTR = "security_event"
REDACTED = "[REDACTED]"

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization header values (Bearer/Basic/Token schemes).
    (re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}"), rf"\1 {REDACTED}"),
    # JWTs: three base64url segments, the first one a JSON header ("eyJ").
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), REDACTED),
    # key=value / "key": "value" pairs whose key names a secret.
    (
        re.compile(
            r"(?i)(\"?(?:password|passwd|secret|token|api[_-]?key|authorization|credential)"
            r"[A-Za-z_]*\"?\s*[:=]\s*\"?)([^\s\",}&]+)"
        ),
        rf"\1{REDACTED}",
    ),
    # bcrypt hashes.
    (re.compile(r"\$2[abxy]?\$\d{2}\$[./A-Za-z0-9]{53}"), REDACTED),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Masks credential-shaped substrings in every record's rendered message
    and exception text. Freezes the message (args consumed) so formatters
    cannot re-expand the raw arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed %-args: keep the template only
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def email_digest(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def security_event(
    event: str,
    *,
    outcome: str,
    request: Request | None = None,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit one security event. `fields` must be non-secret identifiers
    (ids, digests, reasons); values are redacted anyway as a safeguard."""
    payload: dict[str, Any] = {"event": event, "outcome": outcome}
    ip = client_ip(request)
    if ip is not None:
        payload["client_ip"] = ip
    for key, value in fields.items():
        if value is not None:
            payload[key] = redact(str(value))
    rendered = " ".join(f"{key}={value}" for key, value in payload.items())
    logger.log(level, "security %s", rendered, extra={SECURITY_EVENT_ATTR: payload})
