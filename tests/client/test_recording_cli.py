"""Etape 9.2 CLI: `studio mark "<label>"`. Transport and the local recording
store are both substituted, so these tests never open a socket to a real
server nor touch the machine's real outbox — only an `httpx.MockTransport`
and a `tmp_path` SQLite file."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from studio_client import api_client as api_client_module
from studio_client import cli
from studio_client.config import ClientConfig
from studio_client.outbox import OutboxStore, connect
from studio_client.recording import NullRecordingStore, OutboxRecordingStore, Recording
from studio_client.tokens import TokenStore
from studio_contracts.events import EventType

MACHINE = UUID("11111111-1111-1111-1111-111111111111")
PROJECT = UUID("22222222-2222-2222-2222-222222222222")
START = datetime(2026, 9, 15, 20, 0, 0, tzinfo=UTC)


def _force_transport(
    monkeypatch: pytest.MonkeyPatch, forced_transport: httpx.AsyncBaseTransport
) -> None:
    original_init = api_client_module.StudioApiClient.__init__

    def patched_init(
        self: api_client_module.StudioApiClient,
        config: ClientConfig,
        token_store: TokenStore | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        original_init(self, config, token_store, transport=forced_transport)

    monkeypatch.setattr(api_client_module.StudioApiClient, "__init__", patched_init)


@pytest.fixture(autouse=True)
def _cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "http://test")
    monkeypatch.setenv("STUDIO_CLIENT_MACHINE_TOKEN", "test-token")
    monkeypatch.setenv("STUDIO_CLIENT_MACHINE_ID", str(MACHINE))


def _null_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_recording_store", lambda: NullRecordingStore())


def _recording_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> OutboxRecordingStore:
    store = OutboxRecordingStore(OutboxStore(connect(tmp_path / "outbox.sqlite3")))
    monkeypatch.setattr(cli, "_recording_store", lambda: store)
    return store


def _echo_envelope(request: httpx.Request) -> httpx.Response:
    body: dict[str, Any] = json.loads(request.content)
    body["server_timestamp"] = START.isoformat()
    return httpx.Response(201, json=body)


def test_mark_with_project_posts_marker_event_and_prints_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _null_store(monkeypatch)
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return _echo_envelope(request)

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["mark", "first successful gameplay", "--project", str(PROJECT), "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out["label"] == "first successful gameplay"
    assert UUID(out["marker_id"])
    assert seen["path"] == "/api/v1/events"
    assert seen["body"]["event_type"] == EventType.RECORDING_MARKER_CREATED.value
    assert seen["body"]["project_id"] == str(PROJECT)
    assert seen["body"]["task_id"] is None
    assert seen["body"]["machine_id"] == str(MACHINE)
    assert seen["body"]["payload"] == {
        "marker_id": out["marker_id"],
        "label": "first successful gameplay",
        "recorded_at": seen["body"]["payload"]["recorded_at"],
    }


def test_mark_human_output_mentions_label(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _null_store(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return _echo_envelope(request)

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["mark", "boss down", "--project", str(PROJECT)])

    out = capsys.readouterr().out
    assert "boss down" in out
    assert "{" not in out


def test_mark_without_project_and_no_recording_exits_with_short_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _null_store(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["mark", "orphan"])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "no --project given" in err
    assert "Traceback" not in err


def test_mark_invalid_project_uuid_exits_with_short_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _null_store(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["mark", "x", "--project", "not-a-uuid"])

    assert excinfo.value.code == 1
    assert "invalid project_id" in capsys.readouterr().err


def test_mark_invalid_at_exits_with_short_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _null_store(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return _echo_envelope(request)

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["mark", "x", "--project", str(PROJECT), "--at", "not-a-time"])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "unrecognized timestamp" in err
    assert "Traceback" not in err


def test_mark_missing_machine_id_exits_with_short_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _null_store(monkeypatch)
    monkeypatch.delenv("STUDIO_CLIENT_MACHINE_ID")

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["mark", "x", "--project", str(PROJECT)])

    assert excinfo.value.code == 1
    assert "machine_id" in capsys.readouterr().err


def test_mark_explicit_task_and_session_travel_in_envelope_and_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _null_store(monkeypatch)
    task_id, session_id = uuid4(), uuid4()
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _echo_envelope(request)

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(
        [
            "mark",
            "note",
            "--project",
            str(PROJECT),
            "--task",
            str(task_id),
            "--session",
            str(session_id),
            "--json",
        ]
    )
    capsys.readouterr()

    assert seen["body"]["task_id"] == str(task_id)
    assert seen["body"]["payload"]["session_id"] == str(session_id)


def test_mark_relative_at_uses_active_recording_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _recording_store(monkeypatch, tmp_path)
    store.save(
        Recording(
            recording_id=uuid4(),
            project_id=PROJECT,
            started_at=START,
            task_id=None,
            session_id=None,
        )
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _echo_envelope(request)

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["mark", "clutch", "--at", "+30", "--json"])
    capsys.readouterr()

    payload = seen["body"]["payload"]
    assert payload["offset_seconds"] == 30.0
    assert payload["recorded_at"] == (START + timedelta(seconds=30)).isoformat()
    assert payload["recording_id"] is not None
    assert seen["body"]["project_id"] == str(PROJECT)


def test_mark_uses_active_recording_project_when_no_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _recording_store(monkeypatch, tmp_path)
    task_id = uuid4()
    store.save(
        Recording(recording_id=uuid4(), project_id=PROJECT, started_at=START, task_id=task_id)
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _echo_envelope(request)

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["mark", "auto", "--json"])
    capsys.readouterr()

    assert seen["body"]["project_id"] == str(PROJECT)
    assert seen["body"]["task_id"] == str(task_id)
