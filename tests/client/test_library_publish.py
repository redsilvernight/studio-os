from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from studio_client.canonical import load_rule_meta, load_rule_text
from studio_client.publish import (
    PublishError,
    build_publish_items,
    publish_items,
)
from studio_contracts.library import (
    SKILL_FILES_MAX,
    LibraryActivate,
    LibraryKind,
    LibraryResource,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersion,
    LibraryVersionCreate,
)

REPO = Path(__file__).resolve().parents[2]


class FakeClient:
    """In-memory Library honouring the parts of the HTTP surface publish uses."""

    def __init__(self) -> None:
        self.resources: dict[UUID, LibraryResource] = {}
        self.versions: dict[UUID, list[LibraryVersion]] = {}
        self.writes: list[str] = []

    async def list_library_resources(
        self,
        *,
        kind: str | None = None,
        scope: str | None = None,
        project_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[LibraryResource]:
        rows = [
            r
            for r in self.resources.values()
            if (kind is None or r.kind.value == kind)
            and (scope is None or r.scope.value == scope)
            and (project_id is None or r.project_id == project_id)
        ]
        return rows[offset : offset + limit]

    async def get_library_resource(self, resource_id: UUID) -> LibraryResource:
        return self.resources[resource_id]

    async def list_library_versions(self, resource_id: UUID) -> list[LibraryVersion]:
        return list(self.versions[resource_id])

    def _version(self, resource_id: UUID, number: int, data: Any) -> LibraryVersion:
        return LibraryVersion(
            id=uuid4(),
            resource_id=resource_id,
            version=number,
            title=data.title,
            content=data.content,
            dependencies=data.dependencies,
            created_at=datetime.now(UTC),
        )

    async def create_library_resource(
        self, resource_in: LibraryResourceCreate, *, idempotency_key: str
    ) -> LibraryResource:
        self.writes.append(f"create:{resource_in.stable_key}")
        resource = LibraryResource(
            id=uuid4(),
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            kind=resource_in.kind,
            stable_key=resource_in.stable_key,
            scope=resource_in.scope,
            project_id=resource_in.project_id,
        )
        self.resources[resource.id] = resource
        self.versions[resource.id] = [self._version(resource.id, 1, resource_in)]
        return resource

    async def create_library_version(
        self, resource_id: UUID, version_in: LibraryVersionCreate, *, idempotency_key: str
    ) -> LibraryVersion:
        self.writes.append(f"version:{self.resources[resource_id].stable_key}")
        number = len(self.versions[resource_id]) + 1
        version = self._version(resource_id, number, version_in)
        self.versions[resource_id].append(version)
        return version

    async def activate_library_version(
        self, resource_id: UUID, activate_in: LibraryActivate, *, idempotency_key: str
    ) -> LibraryResource:
        resource = self.resources[resource_id]
        assert activate_in.expected_resource_version == resource.version
        self.writes.append(f"activate:{resource.stable_key}")
        updated = resource.model_copy(
            update={"active_version": activate_in.version, "version": resource.version + 1}
        )
        self.resources[resource_id] = updated
        return updated


def _run(client: FakeClient, **kwargs: Any) -> Any:
    return asyncio.run(publish_items(client, **kwargs))  # type: ignore[arg-type]


def test_items_ordered_rules_skills_agents_and_agent_pins() -> None:
    items = build_publish_items(REPO)
    order = {"rule": 0, "skill": 1, "model_profile": 2, "agent": 3}
    kinds = [item.kind for item in items]
    assert kinds == sorted(kinds, key=order.__getitem__)
    tester = next(i for i in items if i.kind == "agent" and i.stable_key == "studio-tester")
    assert ("rule", "contracts") in tester.pins
    assert ("model_profile", "studio-tester-profile") in tester.pins
    assert tester.content["content_schema"] == "studio.library.agent_definition/v2"
    assert str(tester.content["instructions"]).startswith("Common lifecycle")
    assert str(tester.content["intended_use"]).startswith("Use after implementing")


def test_model_profile_items_carry_agent_requirements() -> None:
    items = build_publish_items(REPO, kinds=("agent",))
    profiles = {i.stable_key: i for i in items if i.kind == "model_profile"}
    assert "studio-tester-profile" in profiles
    profile = profiles["studio-tester-profile"]
    assert profile.content["content_schema"] == "studio.library.model_profile/v1"
    assert profile.content["requirements"] == {
        "reasoning": "medium",
        "coding": False,
        "tools_required": [],
        "local_compatible": False,
    }
    with pytest.raises(PublishError, match="published with its agent"):
        build_publish_items(REPO, kinds=("model_profile",))


def test_unknown_key_and_scope_mismatch_fail_closed() -> None:
    with pytest.raises(PublishError, match="no canonical resource"):
        build_publish_items(REPO, keys=["nope-not-a-key"])
    with pytest.raises(PublishError, match="project-id"):
        _run(FakeClient(), items=[], scope=LibraryScope.PROJECT, project_id=None)
    with pytest.raises(PublishError, match="project-id"):
        _run(FakeClient(), items=[], scope=LibraryScope.STUDIO, project_id=uuid4())


def test_publish_creates_then_is_idempotent() -> None:
    items = build_publish_items(REPO, kinds=("rule", "skill", "agent"), keys=["studio-tester"])
    client = FakeClient()
    needed = build_publish_items(REPO, kinds=("rule", "skill"))
    first = _run(
        client,
        items=[*needed, *items],
        scope=LibraryScope.STUDIO,
        project_id=None,
        activate=True,
    )
    assert all(r.action == "created" and r.activated for r in first)
    agent = next(r for r in first if r.kind == "agent")
    agent_resource = next(
        r for r in client.resources.values() if r.kind == LibraryKind.AGENT_DEFINITION
    )
    pins = client.versions[agent_resource.id][0].dependencies
    assert {(p.kind.value, p.stable_key, p.version) for p in pins} >= {
        ("rule", "contracts", 1),
        ("model_profile", "studio-tester-profile", 1),
    }
    assert agent.version == 1
    # The profile is published before the agent that pins it.
    assert [r.kind for r in first].index("model_profile") < [r.kind for r in first].index("agent")

    writes_before = len(client.writes)
    second = _run(
        client,
        items=[*needed, *items],
        scope=LibraryScope.STUDIO,
        project_id=None,
        activate=True,
    )
    assert all(r.action == "unchanged" and not r.activated for r in second)
    assert len(client.writes) == writes_before


def test_rule_content_v2_carries_applies_to() -> None:
    (item,) = build_publish_items(REPO, kinds=("rule",), keys=["contracts"])
    applies_to, body = load_rule_meta(REPO, "contracts")
    assert item.content == {
        "content_schema": "studio.library.rule/v2",
        "text": body,
        "applies_to": applies_to,
    }
    assert applies_to and body == load_rule_text(REPO, "contracts")


def test_skill_references_publish_as_files() -> None:
    (graphify,) = build_publish_items(REPO, kinds=("skill",), keys=["graphify"])
    files = graphify.content["files"]
    assert isinstance(files, list) and len(files) == 8
    assert [f["path"] for f in files] == sorted(f["path"] for f in files)
    assert all(f["path"].startswith("references/") for f in files)
    assert all(f["sha256"] == hashlib.sha256(f["text"].encode("utf-8")).hexdigest() for f in files)
    (single,) = build_publish_items(REPO, kinds=("skill",), keys=["openapi-sync"])
    assert "files" not in single.content


def test_skill_files_budget_fails_closed(tmp_path: Path) -> None:
    skill = tmp_path / ".agents" / "skills" / "heavy"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: heavy\ndescription: Heavy skill\n---\n\nbody\n", encoding="utf-8"
    )
    for index in range(SKILL_FILES_MAX + 1):
        (skill / "references" / f"f{index:02d}.md").write_text(f"file {index}\n", encoding="utf-8")
    with pytest.raises(PublishError, match="auxiliary files, max"):
        build_publish_items(tmp_path, kinds=("skill",))


