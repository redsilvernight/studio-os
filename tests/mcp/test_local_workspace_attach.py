"""P2-mcp-local: launching `studio-os-local` from any MCP client attaches the
client's folder to a project.

At initialization the server asks for `roots/list` when the client declares
the roots capability and resolves every `file://` root, otherwise it resolves
the launch directory; `notifications/roots/list_changed` re-resolves. The
result is exposed machine-readable through `studio_resolve_workspace` — an
unresolved folder is an explicit reason and never creates a workspace.

Real stdio framing (a subprocess server, real Git repositories on disk, the
real registry), only the repository lookup is faked: the child answers from
an env-provided remote-key map instead of HTTP, so these tests need no
Postgres, no token and no network.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, ListRootsResult, Root
from studio_contracts.local.identity import ProfileRef
from studio_contracts.projects import ResolveRepositoryResponse
from studio_contracts.repositories import normalize_remote_url
from studio_mcp.local_server import create_local_server
from studio_mcp.workspace_attach import (
    RESOLVE_WORKSPACE_TOOL,
    WORKSPACE_INSTRUCTIONS,
    WorkspaceAttachConfig,
    WorkspaceAttachment,
    WorkspaceAttachmentMiddleware,
    file_root_to_path,
)
from studio_workspaces import RootConfirmationService, WorkspaceStore

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")

PROFILE = ProfileRef(profile_id="default", server_origin="https://studio.example")
PROJECT_A = UUID("44444444-4444-4444-8444-444444444444")
PROJECT_B = UUID("55555555-5555-5555-8555-555555555555")
REMOTE_A = "https://git.example/org/repo-a.git"
REMOTE_B = "https://git.example/org/repo-b.git"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHILD_SRCS = os.pathsep.join(
    str(_REPO_ROOT / relative)
    for relative in (
        "services/mcp/src",
        "packages/studio-contracts/src",
        "packages/studio-client/src",
        "packages/studio-code-graph/src",
        "packages/studio-workspaces/src",
    )
)

_CHILD_SCRIPT = """\
import json
import os
from pathlib import Path
from uuid import UUID

from studio_contracts.local.identity import ProfileRef
from studio_contracts.projects import ResolveRepositoryResponse
from studio_contracts.repositories import normalize_remote_url
from studio_mcp.local_server import create_local_server
from studio_mcp.workspace_attach import WorkspaceAttachConfig


class MapResolver:
    def __init__(self, mapping):
        self.mapping = mapping

    async def resolve_repository(self, remotes):
        project = self.mapping.get(normalize_remote_url(remotes[0])) if remotes else None
        if project is None:
            return ResolveRepositoryResponse(status="not_found")
        return ResolveRepositoryResponse(
            status="resolved", project_id=UUID(project), slug="demo", name="Demo"
        )


def main():
    fallback = os.environ.get("STUDIO_TEST_FALLBACK_DIR")
    config = WorkspaceAttachConfig(
        profile=ProfileRef(
            profile_id=os.environ.get("STUDIO_TEST_PROFILE_ID", "default"),
            server_origin=os.environ["STUDIO_TEST_PROFILE_ORIGIN"],
        ),
        registry_dir=Path(os.environ["STUDIO_TEST_REGISTRY_DIR"]),
        fallback_dir=Path(fallback) if fallback else None,
        resolver=MapResolver(json.loads(os.environ["STUDIO_TEST_RESOLVE_MAP"])),
    )
    create_local_server(workspace=config).run(transport="stdio")


