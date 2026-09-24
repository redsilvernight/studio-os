from __future__ import annotations

import json
import logging
import re
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_SECRET_NAME = (
    r"token|secret(?:[_-]?(?:access[_-]?)?key)?|password|passwd|api[_-]?key"
    r"|private[_-]?key|credentials?|signature"
)
_SENSITIVE_KEY = rf"(?:{_SECRET_NAME}|authorization)"

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(rf'(?i)("[A-Za-z0-9_.-]*?{_SENSITIVE_KEY}"\s*:\s*")(?:[^"\\]|\\.)*(")'),
        r"\1[REDACTED]\2",
    ),
    (
        re.compile(rf"(?i)('[A-Za-z0-9_.-]*?{_SENSITIVE_KEY}'\s*:\s*b?')(?:[^'\\]|\\.)*(')"),
        r"\1[REDACTED]\2",
    ),
    (re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (
        re.compile(
            rf"(?i)({_SECRET_NAME}|x-amz-signature)"
            r"([\"']?\s*[:=]\s*[\"']?)[^\s,;&\"'{}\[\]]+"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(r"(?i)([?&](?:x-amz-[^=&?\s]+|signature|token|key)=)[^&\s]+"),
        r"\1[REDACTED]",
    ),
    (re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),
)


def redact_text(value: str) -> str:
    """Mask credentials before they reach daemon.log.

    Same policy as ``redact`` in ``desktop/src-tauri/src/diagnostics.rs``; both
    are checked against ``tests/fixtures/log_redaction_vectors.json``.
    """
    redacted = value
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def configure_daemon_logging(data_root: Path) -> Path:
    log_path = data_root / "logs" / "daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("studio_client.daemon")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return log_path


def export_diagnostics(
    destination: Path,
    *,
    health: dict[str, Any],
    log_path: Path,
    max_log_bytes: int = 512 * 1024,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    log_tail = b""
    if log_path.is_file():
        with log_path.open("rb") as source:
            source.seek(0, 2)
            source.seek(max(0, source.tell() - max_log_bytes))
            log_tail = source.read(max_log_bytes)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "health.json",
            json.dumps(health, ensure_ascii=False, indent=2, sort_keys=True),
        )
        archive.writestr(
            "daemon.log",
            redact_text(log_tail.decode("utf-8", errors="replace")),
        )
    return destination