def test_changed_content_adds_version_without_activating() -> None:
    (item,) = build_publish_items(REPO, kinds=("rule",), keys=["contracts"])
    client = FakeClient()
    _run(client, items=[item], scope=LibraryScope.STUDIO, project_id=None, activate=True)
    changed = type(item)(
        item.kind, item.stable_key, item.title, {**item.content, "text": "edited"}, item.pins
    )
    (result,) = _run(client, items=[changed], scope=LibraryScope.STUDIO, project_id=None)
    assert (result.action, result.version, result.activated) == ("new_version", 2, False)
    resource = next(iter(client.resources.values()))
    assert resource.active_version == 1


def test_dry_run_writes_nothing() -> None:
    items = build_publish_items(REPO, kinds=("rule",))
    client = FakeClient()
    results = _run(client, items=items, scope=LibraryScope.STUDIO, project_id=None, dry_run=True)
    assert all(r.action == "created" for r in results)
    assert client.writes == [] and client.resources == {}


def test_missing_dependency_pin_fails_closed() -> None:
    items = build_publish_items(REPO, kinds=("agent",), keys=["studio-tester"])
    client = FakeClient()
    with pytest.raises(PublishError, match="no published version to pin"):
        _run(client, items=items, scope=LibraryScope.STUDIO, project_id=None)
    # The agent is never written: only its own model_profile precedes it in the run.
    assert client.writes == ["create:studio-tester-profile"]
