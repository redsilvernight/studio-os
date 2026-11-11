"""P43: `build_publish_items` imports `.agents/` without loss.

Built on the repository's real canonical files: every produced content passes
the server-side schema checks (`content_validation_errors`), every canonical
field survives the import (rule `applies_to`, skill `references/**` files,
agent instructions/triggers/edit_policy/tools, `requirements` as a
`model_profile` published before its agent), and republishing identical content
creates no version.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest
from studio_client.canonical import (
    canonical_agent_keys,
    canonical_rule_keys,
    canonical_skill_keys,
    load_definition,
    load_rule_meta,
    load_skill_files,
    load_skill_text,
    model_profile_key,
)
from studio_client.publish import PublishItem, build_publish_items, publish_items
from studio_contracts.library import (
    SKILL_FILE_TEXT_MAX_LENGTH,
    SKILL_FILES_MAX,
    SKILL_FILES_TOTAL_MAX_LENGTH,
    CapabilityRequirement,
    LibraryKind,
    LibraryScope,
    content_validation_errors,
)

from tests.client.test_library_publish import FakeClient

REPO = Path(__file__).resolve().parents[2]

_LIBRARY_KIND: dict[str, LibraryKind] = {
    "rule": LibraryKind.RULE,
    "skill": LibraryKind.SKILL,
    "model_profile": LibraryKind.MODEL_PROFILE,
    "agent": LibraryKind.AGENT_DEFINITION,
}


def _items() -> list[PublishItem]:
    return build_publish_items(REPO)


def test_every_item_content_validates_and_is_unique() -> None:
    items = _items()
    assert {item.kind for item in items} == set(_LIBRARY_KIND)
    assert len({(item.kind, item.stable_key) for item in items}) == len(items)
    for item in items:
        errors = content_validation_errors(_LIBRARY_KIND[item.kind], item.content)
        assert errors == [], f"{item.kind} {item.stable_key}: {errors}"
        assert item.title.strip(), f"{item.kind} {item.stable_key}: empty title"


def test_rules_keep_applies_to_and_body() -> None:
    items = {item.stable_key: item for item in _items() if item.kind == "rule"}
    assert set(items) == set(canonical_rule_keys(REPO))
    for key, item in items.items():
        applies_to, body = load_rule_meta(REPO, key)
        assert item.content == {
            "content_schema": "studio.library.rule/v2",
            "text": body,
            "applies_to": applies_to,
        }


def test_skills_keep_body_and_reference_files() -> None:
    items = {item.stable_key: item for item in _items() if item.kind == "skill"}
    assert set(items) == set(canonical_skill_keys(REPO))
    multi_file = {key for key, item in items.items() if item.content.get("files")}
    assert multi_file == {"graphify", "studio-task"}
    for key, item in items.items():
        assert item.content["content_schema"] == "studio.library.skill/v2"
        assert item.content["text"] == load_skill_text(REPO, key)
        expected = load_skill_files(REPO, key)
        if not expected:
            assert "files" not in item.content
            continue
        files = item.content["files"]
        assert isinstance(files, list)
        assert [file["path"] for file in files] == sorted(file["path"] for file in files)
        assert [file["path"] for file in files] == [file["path"] for file in expected]
        assert [(file["text"], file["sha256"]) for file in files] == [
            (file["text"], file["sha256"]) for file in expected
        ]
        for file in files:
            assert file["sha256"] == hashlib.sha256(file["text"].encode("utf-8")).hexdigest()
            assert file["path"].startswith("references/")
            assert (REPO / ".agents/skills" / key / file["path"]).is_file()


def test_agents_keep_every_canonical_field() -> None:
    items = {item.stable_key: item for item in _items() if item.kind == "agent"}
    assert set(items) == set(canonical_agent_keys(REPO))
    for key, item in items.items():
        agent = load_definition(REPO, key)
        assert set(item.content) == {
            "content_schema",
            "summary",
            "intended_use",
            "instructions",
            "triggers",
            "edit_policy",
            "tools",
        }
        assert item.content["content_schema"] == "studio.library.agent_definition/v2"
        assert item.content["summary"] == agent.summary
        assert item.content["intended_use"] == agent.intended_use
        assert item.content["instructions"] == agent.instructions
        assert item.content["triggers"] == list(agent.triggers)
        assert item.content["edit_policy"] == agent.edit_policy
        assert item.content["tools"] == list(agent.tools)
        # The Markdown body is the instructions, never the intended use.
        assert item.content["instructions"].strip() != item.content["intended_use"].strip()
        assert item.title == agent.title


def test_agent_requirements_become_a_pinned_model_profile_published_first() -> None:
    items = _items()
    profiles = {item.stable_key: item for item in items if item.kind == "model_profile"}
    agents = {item.stable_key: item for item in items if item.kind == "agent"}
    keys = [item.stable_key for item in items]
    expected = {model_profile_key(key) for key in agents}
    assert set(profiles) == expected
    for key, item in agents.items():
        agent = load_definition(REPO, key)
        profile_key = model_profile_key(key)
        assert ("model_profile", profile_key) in item.pins
        assert agent.requirements, f"{key}: profile published without requirements"
        profile = profiles[profile_key]
        assert profile.content["content_schema"] == "studio.library.model_profile/v1"
        assert profile.content["requirements"] == CapabilityRequirement.model_validate(
            agent.requirements
        ).model_dump(mode="json", exclude_none=True)
        assert keys.index(profile_key) < keys.index(key)


def test_republishing_identical_content_creates_no_version() -> None:
    client = FakeClient()

    asyncio.run(
        publish_items(
            client,  # type: ignore[arg-type]
            _items(),
            scope=LibraryScope.STUDIO,
            project_id=None,
            activate=True,
        )
    )
    assert len(client.resources) == len({(i.kind, i.stable_key) for i in _items()})
    writes = len(client.writes)
    versions = {resource_id: len(rows) for resource_id, rows in client.versions.items()}
    assert all(count == 1 for count in versions.values())

    second = asyncio.run(
        publish_items(
            client,  # type: ignore[arg-type]
            _items(),
            scope=LibraryScope.STUDIO,
            project_id=None,
            activate=True,
        )
    )
    assert {result.action for result in second} == {"unchanged"}
    assert all(result.version == 1 for result in second)
    assert len(client.writes) == writes
    assert {resource_id: len(rows) for resource_id, rows in client.versions.items()} == versions


@pytest.mark.parametrize("key", canonical_skill_keys(REPO))
def test_skill_files_respect_the_contract_budget(key: str) -> None:
    files = load_skill_files(REPO, key)
    assert len(files) <= SKILL_FILES_MAX
    assert all(len(file["text"]) <= SKILL_FILE_TEXT_MAX_LENGTH for file in files)
    assert sum(len(file["text"]) for file in files) <= SKILL_FILES_TOTAL_MAX_LENGTH


def test_skills_publish_disable_model_invocation_flag() -> None:
    """`skill/v2` carries the frontmatter `disable-model-invocation` flag:
    true for `alembic-migration`, false everywhere else."""

    from studio_client.canonical import load_skill_disable_model_invocation

    items = {item.stable_key: item for item in _items() if item.kind == "skill"}
    for key, item in items.items():
        assert item.content["disable_model_invocation"] is (
            load_skill_disable_model_invocation(REPO, key)
        )
    assert items["alembic-migration"].content["disable_model_invocation"] is True
    others = {key for key in items if key != "alembic-migration"}
    assert others, "expected other skills besides alembic-migration"
    assert all(items[key].content["disable_model_invocation"] is False for key in others)


def test_non_boolean_disable_model_invocation_fails_closed(tmp_path: Path) -> None:
    skill = tmp_path / ".agents" / "skills" / "flagged"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: flagged\ndescription: Flagged skill\n"
        "disable-model-invocation: 'true'\n---\n\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="disable-model-invocation must be a boolean"):
        build_publish_items(tmp_path, kinds=("skill",))
