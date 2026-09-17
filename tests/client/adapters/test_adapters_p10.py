"""P10 Adapters — pure local translation tests (no DB, no network, no FS by default).

The central gate: the SAME canonical `ResolvedAgentDefinition` projects to
both Claude Code and OpenCode with differences coming only from the target
format — never from a divergent reading of the canon, never from a
Claude-to-OpenCode derivation."""

from __future__ import annotations

import socket
import uuid
from pathlib import Path

import pytest
from studio_client.adapters import (
    AdapterError,
    AdapterErrorCode,
    AdapterResult,
    get_adapter,
    list_adapters,
    materialize,
    register_adapter,
    sanitize_agent_filename,
)
from studio_client.adapters.base import AdapterArtifact
from studio_contracts.library import (
    BindingRelation,
    CapabilityRequirement,
    LibraryKind,
    LibraryScope,
    VersionOrigin,
)
from studio_contracts.resolution import (
    PreservedReference,
    Provenance,
    ProvenanceSource,
    ResolvedAgent,
    ResolvedAgentDefinition,
    ResolvedModelProfile,
    ResolvedRule,
    ResolvedRuntime,
    ResolvedSkill,
)
from studio_contracts.runtime import RuntimeLevel, RuntimeTarget

AGENT = LibraryKind.AGENT_DEFINITION


def _rid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"studio-os:p10:{name}")


def _prov(key: str = "agent") -> Provenance:
    return Provenance(
        source=ProvenanceSource.ACTIVE_POINTER,
        resource_id=_rid(key),
        stable_key=key,
        scope=LibraryScope.STUDIO,
        version=1,
        version_origin=VersionOrigin.ACTIVE,
    )


def _agent(key: str = "review-helper") -> ResolvedAgent:
    return ResolvedAgent(
        resource_id=_rid(f"agent:{key}"),
        kind=AGENT,
        stable_key=key,
        scope=LibraryScope.STUDIO,
        version=2,
        version_origin=VersionOrigin.ACTIVE,
        title="Review Helper",
        content={
            "content_schema": "studio.library.agent_definition/v1",
            "summary": "Helps review code before human sign-off.",
            "intended_use": "Pre-review triage.",
        },
        provenance=_prov("agent"),
    )


def _rule(key: str, text: str = "Rule text.") -> ResolvedRule:
    return ResolvedRule(
        resource_id=_rid(f"rule:{key}"),
        stable_key=key,
        scope=LibraryScope.STUDIO,
        version=1,
        version_origin=VersionOrigin.ACTIVE,
        title=f"{key} title",
        content={"content_schema": "studio.library.rule/v1", "text": text},
        paths=[],
    )


def _skill(key: str, text: str = "Skill text.") -> ResolvedSkill:
    return ResolvedSkill(
        resource_id=_rid(f"skill:{key}"),
        stable_key=key,
        scope=LibraryScope.STUDIO,
        version=1,
        version_origin=VersionOrigin.ACTIVE,
        title=f"{key} title",
        content={"content_schema": "studio.library.skill/v1", "text": text},
        provenance=_prov(f"skill:{key}"),
    )


def _profile() -> ResolvedModelProfile:
    return ResolvedModelProfile(
        resource_id=_rid("profile:base"),
        stable_key="base-profile",
        scope=LibraryScope.STUDIO,
        version=1,
        version_origin=VersionOrigin.ACTIVE,
        title="Base profile",
        requirements=CapabilityRequirement(
            reasoning="standard", coding=True, tools_required=["read"]
        ),
        provenance=_prov("profile:base"),
    )


def _runtime(harness: str | None = None, *, model: str | None = "model-x") -> ResolvedRuntime:
    return ResolvedRuntime(
        target=RuntimeTarget(harness_ref=harness, provider_ref="provider-a", model_ref=model),
        level=RuntimeLevel.USER,
        matched_kind=AGENT,
        matched_stable_key="review-helper",
    )


