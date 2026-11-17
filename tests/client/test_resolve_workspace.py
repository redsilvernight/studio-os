"""`resolve_workspace`: one workspace per repository identity, created only
when the server of the active profile recognises a remote, cached by the
machine-local registry afterwards."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from studio_client.bootstrap_workspace import find_workspace
from studio_client.errors import ConflictError, TransportError
from studio_client.workspace_resolution import ResolutionReason, resolve_workspace
from studio_contracts.local.identity import ProfileRef
from studio_contracts.projects import ResolveRepositoryResponse
from studio_workspaces import RootConfirmationService, WorkspaceStore, register_workspace

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")

PROFILE = ProfileRef(profile_id="default", server_origin="https://studio.example")
OTHER_PROFILE = ProfileRef(profile_id="default", server_origin="https://other.example")
PROJECT = UUID("44444444-4444-4444-8444-444444444444")
REMOTE = "https://github.com/org/repo.git"
KEY = "github.com/org/repo"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run([GIT or "git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(path: Path, remote: str | None = REMOTE) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    (path / "file.txt").write_text("data", encoding="utf-8")
    _git("add", ".", cwd=path)
    _git("-c", "user.email=t@t.test", "-c", "user.name=t", "commit", "-m", "init", cwd=path)
    if remote is not None:
        _git("remote", "add", "origin", remote, cwd=path)


class FakeResolver:
    def __init__(
        self,
        response: ResolveRepositoryResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[list[str]] = []

    async def resolve_repository(self, remotes: Sequence[str]) -> ResolveRepositoryResponse:
        self.calls.append(list(remotes))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class ExplodingResolver:
    async def resolve_repository(self, remotes: Sequence[str]) -> ResolveRepositoryResponse:
        raise AssertionError(f"network forbidden, got remotes {list(remotes)!r}")


def _resolved() -> ResolveRepositoryResponse:
    return ResolveRepositoryResponse(
        status="resolved", project_id=PROJECT, slug="demo", name="Demo"
    )


def _store(registry: Path) -> WorkspaceStore:
    return WorkspaceStore(registry, RootConfirmationService())


@needs_git
async def test_worktree_and_main_checkout_share_one_workspace(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    worktree = tmp_path / "repo-wt"
    _git("worktree", "add", str(worktree), "-b", "task", cwd=repo)
    registry = tmp_path / "registry"
    resolver = FakeResolver(_resolved())

    main = await resolve_workspace(repo, PROFILE, registry_dir=registry, client=resolver)

    assert main.resolved and main.created and not main.cached
    assert main.workspace is not None
    assert main.workspace.project_id == PROJECT
    assert main.workspace.project_slug == "demo"
    assert main.project_id == PROJECT
    assert main.repository_key == KEY
    assert resolver.calls == [[KEY]]

    linked = await resolve_workspace(worktree, PROFILE, registry_dir=registry, client=resolver)

    assert linked.resolved and linked.cached and not linked.created
    assert linked.workspace_id == main.workspace_id
    assert len(resolver.calls) == 1
    assert len(list((registry / "workspaces").glob("*.json"))) == 1


@needs_git
async def test_same_path_second_call_is_served_by_the_cache(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    registry = tmp_path / "registry"
    resolver = FakeResolver(_resolved())

    first = await resolve_workspace(repo, PROFILE, registry_dir=registry, client=resolver)
    second = await resolve_workspace(repo, PROFILE, registry_dir=registry, client=resolver)

    assert second.workspace_id == first.workspace_id
    assert second.cached and not second.created
    assert len(resolver.calls) == 1


async def test_non_git_folder_is_unresolved_without_config(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    folder = tmp_path / "plain"
    folder.mkdir()

    result = await resolve_workspace(
        folder, PROFILE, registry_dir=registry, client=ExplodingResolver()
    )

    assert result.status == "unresolved"
    assert result.reason == ResolutionReason.NOT_A_REPO
    assert result.workspace is None
    assert not (registry / "workspaces").exists()


@needs_git
async def test_repository_without_remote_is_unresolved_without_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, remote=None)
    registry = tmp_path / "registry"

    result = await resolve_workspace(
        repo, PROFILE, registry_dir=registry, client=ExplodingResolver()
    )

    assert result.reason == ResolutionReason.NO_GIT_REMOTE
    assert result.workspace is None
    assert not (registry / "workspaces").exists()
    assert result.detected is None


@needs_git
async def test_not_found_creates_no_config_and_records_the_detected_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    registry = tmp_path / "registry"
    resolver = FakeResolver(ResolveRepositoryResponse(status="not_found"))

    result = await resolve_workspace(repo, PROFILE, registry_dir=registry, client=resolver)

    assert result.reason == ResolutionReason.NOT_FOUND
    assert result.workspace is None
    assert _store(registry).list_workspaces(PROFILE) == []
    assert result.detected is not None
    assert result.detected.reason == "not_found"
    assert result.detected.remotes == (KEY,)
    assert Path(result.detected.root).resolve() == repo.resolve()


@needs_git
async def test_ambiguous_is_unresolved_without_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    registry = tmp_path / "registry"
    resolver = FakeResolver(error=ConflictError(409, "ambiguous", "remotes match several projects"))

    result = await resolve_workspace(repo, PROFILE, registry_dir=registry, client=resolver)

    assert result.reason == ResolutionReason.AMBIGUOUS
    assert result.workspace is None
    assert _store(registry).list_workspaces(PROFILE) == []


@needs_git
async def test_unreachable_server_is_unresolved_without_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    registry = tmp_path / "registry"
    resolver = FakeResolver(error=TransportError("connection refused"))

    result = await resolve_workspace(repo, PROFILE, registry_dir=registry, client=resolver)

    assert result.reason == ResolutionReason.SERVER_UNREACHABLE
    assert result.workspace is None
    assert _store(registry).list_workspaces(PROFILE) == []
    assert result.detected is not None


@needs_git
async def test_another_server_origin_is_never_attached(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    registry = tmp_path / "registry"
    owner = register_workspace(registry, PROFILE, uuid4(), str(repo), project_slug="demo")

    result = await resolve_workspace(
        repo, OTHER_PROFILE, registry_dir=registry, client=ExplodingResolver()
    )

    assert result.reason == ResolutionReason.OTHER_PROFILE
    assert result.workspace is None
    configs = _store(registry).all_workspaces()
    assert [config.profile for config in configs] == [PROFILE]
    assert configs[0].workspace_id == owner.config.workspace_id


@needs_git
def test_find_workspace_accepts_a_worktree_of_the_registered_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    worktree = tmp_path / "repo-wt"
    _git("worktree", "add", str(worktree), "-b", "task", cwd=repo)
    registry = tmp_path / "registry"
    registered = register_workspace(registry, PROFILE, uuid4(), str(repo), project_slug="demo")

    found = find_workspace(registry, PROFILE, worktree)

    assert found.workspace_id == registered.config.workspace_id
