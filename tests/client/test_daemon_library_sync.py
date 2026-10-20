from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.context.library import LibraryContextItem
from studio_client.daemon import skills_bridge
from studio_client.tokens import MemoryTokenStore

ORIGIN = "https://studio.example"


def _projection(
    key: str,
    kind: str,
    text: str,
    *,
    scope: str = "studio",
    version: int = 1,
) -> LibraryContextItem:
    schema = {
        "skill": "studio.library.skill/v1",
        "rule": "studio.library.rule/v1",
        "agent_definition": "studio.library.agent_definition/v1",
    }[kind]
    return LibraryContextItem(
        library_kind=kind,
        stable_key=key,
        version=version,
        version_origin="active",
        scope=scope,
        title=f"{kind} {key}",
        text=text,
        content_schema=schema,
    )


def _config(home: Path, data_root: Path) -> tuple[ClientConfig, MemoryTokenStore]:
    token_store = MemoryTokenStore()
    token_store.set_token(ORIGIN, "tok")
    return (
        ClientConfig(api_base_url=f"{ORIGIN}/api/v1", profile_id="main", machine_id=uuid4()),
        token_store,
    )


def _run(home: Path, data_root: Path) -> skills_bridge._AutoSyncRunner:
    config, token_store = _config(home, data_root)
    runner = skills_bridge._AutoSyncRunner(config, token_store, home, data_root)
    runner._run()
    return runner


def _patch_fetch(monkeypatch: pytest.MonkeyPatch, projections: list[LibraryContextItem]) -> None:
    async def fake(_config: ClientConfig, _token_store: MemoryTokenStore) -> Any:
        return projections

    monkeypatch.setattr(skills_bridge, "_fetch", fake)


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_auto_sync_projects_skills_rules_and_agents(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _patch_fetch(
        monkeypatch,
        [
            _projection("studio-git-flow", "skill", "Skill body"),
            _projection("coding-standard", "rule", "Rule body"),
            _projection("studio-tester", "agent_definition", "Agent body"),
        ],
    )

    _run(home, tmp_path / "data")

    assert (home / ".agents" / "skills" / "studio-git-flow" / "SKILL.md").is_file()
    assert (home / ".claude" / "skills" / "studio-git-flow" / "SKILL.md").is_file()
    assert (home / ".agents" / "rules" / "coding-standard.md").is_file()
    assert (home / ".claude" / "rules" / "coding-standard.md").is_file()
    assert (home / ".agents" / "definitions" / "studio-tester.md").is_file()
    assert (home / ".claude" / "agents" / "studio-tester.md").is_file()
    assert "Rule body" in (home / ".claude" / "rules" / "coding-standard.md").read_text(
        encoding="utf-8"
    )
    status = skills_bridge._load_status(tmp_path / "data")
    assert status is not None
    assert status.state.value == "updated"
    assert status.conflicts == []


def test_local_conflict_blocks_every_kind_and_stays_visible(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    edited = home / ".claude" / "rules" / "coding-standard.md"
    edited.parent.mkdir(parents=True)
    edited.write_text("hand edited\n", encoding="utf-8")
    _patch_fetch(
        monkeypatch,
        [
            _projection("studio-git-flow", "skill", "Skill body"),
            _projection("coding-standard", "rule", "Rule body"),
        ],
    )

    _run(home, tmp_path / "data")

    assert edited.read_text(encoding="utf-8") == "hand edited\n"
    assert not (home / ".agents" / "skills" / "studio-git-flow").exists()
    assert not (home / ".agents" / "rules" / "coding-standard.md").exists()
    status = skills_bridge._load_status(tmp_path / "data")
    assert status is not None
    assert status.state.value == "conflicts"
    assert ".claude/rules/coding-standard.md" in status.conflicts


def test_two_syncs_write_nothing_the_second_time(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _patch_fetch(
        monkeypatch,
        [
            _projection("studio-git-flow", "skill", "Skill body"),
            _projection("coding-standard", "rule", "Rule body"),
            _projection("studio-tester", "agent_definition", "Agent body"),
        ],
    )

    _run(home, tmp_path / "data")
    after_first = _snapshot(home)
    _run(home, tmp_path / "data")

    assert _snapshot(home) == after_first
    manifest = json.loads(
        (home / ".studio-os" / "library-definitions-manifest.json").read_text(encoding="utf-8")
    )
    assert [row["kind"] for row in manifest["items"]] == ["agent", "rule"]


@dataclass
class _Resource:
    id: UUID
    stable_key: str
    kind: str
    scope: str = "studio"
    status: str = "active"
    active_version: int = 1
    project_id: UUID | None = None


@dataclass
class _Version:
    resource_id: UUID
    version: int
    title: str
    content: dict[str, object]
    description: str | None = None


class _ReadOnlyApi:
    def __init__(self, resources: list[_Resource], versions: list[_Version]) -> None:
        self.resources = resources
        self.versions = versions
        self.calls: list[str] = []

    async def list_library_resources(self, *, limit: int = 100) -> list[_Resource]:
        self.calls.append("list_library_resources")
        return self.resources[:limit]

    async def list_library_locks(self, *, project_id: UUID | None) -> list[Any]:
        self.calls.append("list_library_locks")
        return []

    async def list_library_versions(self, resource_id: UUID) -> list[_Version]:
        self.calls.append("list_library_versions")
        return [row for row in self.versions if row.resource_id == resource_id]


def test_fetch_only_reads_the_library_never_publishes() -> None:
    resources = [
        _Resource(uuid4(), "studio-git-flow", "skill"),
        _Resource(uuid4(), "coding-standard", "rule"),
        _Resource(uuid4(), "studio-tester", "agent_definition"),
    ]
    versions = [
        _Version(
            resource.id,
            1,
            resource.stable_key,
            {
                "content_schema": f"studio.library.{resource.kind}/v1",
                "text": f"body of {resource.stable_key}",
            }
            if resource.kind != "agent_definition"
            else {
                "content_schema": "studio.library.agent_definition/v1",
                "summary": f"summary of {resource.stable_key}",
            },
        )
        for resource in resources
    ]
    api = _ReadOnlyApi(resources, versions)

    result = asyncio.run(skills_bridge.fetch_library_projections(api, None))

    assert {item.library_kind for item in result} == {"skill", "rule", "agent_definition"}
    assert set(api.calls) == {"list_library_resources", "list_library_versions"}
    assert not any(
        word in call
        for call in api.calls
        for word in ("create", "publish", "update", "activate", "post")
    )