main()
"""


def _git(*args: str, cwd: Path) -> None:
    subprocess.run([GIT or "git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(path: Path, remote: str | None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    (path / "file.txt").write_text("data", encoding="utf-8")
    _git("add", ".", cwd=path)
    _git("-c", "user.email=t@t.test", "-c", "user.name=t", "commit", "-m", "init", cwd=path)
    if remote is not None:
        _git("remote", "add", "origin", remote, cwd=path)


def _resolve_map() -> dict[str, str]:
    return {
        normalize_remote_url(REMOTE_A): str(PROJECT_A),
        normalize_remote_url(REMOTE_B): str(PROJECT_B),
    }


def _workspaces(registry: Path) -> list:
    return WorkspaceStore(registry, RootConfirmationService()).list_workspaces(PROFILE)


class FakeResolver:
    def __init__(self, mapping: dict[str, UUID]) -> None:
        self.mapping = mapping

    async def resolve_repository(self, remotes: Sequence[str]) -> ResolveRepositoryResponse:
        project = self.mapping.get(normalize_remote_url(remotes[0])) if remotes else None
        if project is None:
            return ResolveRepositoryResponse(status="not_found")
        return ResolveRepositoryResponse(
            status="resolved", project_id=project, slug="demo", name="Demo"
        )


class FakeSession:
    """Duck-typed `ServerSession`: only what the attachment reads."""

    def __init__(
        self,
        *,
        roots_capable: bool = True,
        roots: Sequence[Any] | None = None,
        listed: Any | None = None,
        error: Exception | None = None,
    ) -> None:
        self.roots_capable = roots_capable
        self.listed = listed if listed is not None else ListRootsResult(roots=list(roots or []))
        self.error = error
        self.list_calls = 0

    def check_client_capability(self, capability: Any) -> bool:
        return self.roots_capable and capability.roots is not None

    async def list_roots(self) -> ListRootsResult:
        self.list_calls += 1
        if self.error is not None:
            raise self.error
        return self.listed


def _config(tmp_path: Path, **overrides: Any) -> WorkspaceAttachConfig:
    kwargs: dict[str, Any] = {
        "profile": PROFILE,
        "registry_dir": tmp_path / "registry",
        "resolver": FakeResolver(
            {normalize_remote_url(REMOTE_A): PROJECT_A, normalize_remote_url(REMOTE_B): PROJECT_B}
        ),
    }
    kwargs.update(overrides)
    return WorkspaceAttachConfig(**kwargs)


# Unit: wiring and shapes


async def test_tool_registered_only_when_workspace_configured(tmp_path: Path) -> None:
    plain = create_local_server()
    assert RESOLVE_WORKSPACE_TOOL not in {tool.name for tool in await plain.list_tools()}
    assert plain.instructions is None

    attached = create_local_server(workspace=_config(tmp_path))
    by_name = {tool.name: tool for tool in await attached.list_tools()}
    assert RESOLVE_WORKSPACE_TOOL in by_name
    tool = by_name[RESOLVE_WORKSPACE_TOOL]
    assert tool.annotations is not None and tool.annotations.read_only_hint is True
    assert attached.instructions == WORKSPACE_INSTRUCTIONS


async def test_pre_init_payload_is_degraded_without_action(tmp_path: Path) -> None:
    attachment = WorkspaceAttachment(_config(tmp_path))
    payload = attachment.payload()
    assert payload["status"] == "unresolved"
    assert payload["reason"] == "not_initialized"
    assert payload["project_id"] is None
    assert _workspaces(tmp_path / "registry") == []


def test_file_root_to_path_round_trip_and_skips(tmp_path: Path) -> None:
    assert file_root_to_path((tmp_path / "repo").as_uri()) == tmp_path / "repo"
    assert file_root_to_path("https://example.test/repo") is None
    assert file_root_to_path("file://other-host/repo") is None
    assert file_root_to_path("relative/path") is None


@needs_git
async def test_refresh_cwd_fallback_without_roots_capability(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, REMOTE_A)
    attachment = WorkspaceAttachment(_config(tmp_path, fallback_dir=repo))
    await attachment.refresh(FakeSession(roots_capable=False))

    payload = attachment.payload()
    assert payload["status"] == "resolved"
    assert payload["reason"] == "resolved"
    assert payload["source"] == "cwd"
    assert payload["project_id"] == str(PROJECT_A)
    assert payload["cached"] is False
    assert len(_workspaces(tmp_path / "registry")) == 1


@needs_git
async def test_refresh_resolves_each_file_root_and_skips_non_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, REMOTE_A)
    attachment = WorkspaceAttachment(_config(tmp_path))
    await attachment.refresh(
        FakeSession(
            listed=SimpleNamespace(
                roots=[
                    SimpleNamespace(uri=repo.as_uri()),
                    SimpleNamespace(uri="https://example.test/remote"),
                ]
            )
        )
    )

    payload = attachment.payload()
    assert payload["status"] == "resolved"
    assert payload["source"] == "roots"
    assert payload["project_id"] == str(PROJECT_A)
    assert [entry["status"] for entry in payload["roots"]] == ["resolved", "unresolved"]
    assert payload["roots"][1]["reason"] == "non_file_root"


async def test_roots_list_failure_is_degraded(tmp_path: Path) -> None:
    attachment = WorkspaceAttachment(_config(tmp_path))
    await attachment.refresh(FakeSession(error=RuntimeError("back-channel gone")))

    payload = attachment.payload()
    assert payload["status"] == "unresolved"
    assert payload["reason"] == "roots_list_failed"
    assert "back-channel gone" in payload["detail"]
    assert _workspaces(tmp_path / "registry") == []


async def test_empty_roots_list_is_degraded(tmp_path: Path) -> None:
    attachment = WorkspaceAttachment(_config(tmp_path))
    await attachment.refresh(FakeSession(roots=[]))

    payload = attachment.payload()
    assert payload["status"] == "unresolved"
    assert payload["reason"] == "no_roots"
    assert payload["roots"] == []
    assert _workspaces(tmp_path / "registry") == []


async def test_middleware_refreshes_only_on_init_and_roots_changed(tmp_path: Path) -> None:
    attachment = WorkspaceAttachment(_config(tmp_path, fallback_dir=tmp_path))
    middleware = WorkspaceAttachmentMiddleware(attachment)
    seen: list[str] = []

    async def call_next(ctx: Any) -> None:
        seen.append(ctx.method)
        return None

    await middleware(SimpleNamespace(method="tools/list", session=FakeSession()), call_next)
    assert attachment.payload()["reason"] == "not_initialized"

    await middleware(
        SimpleNamespace(
            method="notifications/initialized", session=FakeSession(roots_capable=False)
        ),
        call_next,
    )
    assert attachment.payload()["source"] == "cwd"
    assert seen == ["tools/list", "notifications/initialized"]


async def test_tool_serves_cached_state_without_session(tmp_path: Path) -> None:
    server = create_local_server(workspace=_config(tmp_path))
    result = await server.call_tool(RESOLVE_WORKSPACE_TOOL, {})
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    assert result.structured_content["reason"] == "not_initialized"


@needs_git
async def test_tool_refreshes_on_demand_when_init_refresh_lost_the_race(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, REMOTE_A)
    server = create_local_server(workspace=_config(tmp_path, fallback_dir=repo))
    ctx = SimpleNamespace(session=FakeSession(roots_capable=False))
    result = await server.call_tool(RESOLVE_WORKSPACE_TOOL, {}, ctx)  # type: ignore[arg-type]
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    assert result.structured_content["status"] == "resolved"
    assert result.structured_content["project_id"] == str(PROJECT_A)


# Integration: real stdio framing, real Git, real registry, faked lookup


async def _call_state(session: ClientSession) -> dict[str, Any]:
    result = await session.call_tool(RESOLVE_WORKSPACE_TOOL, {})
    assert not result.is_error
    assert isinstance(result.structured_content, dict)
    return result.structured_content


async def _wait_state(
    session: ClientSession, predicate: Any, timeout: float = 15.0
) -> dict[str, Any]:
    """Poll `studio_resolve_workspace` until `predicate` holds: refreshes on
    `notifications/roots/list_changed` run asynchronously, so the state
    converges instead of flipping synchronously."""
    import anyio

    deadline = anyio.current_time() + timeout
    state = await _call_state(session)
    while not predicate(state):
        if anyio.current_time() >= deadline:
            raise AssertionError(f"workspace state never converged: {state!r}")
        await anyio.sleep(0.2)
        state = await _call_state(session)
    return state


def _child_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = {
        "PYTHONPATH": _CHILD_SRCS,
        "STUDIO_TEST_RESOLVE_MAP": json.dumps(_resolve_map()),
        "STUDIO_TEST_REGISTRY_DIR": str(tmp_path / "registry"),
        "STUDIO_TEST_PROFILE_ORIGIN": "https://studio.example",
        "STUDIO_TEST_PROFILE_ID": "default",
    }
    env.update(overrides)
    return env


@needs_git
async def test_stdio_roots_client_resolves_and_list_changed_reattaches(
    tmp_path: Path,
) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    plain = tmp_path / "plain"
    _init_repo(repo_a, REMOTE_A)
    _init_repo(repo_b, REMOTE_B)
    plain.mkdir()
    script = tmp_path / "child_server.py"
    script.write_text(_CHILD_SCRIPT, encoding="utf-8")
    errlog = tmp_path / "child-stderr.log"

    roots = [repo_a.as_uri()]

    async def list_roots(context: Any) -> ListRootsResult:
        return ListRootsResult(roots=[Root(uri=uri) for uri in roots])

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(script)],
        env=_child_env(tmp_path),
    )
    with errlog.open("w", encoding="utf-8") as err:
        async with stdio_client(params, errlog=err) as (read, write):
            async with ClientSession(read, write, list_roots_callback=list_roots) as session:
                await session.initialize()

                first = await _call_state(session)
                assert first["status"] == "resolved", errlog.read_text(encoding="utf-8")
                assert first["source"] == "roots"
                assert first["project_id"] == str(PROJECT_A)
                assert len(_workspaces(tmp_path / "registry")) == 1

                roots[:] = [repo_b.as_uri()]
                await session.send_roots_list_changed()
                second = await _wait_state(
                    session, lambda state: state["project_id"] == str(PROJECT_B)
                )
                assert second["status"] == "resolved"
                assert len(_workspaces(tmp_path / "registry")) == 2

                roots[:] = [plain.as_uri()]
                await session.send_roots_list_changed()
                third = await _wait_state(session, lambda state: state["reason"] == "not_a_repo")
                assert third["status"] == "unresolved"
                assert third["project_id"] is None
                assert len(_workspaces(tmp_path / "registry")) == 2


@needs_git
async def test_stdio_client_without_roots_falls_back_to_cwd(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, REMOTE_A)
    script = tmp_path / "child_server.py"
    script.write_text(_CHILD_SCRIPT, encoding="utf-8")
    errlog = tmp_path / "child-stderr.log"

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(script)],
        env=_child_env(tmp_path),
        cwd=str(repo),
    )
    with errlog.open("w", encoding="utf-8") as err:
        async with stdio_client(params, errlog=err) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                state = await _call_state(session)
                assert state["status"] == "resolved", errlog.read_text(encoding="utf-8")
                assert state["source"] == "cwd"
                assert state["project_id"] == str(PROJECT_A)
                assert len(_workspaces(tmp_path / "registry")) == 1
