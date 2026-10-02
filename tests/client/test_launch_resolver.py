from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from studio_client.config import ClientConfig
from studio_client.daemon.runtime import build_launch_resolver
from studio_contracts.task_launch import TaskLaunch, TaskLaunchStatus

HARNESS = "opencode"


class _Adapter:
    harness_id = HARNESS


class _Registry:
    def __init__(self, adapter: _Adapter | None) -> None:
        self._adapter = adapter

    def get(self, harness_id: str) -> _Adapter | None:
        if self._adapter is not None and harness_id == self._adapter.harness_id:
            return self._adapter
        return None


class _Client:
    async def get_task(self, task_id: UUID) -> Any:
        return SimpleNamespace(title="Créer un fichier texte")


def _launch(project_id: UUID, *, harness: str = HARNESS) -> TaskLaunch:
    now = datetime.now(UTC)
    return TaskLaunch(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        version=1,
        project_id=project_id,
        task_id=uuid4(),
        machine_id=uuid4(),
        requested_by_user_id=uuid4(),
        harness_id=harness,
        status=TaskLaunchStatus.ACCEPTED,
        expires_at=now + timedelta(minutes=15),
    )


def _config() -> ClientConfig:
    return ClientConfig(api_base_url="https://studio.example")


async def test_resolver_falls_back_to_the_workspace_repository(tmp_path: Path) -> None:
    project_id = uuid4()
    repo = tmp_path / "repo"
    repo.mkdir()
    resolver = build_launch_resolver(
        _Client(),  # type: ignore[arg-type]
        _Registry(_Adapter()),  # type: ignore[arg-type]
        _config(),
        workspace_repo=lambda pid: repo if pid == project_id else None,
    )
    resolved = await resolver(_launch(project_id))
    assert resolved is not None
    assert resolved.repo_root == repo
    assert resolved.adapter.harness_id == HARNESS


async def test_resolver_returns_none_without_any_repository() -> None:
    resolver = build_launch_resolver(
        _Client(),  # type: ignore[arg-type]
        _Registry(_Adapter()),  # type: ignore[arg-type]
        _config(),
    )
    assert await resolver(_launch(uuid4())) is None


async def test_resolver_returns_none_for_an_unknown_harness(tmp_path: Path) -> None:
    project_id = uuid4()
    repo = tmp_path / "repo"
    repo.mkdir()
    resolver = build_launch_resolver(
        _Client(),  # type: ignore[arg-type]
        _Registry(None),  # type: ignore[arg-type]
        _config(),
        workspace_repo=lambda _pid: repo,
    )
    assert await resolver(_launch(project_id)) is None
