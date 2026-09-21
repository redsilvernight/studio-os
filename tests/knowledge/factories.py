from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import (
    IndexLocation,
    KnowledgeConfig,
    LocalFeatures,
    LocalWorkspaceConfig,
    WorkspaceRoots,
)

WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")
PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")
PROFILE = ProfileRef(profile_id="default", server_origin="https://studio.example.test")
CREATED = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
UPDATED = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)

VAULT_DIRECTORY = "vault"
INDEX_DIRECTORY = "knowledge-index"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_vault(root: Path) -> Path:
    """A small, deterministic Markdown vault used across the suite."""
    vault = root / VAULT_DIRECTORY
    write(
        vault / "projects/demo/intro.md",
        "---\ntitle: Introduction\ntags: [mechanics]\n---\n"
        "# Intro\n\nSee [design](design.md), [[combat]] and #global-tag.\n",
    )
    write(vault / "projects/demo/design.md", "# Game design\n\nLinks to [intro](intro.md#L5).\n")
    write(
        vault / "projects/demo/combat.md",
        "---\ntags: mechanics, balance\n---\n# Combat rules\n\nDamage per turn.\n",
    )
    write(
        vault / "conventions/style.md",
        "# Style\n\nAlways cite [combat](../projects/demo/combat.md).\n",
    )
    write(vault / "templates/note.md", "# Template\n\nSkeleton only.\n")
    return vault


def make_knowledge_config(content_root: str = VAULT_DIRECTORY) -> KnowledgeConfig:
    return KnowledgeConfig(
        provider_id="markdown-files",
        content_root=content_root,
        index=IndexLocation(directory_name=INDEX_DIRECTORY),
    )


def make_config(
    root: Path,
    *,
    workspace_id: UUID = WORKSPACE_ID,
    content_root: str = VAULT_DIRECTORY,
    knowledge: bool = True,
    profile: ProfileRef = PROFILE,
) -> LocalWorkspaceConfig:
    return LocalWorkspaceConfig(
        workspace_id=workspace_id,
        profile=profile,
        project_id=PROJECT_ID,
        project_slug="demo-game",
        roots=WorkspaceRoots(workspace_root=str(root)),
        features=LocalFeatures(knowledge=knowledge),
        knowledge=make_knowledge_config(content_root) if knowledge else None,
        created_at=CREATED,
        updated_at=UPDATED,
    )
