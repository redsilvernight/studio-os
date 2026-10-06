"""P3 canonical agents — parser, capabilities, codex, anti-drift (no DB).

Anti-drift core: every managed harness file must equal a fresh offline
export of `.agents/definitions/`. A manual edit (or a canonical change
without regen) fails here exactly as `studio adapters check` fails in CI.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml
from studio_client.adapters import (
    CAPABILITY_DIMENSIONS,
    AdapterError,
    AdapterErrorCode,
    AdapterResult,
    CapabilitySupport,
    get_adapter,
    list_adapters,
)
from studio_client.adapters.base import AdapterArtifact
from studio_client.canonical import (
    LibrarySnapshot,
    build_merged_resolved,
    build_offline_resolved,
    canonical_agent_keys,
    canonical_rule_keys,
    load_definition,
    load_rule_meta,
    render_agents_rules_block,
    render_claude_rule,
    to_publish_payload,
)
from studio_contracts.library import VersionOrigin
from studio_contracts.resolution import ResolvedAgentDefinition

REPO = Path(__file__).resolve().parents[2]
KEYS = ("studio-architect", "studio-tester", "contract-guardian", "sync-debugger")
FORBIDDEN = ("opus", "sonnet", "gpt-", "kimi", "anthropic", "openai", "claude-code")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_canonical_definitions_exist_and_parse() -> None:
    assert canonical_agent_keys(REPO) == sorted(KEYS)
    for key in KEYS:
        agent = load_definition(REPO, key)
        assert agent.stable_key == key
        assert agent.summary and agent.instructions and agent.triggers
        assert agent.edit_policy == "deny"
        assert agent.rules and agent.skills


def test_canonical_definitions_name_no_model_or_harness() -> None:
    for key in KEYS:
        text = (REPO / ".agents" / "definitions" / f"{key}.md").read_text(encoding="utf-8").lower()
        for token in FORBIDDEN:
            assert token not in text, f"{key} leaks {token!r}"


def test_offline_build_deterministic_and_publishable() -> None:
    first = build_offline_resolved(REPO, "studio-tester")
    second = build_offline_resolved(REPO, "studio-tester")
    assert first == second
    assert first.agent.version == 1
    assert first.agent.version_origin == VersionOrigin.ACTIVE
    assert {r.stable_key for r in first.rules} == {
        "contracts",
        "python-conventions",
        "offline-sync",
        "storage-transfers",
    }
    content, pins = to_publish_payload(load_definition(REPO, "studio-tester"))
    assert content["content_schema"] == "studio.library.agent_definition/v1"
    assert "instructions" not in content  # Library forbids file-only keys
    assert ("rule", "contracts") in pins and ("skill", "graphify") in pins


def test_capabilities_cover_all_dimensions() -> None:
    for adapter_id in ("claude-code", "opencode", "codex"):
        caps = get_adapter(adapter_id).capabilities()
        assert set(caps) == set(CAPABILITY_DIMENSIONS)
        assert all(isinstance(v, CapabilitySupport) for v in caps.values())
    assert get_adapter("claude-code").capabilities()["permissions"] == CapabilitySupport.SUPPORTED
    assert get_adapter("opencode").capabilities()["permissions"] == CapabilitySupport.DEGRADED
    assert get_adapter("codex").capabilities()["permissions"] == CapabilitySupport.DEGRADED


def test_codex_projection_shape() -> None:
    resolved = build_offline_resolved(REPO, "studio-architect")
    result = get_adapter("codex").translate(resolved)
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.path == ".codex/agents/studio-architect.toml"
    assert 'name = "studio-architect"' in artifact.content
    assert "model_reasoning_effort = 'high'" in artifact.content
    assert "developer_instructions = '''" in artifact.content
    assert "You are the architecture specialist" in artifact.content
    assert "\nmodel = " not in artifact.content  # no runtime binding configured


def test_fake_third_party_adapter_needs_no_core_change() -> None:
    """P3.10: a new harness registers against the open registry, receives the
    canonical definition, and projects it — Library, Resolution, contracts
    and skills untouched."""

    from studio_client.adapters import register_adapter

    seen: dict[str, Any] = {}

    class TestHarnessAdapter:
        adapter_id = "test-harness"
        managed_dir = ".test/agents"

        def capabilities(self) -> dict[str, CapabilitySupport]:
            return dict.fromkeys(CAPABILITY_DIMENSIONS, CapabilitySupport.SUPPORTED)

        def translate(self, resolved: ResolvedAgentDefinition, *, context=None) -> AdapterResult:
            seen["key"] = resolved.agent.stable_key
            return AdapterResult(
                adapter_id=self.adapter_id,
                artifacts=(
                    AdapterArtifact(
                        path=f"{self.managed_dir}/{resolved.agent.stable_key}.test",
                        content=f"agent={resolved.agent.stable_key}\nrules={len(resolved.rules)}\n",
                    ),
                ),
            )

    register_adapter(TestHarnessAdapter())  # type: ignore[arg-type]
    try:
        assert "test-harness" in list_adapters()
        resolved = build_offline_resolved(REPO, "sync-debugger")
        result = get_adapter("test-harness").translate(resolved)
        assert seen["key"] == "sync-debugger"
        assert "rules=3" in result.artifacts[0].content
    finally:
        from studio_client.adapters.base import _REGISTRY

        _REGISTRY.pop("test-harness", None)


def test_unsupported_capability_fails_explicit() -> None:
    from studio_client.adapters import register_adapter
    from studio_client.adapters.base import _REGISTRY

    class NoPermissionsAdapter:
        adapter_id = "no-perms"
        managed_dir = ".noperms"

        def capabilities(self) -> dict[str, CapabilitySupport]:
            caps = dict.fromkeys(CAPABILITY_DIMENSIONS, CapabilitySupport.SUPPORTED)
            caps["permissions"] = CapabilitySupport.UNSUPPORTED
            return caps

        def translate(self, resolved: ResolvedAgentDefinition, *, context=None) -> AdapterResult:
            from studio_client.adapters.base import ensure_supported

            ensure_supported(
                self.adapter_id,
                self.capabilities(),
                edit_policy=resolved.agent.content.get("edit_policy"),  # type: ignore[arg-type]
            )
            raise AssertionError("must not reach projection")

    register_adapter(NoPermissionsAdapter())  # type: ignore[arg-type]
    try:
        with pytest.raises(AdapterError) as exc_info:
            get_adapter("no-perms").translate(build_offline_resolved(REPO, "studio-tester"))
        assert exc_info.value.code == AdapterErrorCode.UNSUPPORTED
    finally:
        _REGISTRY.pop("no-perms", None)


def test_anti_drift_all_managed_files() -> None:
    """Every generated artifact equals a fresh offline export. Edit the
    canonical source and re-export — never the artifact."""
    drifted: list[str] = []
    for adapter_id in ("claude-code", "opencode", "codex"):
        adapter = get_adapter(adapter_id)
        for key in KEYS:
            for artifact in adapter.translate(build_offline_resolved(REPO, key)).artifacts:
                if _read(REPO / artifact.path) != artifact.content:
                    drifted.append(artifact.path)
    for key in canonical_rule_keys(REPO):
        applies_to, body = load_rule_meta(REPO, key)
        if _read(REPO / ".claude" / "rules" / f"{key}.md") != render_claude_rule(
            key, applies_to, body
        ):
            drifted.append(f".claude/rules/{key}.md")
    assert render_agents_rules_block(REPO).rstrip("\n") in _read(REPO / "AGENTS.md")
    assert drifted == []


def test_rule_frontmatter_neutral() -> None:
    for key in canonical_rule_keys(REPO):
        raw = (REPO / ".agents" / "rules" / f"{key}.md").read_text(encoding="utf-8")
        data = yaml.safe_load(raw.split("---\n", 2)[1])
        assert "paths" not in data  # harness envelope lives in the projection
        assert isinstance(data.get("applies_to"), list)


def _write_definition(
    root: Path, key: str, *, rules: tuple[str, ...], skills: tuple[str, ...]
) -> None:
    definitions = root / ".agents" / "definitions"
    definitions.mkdir(parents=True)
    definitions.joinpath(f"{key}.md").write_text(
        "---\n"
        f"stable_key: {key}\n"
        "title: T\n"
        "summary: S\n"
        "intended_use: U\n"
        f"rules: [{', '.join(rules)}]\n"
        f"skills: [{', '.join(skills)}]\n"
        "---\n"
        "Body.\n",
        encoding="utf-8",
    )


def test_merged_without_library_matches_offline() -> None:
    for key in KEYS:
        assert build_merged_resolved(REPO, key) == build_offline_resolved(REPO, key)


def test_merged_roundtrip_through_snapshot() -> None:
    """`from_resolved` + merge over a complete repo changes nothing: every
    piece resolves file-backed, with the file identity namespace."""
    offline = build_offline_resolved(REPO, "studio-tester")
    snapshot = LibrarySnapshot.from_resolved(offline)
    assert build_merged_resolved(REPO, "studio-tester", library=snapshot) == offline


def test_merged_project_file_wins_over_library() -> None:
    offline = build_offline_resolved(REPO, "studio-tester")
    snapshot = LibrarySnapshot.from_resolved(offline)
    poisoned_rule = snapshot.rules["contracts"].model_copy(
        update={
            "resource_id": uuid.uuid4(),
            "version": 99,
            "content": {"content_schema": "studio.library.rule/v1", "text": "POISON"},
        }
    )
    poisoned = LibrarySnapshot(
        agent=snapshot.agent,
        rules={**snapshot.rules, "contracts": poisoned_rule},
        skills=snapshot.skills,
        requirements=snapshot.requirements,
    )
    merged = build_merged_resolved(REPO, "studio-tester", library=poisoned)
    by_key = {rule.stable_key: rule for rule in merged.rules}
    assert by_key["contracts"].content["text"] != "POISON"
    assert by_key["contracts"].version == 1  # file namespace, not Library 99


def test_merged_library_fills_missing_project_files(tmp_path: Path) -> None:
    _write_definition(tmp_path, "x-agent", rules=("x-rule",), skills=())
    offline = build_offline_resolved(REPO, "studio-tester")
    snapshot = LibrarySnapshot.from_resolved(offline)
    library_rule = snapshot.rules["contracts"]
    library_only = LibrarySnapshot(
        agent=snapshot.agent.model_copy(update={"stable_key": "x-agent"}),
        rules={"x-rule": library_rule.model_copy(update={"stable_key": "x-rule"})},
        skills={},
        requirements=snapshot.requirements,
    )
    merged = build_merged_resolved(tmp_path, "x-agent", library=library_only)
    assert [rule.stable_key for rule in merged.rules] == ["x-rule"]
    assert merged.rules[0].resource_id == library_rule.resource_id
    assert merged.rules[0].version == library_rule.version
    assert merged.agent.content["instructions"] == "Body.\n"  # file head wins


def test_merged_no_project_files_uses_library_head(tmp_path: Path) -> None:
    """Near-empty repo: no `.agents/` at all — the Library snapshot
    supplies the head (with defaulted file-only keys) and the pieces."""
    offline = build_offline_resolved(REPO, "studio-tester")
    snapshot = LibrarySnapshot.from_resolved(offline)
    library_rule = snapshot.rules["contracts"].model_copy(update={"stable_key": "x-rule"})
    library_only = LibrarySnapshot(
        agent=snapshot.agent.model_copy(update={"stable_key": "x-agent"}),
        rules={"x-rule": library_rule},
        skills={},
        requirements=snapshot.requirements,
    )
    merged = build_merged_resolved(tmp_path, "x-agent", library=library_only)
    assert merged.agent.resource_id == library_only.agent.resource_id
    assert merged.agent.content["instructions"] == ""  # Library never carries file-only keys
    assert merged.agent.content["edit_policy"] == "deny"
    assert [rule.stable_key for rule in merged.rules] == ["x-rule"]


def test_merged_missing_everywhere_raises(tmp_path: Path) -> None:
    _write_definition(tmp_path, "x-agent", rules=("ghost-rule",), skills=())
    offline = build_offline_resolved(REPO, "studio-tester")
    snapshot = LibrarySnapshot.from_resolved(offline)
    agent_only = LibrarySnapshot(
        agent=snapshot.agent.model_copy(update={"stable_key": "x-agent"}),
        rules={},
        skills={},
        requirements=snapshot.requirements,
    )
    with pytest.raises(FileNotFoundError):
        build_merged_resolved(tmp_path, "x-agent", library=agent_only)
    with pytest.raises(ValueError):
        build_merged_resolved(tmp_path, "other-agent", library=agent_only)


def test_snapshot_rejects_textless_entry() -> None:
    offline = build_offline_resolved(REPO, "studio-tester")
    broken_rule = offline.rules[0].model_copy(update={"content": {}})
    with pytest.raises(ValueError):
        LibrarySnapshot.from_resolved(
            offline.model_copy(update={"rules": [broken_rule, *offline.rules[1:]]})
        )


def test_merged_corrupt_project_file_never_falls_back(tmp_path: Path) -> None:
    definitions = tmp_path / ".agents" / "definitions"
    definitions.mkdir(parents=True)
    definitions.joinpath("x-agent.md").write_text("no frontmatter here\n", encoding="utf-8")
    snapshot = LibrarySnapshot.from_resolved(build_offline_resolved(REPO, "studio-tester"))
    with pytest.raises(ValueError):
        build_merged_resolved(tmp_path, "x-agent", library=snapshot)
