"""P40 — projections generated from the Library resolution (no DB)."""

from __future__ import annotations

import argparse
import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from studio_client import bootstrap, cli
from studio_client.adapters_check import check_adapters
from studio_client.bootstrap import PlannedFile, plan_files
from studio_client.config import ClientConfig
from studio_client.projection_source import (
    bundle_from_resolved,
    fetch_projection_bundle,
)
from studio_contracts.library import LibraryScope, LibraryStatus
from studio_contracts.resolution import ResolvedAgentDefinition

from tests.library_bundle import PROTOCOL_TEXT, sample_definitions


def _manifest() -> bootstrap.BootstrapManifest:
    return bootstrap.make_manifest("studio-os", "Studio OS", ["claude-code", "codex", "opencode"])


def _by_path(files: list[PlannedFile]) -> dict[str, str]:
    return {item.path: item.content for item in files if not item.block}


def test_resolved_bundle_projects_agents_rules_and_skills(tmp_path: Path) -> None:
    bundle = bundle_from_resolved(sample_definitions())

    assert list(bundle.agents) == sorted(bundle.agents)
    paths = set(_by_path(plan_files(tmp_path, _manifest(), bundle)))
    assert {path for path in paths if path.startswith(".claude/rules/")} == {
        ".claude/rules/contracts.md",
        ".claude/rules/testing.md",
    }
    assert any("/agents/" in path and "/skills/" not in path for path in paths)
    assert ".claude/skills/contract-change/references/notes.md" in paths


def test_plan_is_deterministic_and_never_reads_agents_dir(tmp_path: Path) -> None:
    definitions = sample_definitions()
    manifest = _manifest()
    assert not (tmp_path / ".agents").exists()

    first = plan_files(tmp_path, manifest, bundle_from_resolved(definitions))
    second = plan_files(tmp_path, manifest, bundle_from_resolved(list(reversed(definitions))))

    assert first == second
    assert not (tmp_path / ".agents").exists()


def test_user_scope_resources_are_never_projected() -> None:
    definitions = sample_definitions()
    user_agent = definitions[0].model_copy(
        update={"agent": definitions[0].agent.model_copy(update={"scope": LibraryScope.USER})}
    )
    user_rule = (
        definitions[1]
        .rules[0]
        .model_copy(update={"stable_key": "personal", "scope": LibraryScope.USER})
    )
    mixed = [user_agent, definitions[1].model_copy(update={"rules": [user_rule]}), *definitions[2:]]

    bundle = bundle_from_resolved(mixed)

    assert user_agent.agent.stable_key not in bundle.agents
    assert "personal" not in bundle.rules


def test_rule_without_applies_to_is_global() -> None:
    definition = sample_definitions()[0]
    rule = definition.rules[0]
    content = {k: v for k, v in rule.content.items() if k != "applies_to"}
    bare = definition.model_copy(update={"rules": [rule.model_copy(update={"content": content})]})

    assert bundle_from_resolved([bare]).rules[rule.stable_key][0] == []


def test_adapters_check_passes_on_repo_without_agents_dir(tmp_path: Path) -> None:
    bundle = bundle_from_resolved(sample_definitions())
    manifest = _manifest()
    for item in plan_files(tmp_path, manifest, bundle):
        target = tmp_path / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.content, encoding="utf-8", newline="\n")
    assert not (tmp_path / ".agents").exists()

    result = check_adapters(tmp_path, bundle=bundle)

    assert result.checked > 0
    assert result.failures == ()


def test_adapters_check_reports_drift_without_agents_dir(tmp_path: Path) -> None:
    bundle = bundle_from_resolved(sample_definitions())

    result = check_adapters(tmp_path, bundle=bundle)

    assert result.failures


def test_bundle_rejects_rule_without_text() -> None:
    definition = sample_definitions()[0]
    rule = definition.rules[0].model_copy(update={"content": {}})

    with pytest.raises(ValueError, match="no text content"):
        bundle_from_resolved([definition.model_copy(update={"rules": [rule]})])


