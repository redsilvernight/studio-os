from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig, GitWatchConfig
from studio_client.launch import LaunchPolicy, LaunchPuller, evaluate_launch
from studio_client.tokens import MemoryTokenStore
from studio_contracts.task_launch import TaskLaunch, TaskLaunchReasonCode, TaskLaunchStatus

MACHINE_ID = uuid4()
PROJECT_ID = uuid4()


def _config(**overrides: Any) -> ClientConfig:
    params: dict[str, Any] = {
        "api_base_url": "http://test",
        "machine_id": MACHINE_ID,
        "max_attempts": 1,
        "launch_opt_in": True,
        "launch_allowed_harnesses": ("claude-code",),
        "git_watches": (GitWatchConfig(repo_path=".", project_id=PROJECT_ID),),
    }
    params.update(overrides)
    return ClientConfig(**params)


def _launch(
    *,
    status: TaskLaunchStatus = TaskLaunchStatus.REQUESTED,
    harness: str = "claude-code",
    project_id: UUID = PROJECT_ID,
) -> TaskLaunch:
    return TaskLaunch(
        id=uuid4(),
        version=3,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        project_id=project_id,
        task_id=uuid4(),
        machine_id=MACHINE_ID,
        requested_by_user_id=uuid4(),
        harness_id=harness,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


@pytest.mark.parametrize(
    ("config_overrides", "launch_kwargs", "running", "expected"),
    [
        ({}, {}, 0, TaskLaunchReasonCode.NONE),
        ({"launch_opt_in": False}, {}, 0, TaskLaunchReasonCode.NOT_OPTED_IN),
        ({}, {"project_id": uuid4()}, 0, TaskLaunchReasonCode.PROJECT_NOT_REGISTERED),
        ({}, {"harness": "codex"}, 0, TaskLaunchReasonCode.HARNESS_NOT_ALLOWED),
        ({"launch_allowed_harnesses": ()}, {}, 0, TaskLaunchReasonCode.HARNESS_NOT_ALLOWED),
        ({}, {}, 1, TaskLaunchReasonCode.CAPACITY_REACHED),
        ({"max_concurrent_launches": 2}, {}, 1, TaskLaunchReasonCode.NONE),
    ],
)
def test_policy(
    config_overrides: dict[str, Any],
    launch_kwargs: dict[str, Any],
    running: int,
    expected: TaskLaunchReasonCode,
) -> None:
    policy = LaunchPolicy.from_config(_config(**config_overrides))
    assert evaluate_launch(policy, _launch(**launch_kwargs), running=running) is expected


def _puller(
    pending: list[TaskLaunch], config: ClientConfig | None = None
) -> tuple[LaunchPuller, list[dict[str, Any]]]:
    reports: list[dict[str, Any]] = []
    by_id = {str(launch.id): launch for launch in pending}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == f"/api/v1/machines/{MACHINE_ID}/task-launches/pending"
            return httpx.Response(
                200, json={"items": [launch.model_dump(mode="json") for launch in pending]}
            )
        launch_id = request.url.path.split("/")[-2]
        body = json.loads(request.content)
        reports.append({"id": launch_id, **body})
        updated = by_id[launch_id].model_copy(
            update={"status": body["status"], "reason_code": body["reason_code"]}
        )
        return httpx.Response(200, json=updated.model_dump(mode="json"))

    tokens = MemoryTokenStore()
    tokens.set_token("http://test", "test-token")
    cfg = config or _config()
    client = StudioApiClient(cfg, tokens, transport=httpx.MockTransport(handler))
    return LaunchPuller(client, cfg), reports


async def test_accepts_allowed_launch_and_reports_version() -> None:
    puller, reports = _puller([_launch()])
    outcome = await puller.poll()
    assert [r["status"] for r in reports] == ["accepted"]
    assert reports[0]["expected_version"] == 3
    assert len(outcome.accepted) == 1
    assert puller.running == 1


async def test_rejects_with_closed_reason_when_not_opted_in() -> None:
    puller, reports = _puller([_launch()], _config(launch_opt_in=False))
    outcome = await puller.poll()
    assert reports[0]["status"] == "rejected"
    assert reports[0]["reason_code"] == "not_opted_in"
    assert outcome.accepted == []
    assert puller.running == 0


async def test_concurrency_counts_active_and_accepted_in_same_poll() -> None:
    active = _launch(status=TaskLaunchStatus.RUNNING)
    first, second = _launch(), _launch()
    puller, reports = _puller([active, first, second], _config(max_concurrent_launches=2))
    await puller.poll()
    assert [(r["status"], r["reason_code"]) for r in reports] == [
        ("accepted", "none"),
        ("rejected", "capacity_reached"),
    ]
    assert puller.running == 2


async def test_non_requested_launches_are_not_re_reported() -> None:
    puller, reports = _puller([_launch(status=TaskLaunchStatus.ACCEPTED)])
    await puller.poll()
    assert reports == []
    assert puller.running == 1
