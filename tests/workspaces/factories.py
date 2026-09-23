from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import LocalWorkspaceConfig, WorkspaceRoots

PROFILE = ProfileRef(profile_id="default", server_origin="https://studio.example.test")
OTHER_PROFILE = ProfileRef(profile_id="second", server_origin="https://studio.example.test")
PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")
OTHER_PROJECT_ID = UUID("33333333-3333-4333-8333-333333333333")
CREATED = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
UPDATED = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def make_roots(root: str, repos: list[tuple[str, str]] | None = None) -> WorkspaceRoots:
    return WorkspaceRoots(
        workspace_root=root,
        repo_roots=[{"name": name, "path": path} for name, path in (repos or [])],
    )


def make_config(
    workspace_id: UUID,
    root: str,
    repos: list[tuple[str, str]] | None = None,
    profile: ProfileRef = PROFILE,
    project_id: UUID = PROJECT_ID,
) -> LocalWorkspaceConfig:
    return LocalWorkspaceConfig(
        workspace_id=workspace_id,
        profile=profile,
        project_id=project_id,
        project_slug="demo-game",
        roots=make_roots(root, repos),
        created_at=CREATED,
        updated_at=UPDATED,
    )