def test_rule_v2_content_schema_accepts_applies_to() -> None:
    from studio_contracts.library import LibraryKind, content_validation_errors

    content = {"content_schema": "studio.library.rule/v2", "text": "x", "applies_to": ["a/**"]}
    assert content_validation_errors(LibraryKind.RULE, content) == []
    assert content_validation_errors(LibraryKind.RULE, {**content, "applies_to": "a"})
    v1 = {"content_schema": "studio.library.rule/v1", "text": "x"}
    assert content_validation_errors(LibraryKind.RULE, v1) == []


_CONFIG = ClientConfig(api_base_url="http://127.0.0.1:9")


class _FakeClient:
    def __init__(self, definitions: list[ResolvedAgentDefinition]) -> None:
        self.by_key = {item.agent.stable_key: item for item in definitions}

    async def list_library_resources(self, **kwargs: object) -> list[SimpleNamespace]:
        if kwargs["kind"] == "rule":
            return [
                SimpleNamespace(
                    id=uuid.UUID(int=1),
                    stable_key="studio-protocol",
                    status=LibraryStatus.ACTIVE,
                    scope=LibraryScope.STUDIO,
                    active_version=2,
                )
            ]
        assert kwargs["kind"] == "agent_definition"
        rows = [
            SimpleNamespace(stable_key=key, status=LibraryStatus.ACTIVE, scope=LibraryScope.STUDIO)
            for key in self.by_key
        ]
        rows.append(
            SimpleNamespace(
                stable_key="draft", status=LibraryStatus.DRAFT, scope=LibraryScope.STUDIO
            )
        )
        rows.append(
            SimpleNamespace(stable_key="mine", status=LibraryStatus.ACTIVE, scope=LibraryScope.USER)
        )
        return rows

    async def list_library_versions(self, resource_id: uuid.UUID) -> list[SimpleNamespace]:
        assert resource_id == uuid.UUID(int=1)
        return [
            SimpleNamespace(version=1, content={"text": "old"}),
            SimpleNamespace(version=2, content={"text": PROTOCOL_TEXT}),
        ]

    async def resolve_agent(self, key: str, **_: object) -> ResolvedAgentDefinition:
        return self.by_key[key]


def test_fetch_projection_bundle_resolves_only_active_non_user_agents() -> None:
    definitions = sample_definitions()

    bundle = asyncio.run(fetch_projection_bundle(_FakeClient(definitions), None))

    assert set(bundle.agents) == {item.agent.stable_key for item in definitions}


def test_fetch_projection_bundle_loads_the_studio_protocol_rule() -> None:
    bundle = asyncio.run(fetch_projection_bundle(_FakeClient(sample_definitions()), None))

    assert bundle.protocol == PROTOCOL_TEXT


def _args(root: Path, **extra: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "repo_root": str(root),
        "project_id": str(uuid.uuid4()),
        "yes": True,
        "overwrite": [],
        "wire_mcp": False,
        "json": False,
        "registry_dir": str(root / "registry"),
    }
    return argparse.Namespace(**{**values, **extra})


def test_cli_sync_from_library_writes_without_agents_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definitions = sample_definitions()

    monkeypatch.setattr(
        cli, "_run", lambda _config, action: asyncio.run(action(_FakeClient(definitions)))
    )

    cli._bootstrap_sync(_args(tmp_path), _CONFIG)

    assert not (tmp_path / ".agents").exists()
    assert (tmp_path / ".claude" / "agents").is_dir()
    cli._bootstrap_report(_args(tmp_path), _CONFIG, emit_diff=False)


def test_cli_projection_commands_require_project_id() -> None:
    for command in ("check", "diff", "sync"):
        with pytest.raises(SystemExit):
            cli._build_parser().parse_args(["bootstrap", command])
