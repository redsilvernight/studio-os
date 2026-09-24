from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import Any

import pytest
from studio_client.daemon.logging import (
    configure_daemon_logging,
    export_diagnostics,
    redact_text,
)

_VECTORS = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "log_redaction_vectors.json").read_text(
        encoding="utf-8"
    )
)
_REDACTED: list[dict[str, Any]] = _VECTORS["redacted"]
_UNCHANGED: list[str] = _VECTORS["unchanged"]
_ALL_SECRETS = [secret for case in _REDACTED for secret in case["secrets"]]


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


@pytest.fixture
def daemon_log(tmp_path: Path):
    log_path = configure_daemon_logging(tmp_path)
    logger = logging.getLogger("studio_client.daemon")
    yield logger, log_path
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def _read_log(logger: logging.Logger, log_path: Path) -> str:
    for handler in logger.handlers:
        handler.flush()
    return log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("case", _REDACTED, ids=[case["name"] for case in _REDACTED])
def test_shared_vector_secrets_are_redacted(case: dict[str, Any]) -> None:
    redacted = redact_text(case["input"])

    for secret in case["secrets"]:
        assert secret not in redacted
    for kept in case.get("kept", []):
        assert kept in redacted
    assert "[REDACTED]" in redacted


@pytest.mark.parametrize("value", _UNCHANGED)
def test_shared_vector_ordinary_text_is_unchanged(value: str) -> None:
    assert redact_text(value) == value


@pytest.mark.parametrize("case", _REDACTED, ids=[case["name"] for case in _REDACTED])
def test_redaction_is_deterministic_and_idempotent(case: dict[str, Any]) -> None:
    once = redact_text(case["input"])

    assert redact_text(case["input"]) == once
    assert redact_text(once) == once


def test_redaction_removes_json_quoted_and_bearer_credentials() -> None:
    value = (
        '{"studio_mcp_machine_token": "machine-secret-value", '
        '"Authorization": "Bearer another-secret-value", '
        '"note": "kept"}'
    )

    redacted = redact_text(value)

    assert "machine-secret-value" not in redacted
    assert "another-secret-value" not in redacted
    assert '"note": "kept"' in redacted
    assert redacted.count("[REDACTED]") == 2


def test_redaction_survives_unusual_input() -> None:
    for value in (
        "\x00\x1b[31m",
        "\\" * 5000,
        '"' * 5000,
        "token=" * 2000,
        "é" * 10000,
        "?x-amz-" * 20000,
    ):
        assert isinstance(redact_text(value), str)


def test_daemon_log_file_never_holds_known_secrets(daemon_log) -> None:
    logger, log_path = daemon_log

    for case in _REDACTED:
        logger.info("vector [%s] %s", case["name"], case["input"])
    logger.info(
        "outbound request %s",
        {"api_key": "fake-key-0101", "Authorization": "Bearer fake-bearer-0102", "note": "kept"},
    )
    try:
        raise RuntimeError("upstream rejected password=fake-pass-0103")
    except RuntimeError:
        logger.exception("sync failed for https://u:fake-pass-0104@h.test/x")

    written = _read_log(logger, log_path)

    for secret in [
        *_ALL_SECRETS,
        "fake-key-0101",
        "fake-bearer-0102",
        "fake-pass-0103",
        "fake-pass-0104",
    ]:
        assert secret not in written
    assert "'note': 'kept'" in written
    assert "RuntimeError" in written


def test_daemon_log_keeps_ordinary_messages_readable(daemon_log) -> None:
    logger, log_path = daemon_log

    for value in _UNCHANGED:
        logger.info("%s", value)
    written = _read_log(logger, log_path)

    for value in _UNCHANGED:
        assert value in written
    assert " INFO studio_client.daemon " in written


def test_redaction_removes_credentials_and_signed_query_values() -> None:
    value = (
        "Authorization: Bearer machine-secret https://storage.test/a?X-Amz-Signature=abc&token=def"
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