def _resolved(harness: str | None = None, **kwargs: object) -> ResolvedAgentDefinition:
    return ResolvedAgentDefinition(
        agent=_agent(),
        rules=[
            _rule("no-direct-push", "Never push to master directly."),
            _rule("small-diffs", "Keep diffs reviewable."),
        ],
        skills=[_skill("diff-reading", "Read diffs hunk by hunk.")],
        model_profile=_profile(),
        requirements=CapabilityRequirement(reasoning="standard", coding=True),
        runtime=None if harness == "none" else _runtime(harness),
    )


def _dump(resolved: ResolvedAgentDefinition) -> str:
    return resolved.model_dump_json()


# --- registry / dispatch ----------------------------------------------------


def test_registry_knows_both_adapters() -> None:
    assert set(list_adapters()) == {"claude-code", "opencode"}


def test_unknown_adapter_is_structured_error() -> None:
    with pytest.raises(AdapterError) as exc_info:
        get_adapter("future-harness")
    assert exc_info.value.code == AdapterErrorCode.UNSUPPORTED
    assert "future-harness" in exc_info.value.message


def test_invalid_canonical_type_is_structured_error() -> None:
    for adapter_id in ("claude-code", "opencode"):
        with pytest.raises(AdapterError) as exc_info:
            get_adapter(adapter_id).translate({"not": "canonical"})  # type: ignore[arg-type]
        assert exc_info.value.code == AdapterErrorCode.INVALID_CANONICAL


# --- Claude Code shape ------------------------------------------------------


def test_claude_code_artifact_shape() -> None:
    result = get_adapter("claude-code").translate(_resolved("claude-code"))
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.path == ".claude/agents/review-helper.md"
    head, _, body = artifact.content.partition("\n\n")
    assert head.startswith("---\n")
    assert 'name: "review-helper"' in head
    assert 'description: "Helps review code before human sign-off."' in head
    assert 'model: "model-x"' in head
    assert "tools:" not in head
    assert "# Review Helper" in body
    assert "Never push to master directly." in body
    assert "Read diffs hunk by hunk." in body
    assert "studio-managed" in body


def test_claude_code_omits_model_without_runtime_model() -> None:
    resolved = _resolved(None)
    resolved.runtime.target.model_ref = None  # type: ignore[union-attr]
    result = get_adapter("claude-code").translate(resolved)
    head = result.artifacts[0].content.split("\n\n", 1)[0]
    assert "\nmodel:" not in head
    assert "model_omitted_no_model_ref" in {w.code for w in result.warnings}


# --- OpenCode shape ---------------------------------------------------------


def test_opencode_artifact_shape() -> None:
    result = get_adapter("opencode").translate(_resolved("opencode"))
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.path == ".opencode/agents/review-helper.md"
    head, _, body = artifact.content.partition("\n\n")
    assert 'description: "Helps review code before human sign-off."' in head
    assert "mode: subagent" in head
    assert 'model: "model-x"' in head
    assert "permission" not in head
    assert "Never push to master directly." in body
    assert "permissions_defaulted" in {w.code for w in result.warnings}


# --- gate multi-harness -----------------------------------------------------


def test_gate_same_definition_two_harnesses() -> None:
    """Same logical definition, two runtime contexts (P10 §38): the
    canonical body sections are identical, only envelopes differ."""
    claude_side = _resolved("claude-code")
    opencode_side = _resolved("opencode")
    assert claude_side.agent == opencode_side.agent
    assert claude_side.rules == opencode_side.rules
    assert claude_side.skills == opencode_side.skills

    claude_result = get_adapter("claude-code").translate(claude_side)
    opencode_result = get_adapter("opencode").translate(opencode_side)

    claude_body = claude_result.artifacts[0].content.split("\n\n", 1)[1]
    opencode_body = opencode_result.artifacts[0].content.split("\n\n", 1)[1]

    def _normalized(body: str) -> str:
        return body.replace("claude-code", "HARNESS").replace("opencode", "HARNESS")

    assert _normalized(claude_body) == _normalized(opencode_body)

    assert claude_result.artifacts[0].path != opencode_result.artifacts[0].path
    assert "name:" in claude_result.artifacts[0].content
    assert "mode: subagent" in opencode_result.artifacts[0].content


