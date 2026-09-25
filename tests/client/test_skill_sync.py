from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from studio_client import cli
from studio_client.context.library import LibraryContextItem
from studio_client.skill_sync import (
    SkillSyncConflictError,
    SkillSyncError,
    apply_skill_sync,
    diff_skill_plan,
    fetch_skill_projections,
    plan_skill_sync,
    render_skill,
)


@dataclass
class _Resource:
    id: UUID
    stable_key: str
    scope: str
    project_id: UUID | None = None
    kind: str = "skill"
    status: str = "active"
    active_version: int = 1


@dataclass
class _Version:
    resource_id: UUID
    version: int
    title: str
    text: str

    @property
    def content(self) -> dict[str, str]:
        return {
            "content_schema": "studio.library.skill/v1",
            "text": self.text,
        }


class _FakeApi:
    def __init__(self, resources: list[_Resource], versions: list[_Version]) -> None:
        self.resources = resources
        self.versions = versions
        self.calls: list[tuple[str, Any]] = []

    async def list_library_resources(self, *, limit: int) -> list[_Resource]:
        self.calls.append(("resources", limit))
        return self.resources[:limit]

    async def list_library_locks(self, *, project_id: UUID | None) -> list[Any]:
        self.calls.append(("locks", project_id))
        return []

    async def list_library_versions(self, resource_id: UUID) -> list[_Version]:
        self.calls.append(("versions", resource_id))
        return [row for row in self.versions if row.resource_id == resource_id]


def _projection(
    stable_key: str = "studio-git-flow",
    *,
    text: str = "# Git flow\n\nUse task branches.",
    scope: str = "studio",
) -> LibraryContextItem:
    return LibraryContextItem(
        library_kind="skill",
        stable_key=stable_key,
        version=3,
        version_origin="active",
        scope=scope,
        title="Studio Git Flow",
        text=text,
        content_schema="studio.library.skill/v1",
    )


def _target(home: Path, harness: str, key: str = "studio-git-flow") -> Path:
    return home / f".{harness}" / "skills" / key / "SKILL.md"


@pytest.mark.asyncio
async def test_fetch_uses_effective_library_selection_and_keeps_only_studio_scope() -> None:
    project_id = uuid4()
    retained = _Resource(uuid4(), "retained", "studio")
    shadowed = _Resource(uuid4(), "shadowed", "studio")
    project_override = _Resource(uuid4(), "shadowed", "project", project_id)
    project_only = _Resource(uuid4(), "project-only", "project", project_id)
    resources = [project_only, shadowed, retained, project_override]
    versions = [
        _Version(resource.id, 1, resource.stable_key, f"body:{resource.scope}")
        for resource in resources
    ]
    api = _FakeApi(resources, versions)

    result = await fetch_skill_projections(api, project_id, limit=12)

    assert [item.stable_key for item in result] == ["retained"]
    assert api.calls[0] == ("resources", 12)
    assert ("locks", project_id) in api.calls


@pytest.mark.asyncio
async def test_global_fetch_never_applies_project_locks() -> None:
    resource = _Resource(uuid4(), "studio-git-flow", "studio")
    api = _FakeApi([resource], [_Version(resource.id, 1, resource.stable_key, "body")])

    result = await fetch_skill_projections(api, None)

    assert [item.stable_key for item in result] == ["studio-git-flow"]
    assert not any(call[0] == "locks" for call in api.calls)


def test_render_has_compatible_frontmatter_and_provenance() -> None:
    rendered = render_skill(_projection(text="Body with CRLF.\r\n"))

    assert rendered.startswith(
        '---\nname: "studio-git-flow"\ndescription: "Studio Git Flow"\n---\n'
    )
    assert "version=3; version_origin=active; scope=studio" in rendered
    assert rendered.endswith("Body with CRLF.\n")
    assert "\r" not in rendered


def test_plan_distinguishes_current_missing_and_drifted(tmp_path: Path) -> None:
    first = _projection()
    second = _projection("release-skill", text="Release safely.")
    _target(tmp_path, "agents").parent.mkdir(parents=True)
    _target(tmp_path, "agents").write_text(render_skill(first), encoding="utf-8")
    _target(tmp_path, "claude").parent.mkdir(parents=True)
    _target(tmp_path, "claude").write_text("local edits\n", encoding="utf-8")

    plan = plan_skill_sync(tmp_path, [second, first])

    assert [entry.projection.stable_key for entry in plan.entries] == [
        "release-skill",
        "studio-git-flow",
    ]
    assert [target.harness for target in plan.current] == ["agents"]
    assert [target.harness for target in plan.drifted] == ["claude"]
    assert len(plan.missing) == 2


