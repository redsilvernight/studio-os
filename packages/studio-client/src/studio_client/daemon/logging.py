from __future__ import annotations

import json
import logging
import re
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+"),
    re.compile(r"(?i)(token|secret|password|signature|x-amz-signature)(\s*[:=]\s*)[^\s,;&]+"),
    re.compile(r"(?i)([?&](?:x-amz-[^=&]+|signature|token)=)[^&\s]+"),
)


def redact_text(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups == 1:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub(r"\1\2[REDACTED]", redacted)
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