def test_gate_harness_neutral_input_translates_to_both() -> None:
    """No `harness_ref` at all: the very same object goes to both."""
    resolved = _resolved(None)
    before = _dump(resolved)
    claude_result = get_adapter("claude-code").translate(resolved)
    opencode_result = get_adapter("opencode").translate(resolved)
    assert _dump(resolved) == before
    for result in (claude_result, opencode_result):
        assert "Helps review code before human sign-off." in result.artifacts[0].content


# --- harness mismatch -------------------------------------------------------


def test_harness_mismatch_is_explicit_never_silent() -> None:
    before = _dump(claude := _resolved("claude-code"))
    with pytest.raises(AdapterError) as exc_info:
        get_adapter("opencode").translate(claude)
    assert exc_info.value.code == AdapterErrorCode.HARNESS_MISMATCH
    assert _dump(claude) == before

    with pytest.raises(AdapterError) as exc_info:
        get_adapter("claude-code").translate(_resolved("opencode"))
    assert exc_info.value.code == AdapterErrorCode.HARNESS_MISMATCH


# --- provider / model independence ------------------------------------------


@pytest.mark.parametrize("provider", ["anthropic", "ollama", "opencode-go", "custom-provider"])
@pytest.mark.parametrize("model", ["claude-opus-x", "opencode-model", "anything"])
def test_no_provider_model_branching(provider: str, model: str) -> None:
    """Provider/model values travel as opaque strings: every combination
    translates under both adapters (with a harness-neutral runtime)."""
    resolved = _resolved(None)
    assert resolved.runtime is not None
    resolved.runtime.target.provider_ref = provider
    resolved.runtime.target.model_ref = model
    for adapter_id in ("claude-code", "opencode"):
        result = get_adapter(adapter_id).translate(resolved)
        assert provider in result.artifacts[0].content
        assert model in result.artifacts[0].content
        assert result.artifacts[0].path.startswith(
            ".claude/agents/" if adapter_id == "claude-code" else ".opencode/agents/"
        )


def test_model_name_never_selects_adapter() -> None:
    """`model_ref` containing 'claude' under the opencode adapter stays
    opencode output — model and harness are different concepts."""
    resolved = _resolved(None)
    assert resolved.runtime is not None
    resolved.runtime.target.model_ref = "claude-flavoured-model"
    result = get_adapter("opencode").translate(resolved)
    assert result.adapter_id == "opencode"
    assert result.artifacts[0].path.startswith(".opencode/agents/")


# --- capabilities are not dispatch ------------------------------------------


def test_requirements_never_become_concrete_model() -> None:
    resolved = _resolved("none")
    resolved.runtime = None
    for adapter_id in ("claude-code", "opencode"):
        result = get_adapter(adapter_id).translate(resolved)
        head = result.artifacts[0].content.split("\n\n", 1)[0]
        assert "\nmodel:" not in head
        assert "no_runtime_target" in {w.code for w in result.warnings}
        assert "reasoning" in result.artifacts[0].content


# --- warnings / lossiness ---------------------------------------------------


def test_workflows_and_composed_agents_warn_not_expand() -> None:
    resolved = _resolved(None)
    resolved.composed_agents.append(
        PreservedReference(
            resource_id=_rid("other-agent"),
            kind=AGENT,
            stable_key="other-agent",
            scope=LibraryScope.STUDIO,
            version=1,
            version_origin=VersionOrigin.ACTIVE,
            relation=BindingRelation.COMPOSES_AGENT,
            provenance=_prov("other-agent"),
        )
    )
    resolved.workflows.append(
        PreservedReference(
            resource_id=_rid("wf"),
            kind=LibraryKind.WORKFLOW,
            stable_key="release-flow",
            scope=LibraryScope.STUDIO,
            version=1,
            version_origin=VersionOrigin.ACTIVE,
            relation=BindingRelation.REFERENCES_WORKFLOW,
            provenance=_prov("wf"),
        )
    )
    for adapter_id in ("claude-code", "opencode"):
        result = get_adapter(adapter_id).translate(resolved)
        codes = {w.code for w in result.warnings}
        assert "composed_agents_not_expanded" in codes
        assert "workflows_not_expanded" in codes


# --- immutability & isolation -----------------------------------------------


