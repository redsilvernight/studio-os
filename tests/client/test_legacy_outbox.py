"""A legacy (identity-less) outbox is never adopted: only explicit actions touch it."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client.cli import main as cli_main
from studio_client.config import ClientConfig, default_config_path
from studio_client.daemon.runtime import DaemonRuntime
from studio_client.daemon.service import DaemonController
from studio_client.outbox import OutboxStore, connect, default_outbox_path
from studio_client.outbox.legacy import (
    DISCARD_CONFIRMATION,
    LegacyOutboxError,
    discard_legacy_outbox,
    export_legacy_outbox,
    inspect_legacy_outbox,
    quarantine_legacy_outbox,
)
from studio_client.outbox.legacy import main as legacy_main
from studio_client.outbox.store import OutboxIdentityError
from studio_contracts.events import EventCreate, EventType
from studio_contracts.local.daemon_control import (
    DaemonAction,
    DaemonControlRequest,
    LocalErrorCode,
)
from studio_contracts.local.identity import ProfileRef

ORIGIN = "https://studio.example"


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def event() -> EventCreate:
    return EventCreate(
        event_id=uuid4(),
        event_type=EventType.TASK_CREATED,
        project_id=uuid4(),
        actor_type="agent",
        actor_id=uuid4(),
        client_timestamp=datetime.now(UTC),
        payload={"title": "queued before identities existed"},
    )


def legacy_outbox(queued: bool) -> Path:
    path = default_outbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    store = OutboxStore(connect(path))
    if queued:
        assert store.enqueue_event(event())
        store.connection.commit()
    store.connection.close()
    return path


def runtime(tmp_path: Path, origin: str = ORIGIN) -> DaemonRuntime:
    return DaemonRuntime(
        ClientConfig(api_base_url=origin, profile_id="main", machine_id=uuid4()),
        data_root=tmp_path / "data",
    )


def test_no_legacy_outbox_is_reported_absent() -> None:
    report = inspect_legacy_outbox()
    assert not report.exists
    assert not report.has_queued_work


def test_an_empty_legacy_outbox_holds_no_queued_work() -> None:
    legacy_outbox(queued=False)
    report = inspect_legacy_outbox()
    assert report.exists
    assert not report.has_queued_work


def test_a_non_empty_legacy_outbox_is_reported_with_counts() -> None:
    legacy_outbox(queued=True)
    report = inspect_legacy_outbox()
    assert report.has_queued_work
    assert report.counts["pending_events"] == 1


def test_an_unreadable_legacy_outbox_is_an_error_not_an_empty_one() -> None:
    path = default_outbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a sqlite database" * 64)
    with pytest.raises(LegacyOutboxError):
        inspect_legacy_outbox()


async def test_the_runtime_refuses_to_start_beside_a_non_empty_legacy_outbox(
    tmp_path: Path,
) -> None:
    path = legacy_outbox(queued=True)
    daemon = runtime(tmp_path)
    with pytest.raises(OutboxIdentityError):
        await daemon.run()
    assert path.exists()
    assert inspect_legacy_outbox().counts["pending_events"] == 1
    assert not daemon.outbox_path.exists()


async def test_the_runtime_refuses_an_unreadable_legacy_outbox(tmp_path: Path) -> None:
    path = default_outbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"garbage" * 128)
    with pytest.raises(OutboxIdentityError):
        await runtime(tmp_path).run()


async def test_two_origins_both_refuse_and_neither_adopts_it(tmp_path: Path) -> None:
    legacy_outbox(queued=True)
    for origin in (ORIGIN, "https://other.example"):
        with pytest.raises(OutboxIdentityError):
            await runtime(tmp_path, origin).run()
    assert inspect_legacy_outbox().counts["pending_events"] == 1


async def test_an_empty_legacy_outbox_does_not_block_the_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import studio_client.daemon.runtime as runtime_module

    class Refused(Exception):
        pass

    def boom(_config: object) -> object:
        raise Refused

    legacy_outbox(queued=False)
    monkeypatch.setattr(runtime_module, "StudioApiClient", boom)
    with pytest.raises(Refused):
        await runtime(tmp_path).run()


def test_the_controller_reports_an_identity_mismatch_for_a_legacy_outbox(
    tmp_path: Path,
) -> None:
    legacy_outbox(queued=True)
    controller = DaemonController(
        ClientConfig(api_base_url=ORIGIN, profile_id="main", machine_id=uuid4()),
        data_root=tmp_path / "data",
    )
    profile = ProfileRef(profile_id="main", server_origin=ORIGIN)
    controller.control(DaemonControlRequest(action=DaemonAction.START, profile=profile))
    deadline = time.monotonic() + 5
    status = controller.control(DaemonControlRequest(action=DaemonAction.STATUS, profile=profile))
    while time.monotonic() < deadline and status.status.last_crash is None:
        time.sleep(0.05)
        status = controller.control(
            DaemonControlRequest(action=DaemonAction.STATUS, profile=profile)
        )
    crash = status.status.last_crash
    assert crash is not None
    assert crash.error.code is LocalErrorCode.IDENTITY_MISMATCH
    assert not crash.error.retryable
    assert "legacy" in crash.error.message
    assert str(tmp_path) not in crash.error.message


def test_quarantine_moves_it_aside_without_reading_or_replaying_it(tmp_path: Path) -> None:
    path = legacy_outbox(queued=True)
    moved = quarantine_legacy_outbox(destination_dir=tmp_path / "vault")
    assert not path.exists()
    assert moved.exists()
    assert moved.parent == tmp_path / "vault"
    assert not inspect_legacy_outbox().exists
    assert inspect_legacy_outbox(moved).counts["pending_events"] == 1


def test_quarantine_frees_the_way_for_a_partitioned_outbox(tmp_path: Path) -> None:
    legacy_outbox(queued=True)
    quarantine_legacy_outbox(destination_dir=tmp_path / "vault")
    assert not inspect_legacy_outbox().has_queued_work


def test_export_writes_rows_and_leaves_the_outbox_untouched(tmp_path: Path) -> None:
    path = legacy_outbox(queued=True)
    exported = export_legacy_outbox(tmp_path / "dump" / "legacy.json")
    dump = json.loads(exported.read_text(encoding="utf-8"))
    assert len(dump["pending_events"]) == 1
    assert path.exists()
    assert inspect_legacy_outbox().counts["pending_events"] == 1


def test_export_never_overwrites(tmp_path: Path) -> None:
    legacy_outbox(queued=True)
    target = tmp_path / "legacy.json"
    target.write_text("keep", encoding="utf-8")
    with pytest.raises(LegacyOutboxError):
        export_legacy_outbox(target)
    assert target.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("confirmation", ["", "yes", "discard", DISCARD_CONFIRMATION.upper()])
def test_discard_without_the_exact_confirmation_deletes_nothing(confirmation: str) -> None:
    path = legacy_outbox(queued=True)
    with pytest.raises(LegacyOutboxError):
        discard_legacy_outbox(confirmation)
    assert path.exists()


def test_discard_with_the_confirmation_deletes_it() -> None:
    path = legacy_outbox(queued=True)
    discard_legacy_outbox(DISCARD_CONFIRMATION)
    assert not path.exists()


def test_actions_on_a_missing_outbox_are_errors(tmp_path: Path) -> None:
    with pytest.raises(LegacyOutboxError):
        quarantine_legacy_outbox()
    with pytest.raises(LegacyOutboxError):
        export_legacy_outbox(tmp_path / "x.json")
    with pytest.raises(LegacyOutboxError):
        discard_legacy_outbox(DISCARD_CONFIRMATION)


def test_the_command_line_offers_no_adoption_path(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        legacy_main(["adopt"])
    assert raised.value.code == 2
    assert "adopt" in capsys.readouterr().err


def test_the_command_line_status_quarantine_and_discard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = legacy_outbox(queued=True)
    assert legacy_main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["pending_events"] == 1
    assert legacy_main(["discard", "--confirm", "nope"]) == 1
    assert path.exists()
    assert legacy_main(["quarantine"]) == 0
    assert not path.exists()
    assert legacy_main(["quarantine"]) == 1


def test_studio_client_routes_outbox_legacy_before_loading_a_config(
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy_outbox(queued=False)
    with pytest.raises(SystemExit) as raised:
        cli_main(["outbox", "legacy", "status"])
    assert raised.value.code == 0
    assert json.loads(capsys.readouterr().out)["exists"] is True


def test_the_legacy_location_is_the_default_config_sibling() -> None:
    assert default_outbox_path().parent == default_config_path().parent