def test_apply_refuses_drift_without_overwrite_and_changes_nothing(tmp_path: Path) -> None:
    agents = _target(tmp_path, "agents")
    agents.parent.mkdir(parents=True)
    agents.write_text("keep me\n", encoding="utf-8")
    plan = plan_skill_sync(tmp_path, [_projection()])

    with pytest.raises(SkillSyncConflictError, match="overwrite=True"):
        apply_skill_sync(plan)

    assert agents.read_text(encoding="utf-8") == "keep me\n"
    assert not _target(tmp_path, "claude").exists()
    assert not plan.manifest_path.exists()


def test_apply_overwrite_backs_up_both_harnesses_and_writes_manifest(
    tmp_path: Path,
) -> None:
    agents = _target(tmp_path, "agents")
    claude = _target(tmp_path, "claude")
    for path, content in ((agents, "agents local\n"), (claude, "claude local\n")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    projection = _projection()
    plan = plan_skill_sync(tmp_path, [projection])

    result = apply_skill_sync(plan, overwrite=True)

    desired = render_skill(projection)
    assert agents.read_text(encoding="utf-8") == desired
    assert claude.read_text(encoding="utf-8") == desired
    assert len(result.backups) == 2
    backup_root = result.backups[0].parents[1]
    assert (backup_root / "studio-git-flow" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "agents local\n"
    assert (backup_root / "studio-git-flow" / "claude" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "claude local\n"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest == {
        "schema_version": 1,
        "skills": [
            {
                "scope": "studio",
                "sha256": plan.entries[0].sha256,
                "stable_key": "studio-git-flow",
                "version": 3,
                "version_origin": "active",
            }
        ],
    }


def test_managed_outdated_skill_updates_without_overwrite(tmp_path: Path) -> None:
    initial = _projection(text="version 2")
    apply_skill_sync(plan_skill_sync(tmp_path, [initial]))

    updated = _projection(text="version 3")
    plan = plan_skill_sync(tmp_path, [updated])

    assert len(plan.outdated) == 2
    assert not plan.locally_modified
    result = apply_skill_sync(plan)
    assert len(result.written) == 2
    assert not result.backups


@pytest.mark.parametrize(
    "stable_key",
    [
        "../escape",
        "nested/escape",
        r"nested\escape",
        "..",
        "skill..backup",
        "con",
        "nul.txt",
        "trailing.",
    ],
)
def test_traversal_and_ambiguous_stable_keys_are_rejected(
    tmp_path: Path,
    stable_key: str,
) -> None:
    with pytest.raises(SkillSyncError, match="unsafe skill stable_key"):
        plan_skill_sync(tmp_path, [_projection(stable_key)])


def test_non_studio_projection_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SkillSyncError, match="non-studio"):
        plan_skill_sync(tmp_path, [_projection(scope="project")])


def test_diff_is_deterministic_for_missing_and_drifted_targets(tmp_path: Path) -> None:
    claude = _target(tmp_path, "claude")
    claude.parent.mkdir(parents=True)
    claude.write_text("old\n", encoding="utf-8")
    plan = plan_skill_sync(tmp_path, [_projection(text="new")])

    first = diff_skill_plan(plan)
    second = diff_skill_plan(plan)

    assert first == second
    assert "--- /dev/null" in first
    assert "--- .claude/skills/studio-git-flow/SKILL.md" in first
    assert "+new\n" in first
    assert "-old\n" in first


def test_apply_rejects_a_target_changed_after_planning(tmp_path: Path) -> None:
    plan = plan_skill_sync(tmp_path, [_projection()])
    agents = _target(tmp_path, "agents")
    agents.parent.mkdir(parents=True)
    agents.write_text("appeared later\n", encoding="utf-8")

    with pytest.raises(SkillSyncConflictError, match="changed since planning"):
        apply_skill_sync(plan)


def test_apply_never_deletes_unmanaged_skills(tmp_path: Path) -> None:
    unmanaged = _target(tmp_path, "agents", "unmanaged")
    unmanaged.parent.mkdir(parents=True)
    unmanaged.write_text("keep\n", encoding="utf-8")

    apply_skill_sync(plan_skill_sync(tmp_path, [_projection()]))

    assert unmanaged.read_text(encoding="utf-8") == "keep\n"


def test_cli_check_is_read_only_and_nonzero_when_projection_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_load_config", lambda: object())
    monkeypatch.setattr(cli, "_run", lambda _config, _action: (_projection(),))

    with pytest.raises(SystemExit, match="1"):
        cli.main(["skills", "check", "--home", str(tmp_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["failures"] == 2
    assert not (tmp_path / ".agents").exists()
    assert not (tmp_path / ".claude").exists()


def test_cli_sync_overwrite_backs_up_existing_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    existing = _target(tmp_path, "agents")
    existing.parent.mkdir(parents=True)
    existing.write_text("legacy\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_load_config", lambda: object())
    monkeypatch.setattr(cli, "_run", lambda _config, _action: (_projection(),))

    cli.main(["skills", "sync", "--home", str(tmp_path), "--overwrite", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert len(payload["written"]) == 2
    assert len(payload["backups"]) == 1
    assert existing.read_text(encoding="utf-8") == render_skill(_projection())