def test_failed_translation_leaves_canonical_untouched() -> None:
    resolved = _resolved("claude-code")
    before = _dump(resolved)
    with pytest.raises(AdapterError):
        get_adapter("opencode").translate(resolved)
    assert _dump(resolved) == before


def test_adapter_failure_does_not_contaminate_sibling() -> None:
    claude_side = _resolved("claude-code")
    with pytest.raises(AdapterError):
        get_adapter("opencode").translate(claude_side)
    opencode_side = _resolved("opencode")
    result = get_adapter("opencode").translate(opencode_side)
    assert result.artifacts[0].path == ".opencode/agents/review-helper.md"


def test_determinism_same_input_same_output() -> None:
    resolved = _resolved(None)
    first = get_adapter("claude-code").translate(resolved)
    second = get_adapter("claude-code").translate(resolved)
    assert first.artifacts[0].content == second.artifacts[0].content
    assert first.artifacts[0].sha256 == second.artifacts[0].sha256


def test_rule_order_is_canonical_order() -> None:
    resolved = _resolved(None)
    result = get_adapter("claude-code").translate(resolved)
    body = result.artifacts[0].content
    assert body.index("no-direct-push") < body.index("small-diffs")


# --- offline -----------------------------------------------------------------


def test_translation_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*args: object, **kwargs: object) -> object:
        raise AssertionError("network used during translation")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    resolved = _resolved(None)
    for adapter_id in ("claude-code", "opencode"):
        assert get_adapter(adapter_id).translate(resolved).artifacts


# --- future harness extensibility --------------------------------------------


def test_third_adapter_needs_no_core_change() -> None:
    from studio_client.adapters.base import AdapterArtifact, AdapterResult

    class FutureHarnessAdapter:
        adapter_id = "future-harness"
        managed_dir = ".future/agents"

        def translate(self, resolved: object, *, context: object | None = None) -> AdapterResult:
            assert isinstance(resolved, ResolvedAgentDefinition)
            return AdapterResult(
                adapter_id=self.adapter_id,
                artifacts=(AdapterArtifact(path=f"{self.managed_dir}/x.md", content="x"),),
            )

    register_adapter(FutureHarnessAdapter())  # type: ignore[arg-type]
    try:
        result = get_adapter("future-harness").translate(_resolved(None))
        assert result.artifacts[0].path == ".future/agents/x.md"
    finally:
        from studio_client.adapters import base as _base

        del _base._REGISTRY["future-harness"]
        assert "future-harness" not in list_adapters()


# --- sanitize -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("stable_key", "expected"),
    [
        ("review-helper", "review-helper"),
        ("../escape", "escape"),
        ("/absolute", "absolute"),
        ("a/b\\c", "a-b-c"),
        ("", "agent"),
        ("--", "agent"),
        ("UPPER_case.1", "UPPER_case-1"),
        ("CON", "CON_"),
        ("nul", "nul_"),
        ("com1", "com1_"),
    ],
)
def test_sanitize_agent_filename(stable_key: str, expected: str) -> None:
    assert sanitize_agent_filename(stable_key) == expected


# --- materialize --------------------------------------------------------------


def test_materialize_writes_and_roundtrips(tmp_path: Path) -> None:
    result = get_adapter("claude-code").translate(_resolved("claude-code"))
    written = materialize(result, tmp_path, managed_dir=".claude/agents")
    assert written == [tmp_path / ".claude" / "agents" / "review-helper.md"]
    assert written[0].read_text(encoding="utf-8") == result.artifacts[0].content


def test_materialize_refuses_overwrite_by_default(tmp_path: Path) -> None:
    result = get_adapter("claude-code").translate(_resolved("claude-code"))
    materialize(result, tmp_path, managed_dir=".claude/agents")
    with pytest.raises(AdapterError) as exc_info:
        materialize(result, tmp_path, managed_dir=".claude/agents")
    assert exc_info.value.code == AdapterErrorCode.MATERIALIZATION_FAILED


