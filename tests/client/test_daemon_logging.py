from __future__ import annotations

import logging
import zipfile

import pytest
from studio_client.daemon.logging import (
    configure_daemon_logging,
    export_diagnostics,
    redact_text,
)


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


def test_redaction_removes_credentials_and_signed_query_values() -> None:
    value = (
        "Authorization: Bearer machine-secret "
        "https://storage.test/a?X-Amz-Signature=abc&token=def"
    )

    redacted = redact_text(value)

    assert "machine-secret" not in redacted
    assert "abc" not in redacted
    assert "def" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_diagnostics_are_bounded_and_redacted(tmp_path) -> None:
    log_path = configure_daemon_logging(tmp_path)
    logger = logging.getLogger("studio_client.daemon")
    logger.info("token=top-secret")
    for handler in logger.handlers:
        handler.flush()

    archive_path = export_diagnostics(
        tmp_path / "diagnostics.zip",
        health={"state": "running"},
        log_path=log_path,
        max_log_bytes=1024,
    )

    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {"daemon.log", "health.json"}
        assert "top-secret" not in archive.read("daemon.log").decode()
        assert archive.getinfo("daemon.log").file_size <= 1024
