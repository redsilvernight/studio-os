"""Real entry point (`studio_client.cli.main`): argparse parsing, subcommand
dispatch, JSON/human output formatting, and CLI-boundary error handling
(invalid UUID, missing configuration). `test_api_client.py` and
`test_api_client_against_app.py` exercise `StudioApiClient` directly — this
file is the gap ROADMAP_STEP6_BREAKDOWN.md sous-etape 6.5 flagged as
uncovered: nothing exercised `cli.main` itself, only the client it builds on.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import uvicorn
from sqlalchemy import delete
from studio_api.db import session as db_api_session
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.user import UserModel
from studio_api.main import app as studio_api_app
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_client import api_client as api_client_module
from studio_client import cli
from studio_client.config import ClientConfig
from studio_client.tokens import TokenStore

# The live-server fixture below needs the app's real (non-overridden)
# `get_session` to point at the test database, same as
# `tests/api/test_events.py`'s `live_client` fixture — set at import time,
# before `get_session_factory()`'s module-level engine cache can be
# populated by anything else.
os.environ["STUDIO_DATABASE_URL"] = os.environ.get(
    "STUDIO_TEST_DATABASE_URL", "postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test"
)


def _force_transport(
    monkeypatch: pytest.MonkeyPatch, forced_transport: httpx.AsyncBaseTransport
) -> None:
    """`cli._with_client` always builds `StudioApiClient(config,
    KeyringTokenStore())` with no transport — patch `__init__` so it uses
    a test transport instead of opening a real socket, the same technique
    `conftest.py`'s `app_transport` fixture exists to support."""
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
def _cli_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "http://test")
    monkeypatch.setenv("STUDIO_CLIENT_MACHINE_TOKEN", "test-token")


def _project_body(project_id: uuid.UUID) -> dict[str, Any]:
    return {
        "id": str(project_id),
        "slug": "demo",
        "name": "Demo",
        "description": None,
        "archived": False,
        "version": 1,
        "created_at": "2026-09-13T00:00:00Z",
        "updated_at": "2026-09-13T00:00:00Z",
    }


def test_projects_list_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/projects"
        return httpx.Response(200, json=[_project_body(project_id)])

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["projects", "list", "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out == [_project_body(project_id)]


def test_projects_list_human_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_project_body(project_id)])

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["projects", "list"])

    out = capsys.readouterr().out
    assert str(project_id) in out
    assert "{" not in out


def test_projects_list_empty_human_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["projects", "list"])

    assert capsys.readouterr().out.strip() == "(none)"