def test_materialize_overwrite_replaces_atomically(tmp_path: Path) -> None:
    result = get_adapter("claude-code").translate(_resolved("claude-code"))
    materialize(result, tmp_path, managed_dir=".claude/agents")
    materialize(result, tmp_path, managed_dir=".claude/agents", overwrite=True)
    leftovers = list(tmp_path.rglob("*.studio-tmp"))
    assert leftovers == []


def test_materialize_rejects_escape_and_writes_nothing(tmp_path: Path) -> None:
    evil = AdapterResult(
        adapter_id="claude-code",
        artifacts=(
            AdapterArtifact(path=".claude/agents/ok.md", content="ok"),
            AdapterArtifact(path="../evil.md", content="evil"),
        ),
    )
    with pytest.raises(AdapterError) as exc_info:
        materialize(evil, tmp_path, managed_dir=".claude/agents")
    assert exc_info.value.code == AdapterErrorCode.MATERIALIZATION_FAILED
    assert list(tmp_path.rglob("*")) == []


def test_materialize_rejects_absolute_and_outside_managed(tmp_path: Path) -> None:
    for bad in ("/etc/passwd", ".opencode/agents/x.md"):
        evil = AdapterResult(
            adapter_id="claude-code",
            artifacts=(AdapterArtifact(path=bad, content="x"),),
        )
        with pytest.raises(AdapterError):
            materialize(evil, tmp_path, managed_dir=".claude/agents")
    assert list(tmp_path.rglob("*")) == []


def test_materialize_never_touches_unmanaged_files(tmp_path: Path) -> None:
    user_file = tmp_path / ".claude" / "agents" / "user-handwritten.md"
    user_file.parent.mkdir(parents=True)
    user_file.write_text("user content", encoding="utf-8")
    result = get_adapter("claude-code").translate(_resolved("claude-code"))
    materialize(result, tmp_path, managed_dir=".claude/agents")
    assert user_file.read_text(encoding="utf-8") == "user content"


# --- secrets -------------------------------------------------------------------


def test_no_secret_field_is_projected() -> None:
    for adapter_id in ("claude-code", "opencode"):
        content = get_adapter(adapter_id).translate(_resolved(None)).artifacts[0].content
        assert "runtime_metadata" not in content
        assert "api_key" not in content
        assert "Authorization" not in content


# --- context package (generic, P9 unchanged) ------------------------------------


def test_context_package_projects_generically() -> None:
    from studio_client.context.composer import ContextPackage
    from studio_client.context.manifest import (
        ContextPackageManifest,
        Generator,
        SourceRef,
    )

    manifest = ContextPackageManifest(
        project_id=uuid.uuid4(),
        task_id=None,
        generator=Generator(machine_id=uuid.uuid4()),
        sources=[SourceRef(kind="task", ref="t", included=1)],
        omitted=[],
        truncated=False,
    )
    package = ContextPackage(manifest=manifest, data={"task": {"id": "t"}})
    for adapter_id in ("claude-code", "opencode"):
        before = _dump(resolved := _resolved(None))
        result = get_adapter(adapter_id).translate(resolved, context=package)
        assert "## Context" in result.artifacts[0].content
        assert _dump(resolved) == before


# --- core neutrality guard -------------------------------------------------------


def test_core_stays_free_of_harness_provider_branches() -> None:
    """P10 §39: no product/vendor literal may steer the canonical core.

    Scanned zones: contracts, Library/resolution services, runtime
    bindings/registry, generic context composer. Adapters, tests, docs,
    examples and harness-owned agent files are the only allowed homes
    for product names."""
    repo = Path(__file__).resolve().parents[3]
    zones = [
        repo / "packages" / "studio-contracts" / "src",
        repo / "services" / "api" / "src" / "studio_api" / "services",
        repo / "packages" / "studio-client" / "src" / "studio_client" / "context",
    ]
    forbidden = ("claude-code", "claude_code", "opencode", "open_code", "anthropic", "ollama")
    offenders: list[str] = []
    for zone in zones:
        for path in sorted(zone.rglob("*.py")):
            text = path.read_text(encoding="utf-8").lower()
            hits = [token for token in forbidden if token in text]
            if hits:
                offenders.append(f"{path.relative_to(repo)}: {hits}")
    assert offenders == []
