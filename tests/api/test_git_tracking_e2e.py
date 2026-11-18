"""P4-e2e (DEC-0364): a second user tracks a project managed by someone else
with no manual action. The real client resolution (`resolve_workspace`, real Git
repositories and machine-local registry) runs against the real
`POST /projects/resolve-repository` route and its membership scoping."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_client.workspace_resolution import (
    ResolutionReason,
    ResolutionStatus,
    resolve_workspace,
)
from studio_contracts.local.identity import ProfileRef
from studio_contracts.projects import ResolveRepositoryResponse
from studio_workspaces.detected import list_detected_repositories

pytestmark = [
    pytest.mark.isolation,
    pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed"),
]

PROFILE = ProfileRef(profile_id="default", server_origin="http://studio.test")
REMOTE = "https://github.com/studio-os/demo.git"
FORK_REMOTE = "https://github.com/someone-else/demo.git"
PATH = "/api/v1/projects/resolve-repository"


class AsgiResolver:
    """The `RepositoryResolver` of one machine, served by the in-process API."""

    def __init__(self, client: AsyncClient, headers: dict[str, str]) -> None:
        self._client = client
        self._headers = headers

    async def resolve_repository(self, remotes: Sequence[str]) -> ResolveRepositoryResponse:
        response = await self._client.post(
            PATH, headers=self._headers, json={"remotes": list(remotes)}
        )
        assert response.status_code == 200, response.text
        return ResolveRepositoryResponse.model_validate(response.json())


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _clone(path: Path, remote: str) -> Path:
    """A repository as `git clone` leaves it: one commit, `origin` set."""
    path.mkdir(parents=True)
    _git("init", "-b", "main", cwd=path)
    (path / "file.txt").write_text("data", encoding="utf-8")
    _git("add", ".", cwd=path)
    _git("-c", "user.email=t@t.test", "-c", "user.name=t", "commit", "-m", "init", cwd=path)
    _git("remote", "add", "origin", remote, cwd=path)
    return path


async def _managed_project(
    client: AsyncClient, admin_auth_headers: dict[str, str], project: ProjectModel
) -> None:
    """User A: creates the project and links its repository."""
    linked = await client.post(
        f"/api/v1/projects/{project.id}/repositories",
        headers=admin_auth_headers,
        json={"url": REMOTE},
    )
    assert linked.status_code in (200, 201), linked.text


async def _add_member(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    granted = await client.put(
        f"/api/v1/projects/{project.id}/members/{machine[0].owner_user_id}",
        headers=admin_auth_headers,
    )
    assert granted.status_code in (200, 201), granted.text


async def test_member_tracks_project_without_manual_action_then_worktree_shares_it(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    tmp_path: Path,
) -> None:
    await _managed_project(client, admin_auth_headers, project)
    await _add_member(client, admin_auth_headers, project, machine)
    resolver = AsgiResolver(client, auth_headers)
    registry = tmp_path / "fresh-profile"
    clone = _clone(tmp_path / "clone", REMOTE)

    first = await resolve_workspace(clone, PROFILE, registry_dir=registry, client=resolver)

    assert first.status is ResolutionStatus.RESOLVED
    assert first.created and not first.cached
    assert first.project_id == project.id
    assert first.project_slug == project.slug
    assert list_detected_repositories(registry, PROFILE) == []

    worktree = tmp_path / "wt"
    _git("worktree", "add", "-b", "feature", str(worktree), cwd=clone)
    second = await resolve_workspace(worktree, PROFILE, registry_dir=registry, client=resolver)

    assert second.status is ResolutionStatus.RESOLVED
    assert second.cached and not second.created
    assert second.project_id == project.id
    assert second.workspace_id == first.workspace_id


async def test_non_member_gets_nothing_and_cannot_tell_a_known_repo_from_an_unknown_one(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    tmp_path: Path,
) -> None:
    await _managed_project(client, admin_auth_headers, project)
    resolver = AsgiResolver(client, auth_headers)
    registry = tmp_path / "profile"

    known = await resolve_workspace(
        _clone(tmp_path / "known", REMOTE), PROFILE, registry_dir=registry, client=resolver
    )
    unknown = await resolve_workspace(
        _clone(tmp_path / "unknown", "https://github.com/nobody/nothing.git"),
        PROFILE,
        registry_dir=registry,
        client=resolver,
    )

    for result in (known, unknown):
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.reason is ResolutionReason.NOT_FOUND
        assert result.project_id is None and result.workspace is None
    assert known.detail == unknown.detail
    assert not (tmp_path / "known" / ".studio").exists()
    assert not (tmp_path / "unknown" / ".studio").exists()


async def test_fork_is_not_attached_and_shows_up_as_detected_repository(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    tmp_path: Path,
) -> None:
    await _managed_project(client, admin_auth_headers, project)
    await _add_member(client, admin_auth_headers, project, machine)
    registry = tmp_path / "profile"
    fork = _clone(tmp_path / "fork", FORK_REMOTE)

    result = await resolve_workspace(
        fork, PROFILE, registry_dir=registry, client=AsgiResolver(client, auth_headers)
    )

    assert result.status is ResolutionStatus.UNRESOLVED
    assert result.reason is ResolutionReason.NOT_FOUND
    assert result.workspace is None and result.project_id is None
    detected = list_detected_repositories(registry, PROFILE)
    assert [entry.repository_key for entry in detected] == ["github.com/someone-else/demo"]
    assert Path(detected[0].root).resolve() == fork.resolve()