def test_tasks_create_generates_idempotency_key_and_prints_task(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id = uuid.uuid4()
    task_id = uuid.uuid4()
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["idempotency_key"] = request.headers.get("idempotency-key")
        return httpx.Response(
            201,
            json={
                "id": str(task_id),
                "readable_id": None,
                "project_id": str(project_id),
                "title": "Ship it",
                "description": None,
                "status": "created",
                "claimed_by_machine_id": None,
                "claimed_by_agent_id": None,
                "version": 1,
                "created_at": "2026-09-13T00:00:00Z",
                "updated_at": "2026-09-13T00:00:00Z",
            },
        )

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["tasks", "create", "--project-id", str(project_id), "--title", "Ship it", "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out["id"] == str(task_id)
    assert out["title"] == "Ship it"
    uuid.UUID(seen["idempotency_key"])  # generated by the CLI, not by StudioApiClient


def test_claims_release_json_output_does_not_call_str_on_json_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    claim_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["claims", "release", str(claim_id), "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out == {"released": str(claim_id)}


def _ai_work_body(work_id: uuid.UUID, project_id: uuid.UUID, agent_id: uuid.UUID) -> dict[str, Any]:
    return {
        "id": str(work_id),
        "task_id": None,
        "project_id": str(project_id),
        "agent_id": str(agent_id),
        "machine_id": None,
        "summary": "Investigate claim TTL bug",
        "status": "review_requested",
        "changed_files": [],
        "tests_run": [],
        "started_at": "2026-09-13T00:00:00Z",
        "ended_at": None,
        "agent_profile": None,
        "harness": None,
        "provider": None,
        "model": None,
    }


def test_ai_work_list_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id, work_id, agent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/ai-work"
        return httpx.Response(200, json=[_ai_work_body(work_id, project_id, agent_id)])

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["ai-work", "list", "--project-id", str(project_id), "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out == [_ai_work_body(work_id, project_id, agent_id)]


def test_ai_work_show_finds_matching_entry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id, work_id, other_id, agent_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                _ai_work_body(other_id, project_id, agent_id),
                _ai_work_body(work_id, project_id, agent_id),
            ],
        )

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["ai-work", "show", str(work_id), "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out["id"] == str(work_id)


def test_ai_work_show_not_found_exits_with_short_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    missing_id = uuid.uuid4()
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["ai-work", "show", str(missing_id), "--json"])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert str(missing_id) in err
    assert "not found" in err


def _review_queue_body(
    work_id: uuid.UUID, project_id: uuid.UUID, agent_id: uuid.UUID
) -> dict[str, Any]:
    return {
        "items": [
            {
                "kind": "ai_work_review",
                "id": str(work_id),
                "project_id": str(project_id),
                "task_id": None,
                "title": "Needs review",
                "agent_id": str(agent_id),
                "requested_at": "2026-09-13T00:00:00Z",
            }
        ],
        "generated_at": "2026-09-13T00:05:00Z",
    }


def test_review_queue_list_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id, work_id, agent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/review-queue"
        return httpx.Response(200, json=_review_queue_body(work_id, project_id, agent_id))

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["review-queue", "list", "--project-id", str(project_id), "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out == _review_queue_body(work_id, project_id, agent_id)["items"]


def test_notifications_list_is_a_true_alias_of_review_queue_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """DEC-0051: notifications = review-queue, not a second implementation —
    same client call, byte-identical output shape."""
    project_id, work_id, agent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/review-queue"
        return httpx.Response(200, json=_review_queue_body(work_id, project_id, agent_id))

    _force_transport(monkeypatch, httpx.MockTransport(handler))
    cli.main(["review-queue", "list", "--project-id", str(project_id), "--json"])
    review_queue_out = capsys.readouterr().out

    _force_transport(monkeypatch, httpx.MockTransport(handler))
    cli.main(["notifications", "list", "--project-id", str(project_id), "--json"])
    notifications_out = capsys.readouterr().out

    assert notifications_out == review_queue_out


def test_timeline_list_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id = uuid.uuid4()
    body = {
        "project_id": str(project_id),
        "days": [
            {
                "date": "2026-09-13",
                "events": [
                    {
                        "event_id": str(uuid.uuid4()),
                        "event_type": "task.created",
                        "project_id": str(project_id),
                        "task_id": None,
                        "machine_id": None,
                        "actor_type": "system",
                        "actor_id": str(uuid.uuid4()),
                        "client_timestamp": "2026-09-13T00:00:00Z",
                        "server_timestamp": "2026-09-13T00:00:00Z",
                        "payload": {},
                        "schema_version": 1,
                    }
                ],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/timeline"
        return httpx.Response(200, json=body)

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["timeline", "list", "--project-id", str(project_id), "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out == body


@pytest.mark.parametrize(
    ("argv", "expected_field"),
    [
        (["tasks", "show", "not-a-uuid"], "task_id"),
        (["tasks", "create", "--project-id", "not-a-uuid", "--title", "x"], "project_id"),
        (["claims", "renew", "not-a-uuid"], "claim_id"),
        (["ai-work", "show", "not-a-uuid"], "ai_work_id"),
        (["timeline", "list", "--project-id", "not-a-uuid"], "project_id"),
    ],
)
def test_invalid_uuid_exits_with_short_stderr_message_no_traceback(
    capsys: pytest.CaptureFixture[str], argv: list[str], expected_field: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(argv)

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert f"invalid {expected_field}" in err
    assert "Traceback" not in err


def test_missing_config_exits_with_short_stderr_message_no_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("STUDIO_CLIENT_API_BASE_URL", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["projects", "list"])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "api_base_url" in err
    assert "Traceback" not in err


def test_bad_subcommand_exits_nonzero_via_argparse(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["not-a-command"])

    assert excinfo.value.code != 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _create_committed_project_and_token() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]:
    await db_api_session.reset_engine()
    session_factory = db_api_session.get_session_factory()
    async with session_factory() as session:
        user = await provisioning_service.create_user(
            session, "CLI Test User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine_model, token = await provisioning_service.create_machine(
            session, user.id, "cli-test-machine"
        )
        project = await projects_service.create_project(
            session, f"proj-{uuid.uuid4().hex[:8]}", "CLI Test Project", None, creator=None
        )
    await db_api_session.reset_engine()
    return user.id, project.id, machine_model.id, token


async def _delete_committed_rows(
    user_id: uuid.UUID, project_id: uuid.UUID, machine_id: uuid.UUID
) -> None:
    await db_api_session.reset_engine()
    session_factory = db_api_session.get_session_factory()
    async with session_factory() as session:
        await session.execute(delete(EventModel).where(EventModel.project_id == project_id))
        await session.execute(delete(TaskModel).where(TaskModel.project_id == project_id))
        await session.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
        await session.execute(delete(MachineModel).where(MachineModel.id == machine_id))
        await session.execute(delete(UserModel).where(UserModel.id == user_id))
        await session.commit()
    await db_api_session.reset_engine()


@pytest.fixture
def live_server_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A real uvicorn server on a background OS thread, talking to the real
    (committed, non-savepoint) test database, with `STUDIO_CLIENT_*` env
    pointing `cli.main` at it. Needed because `cli.main` opens a brand new
    event loop via `asyncio.run` on every invocation (that's how the real
    binary behaves) — a savepoint-bound `AsyncSession` shared with
    pytest-asyncio's own loop (as `app_transport` in `conftest.py` provides)
    cannot cross that loop boundary, but a real socket connection to a
    server running on its own thread/loop can, the same reasoning as
    `tests/api/test_events.py`'s `live_client` fixture."""
    user_id, project_id, machine_id, token = asyncio.run(_create_committed_project_and_token())

    port = _free_port()
    config = uvicorn.Config(studio_api_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, "live test server failed to start"

        monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setenv("STUDIO_CLIENT_MACHINE_TOKEN", token)
        yield str(project_id)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        asyncio.run(_delete_committed_rows(user_id, project_id, machine_id))


def test_task_create_and_show_round_trip_against_real_app(
    capsys: pytest.CaptureFixture[str], live_server_env: str
) -> None:
    """The representative real-app path DEC-0031 covered manually
    (`studio-client tasks create` / `tasks show`) — now automated against
    a real running server and a real Postgres database, through the actual
    `studio-client` entry point rather than `StudioApiClient` directly."""
    project_id = live_server_env

    cli.main(["tasks", "create", "--project-id", project_id, "--title", "Ship it", "--json"])
    created = json.loads(capsys.readouterr().out)
    assert created["title"] == "Ship it"
    assert created["project_id"] == project_id

    cli.main(["tasks", "show", created["id"], "--json"])
    shown = json.loads(capsys.readouterr().out)

    assert shown["id"] == created["id"]
    assert shown["status"] == "created"


def test_tasks_show_not_found_against_real_app_exits_with_short_message(
    capsys: pytest.CaptureFixture[str], live_server_env: str
) -> None:
    del live_server_env  # only needed to stand up the server + auth

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["tasks", "show", str(uuid.uuid4()), "--json"])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "404" in err
    assert "Traceback" not in err


def _build_body(build_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any]:
    return {
        "id": str(build_id),
        "project_id": str(project_id),
        "task_id": None,
        "github_integration_id": None,
        "workflow_run_id": 4001,
        "workflow_name": "CI",
        "run_number": 1,
        "branch": "main",
        "commit_sha": "sha1",
        "pr_number": None,
        "status": "failed",
        "conclusion": "failure",
        "html_url": "https://example.test/runs/4001",
        "actor_login": "dev-one",
        "started_at": None,
        "completed_at": None,
        "created_at": "2026-09-16T10:00:00Z",
        "updated_at": "2026-09-16T10:05:00Z",
    }


def _producer_job_body(job_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any]:
    return {
        "id": str(job_id),
        "project_id": str(project_id),
        "kind": "priority_analysis",
        "status": "completed",
        "task_id": None,
        "result": {"ranking": []},
        "error": None,
        "created_at": "2026-09-16T10:00:00Z",
        "completed_at": "2026-09-16T10:00:01Z",
    }


def test_builds_list_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id, build_id = uuid.uuid4(), uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/builds"
        return httpx.Response(200, json=[_build_body(build_id, project_id)])

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["builds", "list", "--project-id", str(project_id), "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out == [_build_body(build_id, project_id)]


def test_builds_show_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id, build_id = uuid.uuid4(), uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/builds/{build_id}"
        return httpx.Response(200, json=_build_body(build_id, project_id))

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(["builds", "show", str(build_id), "--json"])

    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "failed"


def test_builds_list_invalid_status_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["builds", "list", "--status", "exploded"])
    assert excinfo.value.code == 1
    assert "unknown build status" in capsys.readouterr().err


def test_producer_run_posts_with_idempotency_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id, job_id = uuid.uuid4(), uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/producer-jobs"
        assert request.headers["Idempotency-Key"]
        return httpx.Response(201, json=_producer_job_body(job_id, project_id))

    _force_transport(monkeypatch, httpx.MockTransport(handler))

    cli.main(
        [
            "producer",
            "run",
            "--project-id",
            str(project_id),
            "--kind",
            "priority_analysis",
            "--json",
        ]
    )

    out = json.loads(capsys.readouterr().out)
    assert out["id"] == str(job_id)
    assert out["result"] == {"ranking": []}
