"""P40 — projections generated from the Library resolution, not `.agents/` (no DB)."""

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
from studio_client.canonical import build_offline_resolved, canonical_agent_keys, load_rule_meta
from studio_client.config import ClientConfig
from studio_client.projection_source import (
    ProjectionBundle,
    bundle_from_repo,
    bundle_from_resolved,
    fetch_projection_bundle,
)
from studio_contracts.library import LibraryScope, LibraryStatus
from studio_contracts.resolution import ResolvedAgentDefinition

REPO = Path(__file__).resolve().parents[2]


def _manifest() -> bootstrap.BootstrapManifest:
    return bootstrap.make_manifest("studio-os", "Studio OS", ["claude-code", "codex", "opencode"])


def _as_library(repo_bundle: ProjectionBundle) -> list[ResolvedAgentDefinition]:
    definitions = []
    for resolved in repo_bundle.agents.values():
        rules = []
        for rule in resolved.rules:
            applies_to, _ = repo_bundle.rules[rule.stable_key]
            content = {**rule.content, "content_schema": "studio.library.rule/v2"}
            rules.append(rule.model_copy(update={"content": {**content, "applies_to": applies_to}}))
        definitions.append(resolved.model_copy(update={"rules": rules}))
    return definitions


def _by_path(files: list[PlannedFile]) -> dict[str, str]:
    return {item.path: item.content for item in files if not item.block}


def test_resolved_bundle_matches_repo_projections() -> None:
    repo_bundle = bundle_from_repo(REPO)
    from_library = bundle_from_resolved(_as_library(repo_bundle))

    assert list(from_library.agents) == sorted(repo_bundle.agents)
    manifest = _manifest()
    expected = _by_path(plan_files(REPO, manifest, repo_bundle))
    actual = _by_path(plan_files(REPO, manifest, from_library))
    agent_paths = {path for path in expected if "/agents/" in path and "/skills/" not in path}
    rule_paths = {path for path in expected if path.startswith(".claude/rules/")}
    assert agent_paths and rule_paths
    assert {path: actual[path] for path in agent_paths | rule_paths} == {
        path: expected[path] for path in agent_paths | rule_paths
    }


def test_plan_is_deterministic_and_never_reads_agents_dir(tmp_path: Path) -> None:
    definitions = _as_library(bundle_from_repo(REPO))
    manifest = _manifest()
    assert not (tmp_path / ".agents").exists()

    first = plan_files(tmp_path, manifest, bundle_from_resolved(definitions))
    second = plan_files(tmp_path, manifest, bundle_from_resolved(list(reversed(definitions))))

    assert first == second
    assert not (tmp_path / ".agents").exists()


def test_user_scope_resources_are_never_projected() -> None:
    definitions = _as_library(bundle_from_repo(REPO))
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
    definition = _as_library(bundle_from_repo(REPO))[0]
    rule = definition.rules[0]
    content = {k: v for k, v in rule.content.items() if k != "applies_to"}
    bare = definition.model_copy(update={"rules": [rule.model_copy(update={"content": content})]})

    assert bundle_from_resolved([bare]).rules[rule.stable_key][0] == []


def test_adapters_check_passes_on_repo_without_agents_dir(tmp_path: Path) -> None:
    bundle = bundle_from_resolved(_as_library(bundle_from_repo(REPO)))
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
    bundle = bundle_from_resolved(_as_library(bundle_from_repo(REPO)))

    result = check_adapters(tmp_path, bundle=bundle)

    assert result.failures


def test_repo_bundle_is_unchanged_default() -> None:
    manifest = _manifest()
    assert plan_files(REPO, manifest) == plan_files(REPO, manifest, bundle_from_repo(REPO))
    key = canonical_agent_keys(REPO)[0]
    assert bundle_from_repo(REPO).agents[key] == build_offline_resolved(REPO, key)
    assert bundle_from_repo(REPO).rules
    assert load_rule_meta(REPO, next(iter(bundle_from_repo(REPO).rules)))


def test_bundle_rejects_rule_without_text() -> None:
    definition = _as_library(bundle_from_repo(REPO))[0]
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

    async def resolve_agent(self, key: str, **_: object) -> ResolvedAgentDefinition:
        return self.by_key[key]


def test_fetch_projection_bundle_resolves_only_active_non_user_agents() -> None:
    definitions = _as_library(bundle_from_repo(REPO))

    bundle = asyncio.run(fetch_projection_bundle(_FakeClient(definitions), None))

    assert set(bundle.agents) == {item.agent.stable_key for item in definitions}


def _args(root: Path, **extra: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "repo_root": str(root),
        "from_library": True,
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
    definitions = _as_library(bundle_from_repo(REPO))

    monkeypatch.setattr(
        cli, "_run", lambda _config, action: asyncio.run(action(_FakeClient(definitions)))
    )

    cli._bootstrap_sync(_args(tmp_path), _CONFIG)

    assert not (tmp_path / ".agents").exists()
    assert (tmp_path / ".claude" / "agents").is_dir()
    cli._bootstrap_report(_args(tmp_path), _CONFIG, emit_diff=False)


def test_cli_from_library_requires_project_id(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        cli._projection_bundle(_args(tmp_path, project_id=None), _CONFIG)
