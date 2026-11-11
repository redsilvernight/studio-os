"""Harness adapters over a Library-resolved agent: capabilities, codex shape,
open registry (no DB, no repository files)."""

from __future__ import annotations

from typing import Any

import pytest
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
from studio_contracts.resolution import ResolvedAgentDefinition

from tests.library_bundle import make_agent, make_rule

FORBIDDEN = ("opus", "sonnet", "gpt-", "kimi", "anthropic", "openai", "claude-code")


def test_capabilities_cover_all_dimensions() -> None:
    for adapter_id in ("claude-code", "opencode", "codex"):
        caps = get_adapter(adapter_id).capabilities()
        assert set(caps) == set(CAPABILITY_DIMENSIONS)
        assert all(isinstance(v, CapabilitySupport) for v in caps.values())
    assert get_adapter("claude-code").capabilities()["permissions"] == CapabilitySupport.SUPPORTED
    assert get_adapter("opencode").capabilities()["permissions"] == CapabilitySupport.DEGRADED
    assert get_adapter("codex").capabilities()["permissions"] == CapabilitySupport.DEGRADED


def test_codex_projection_shape() -> None:
    resolved = make_agent(
        "studio-architect",
        instructions="You are the architecture specialist.\n",
        requirements={"reasoning": "high"},
    )
    result = get_adapter("codex").translate(resolved)
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.path == ".codex/agents/studio-architect.toml"
    assert 'name = "studio-architect"' in artifact.content
    assert "model_reasoning_effort = 'high'" in artifact.content
    assert "developer_instructions = '''" in artifact.content
    assert "You are the architecture specialist" in artifact.content
    assert "\nmodel = " not in artifact.content  # no runtime binding configured


@pytest.mark.parametrize("adapter_id", ["claude-code", "opencode", "codex"])
def test_projection_names_no_model_or_harness(adapter_id: str) -> None:
    resolved = make_agent("sync-debugger", rules=[make_rule("testing", "Run the tests.\n")])
    for artifact in get_adapter(adapter_id).translate(resolved).artifacts:
        text = artifact.content.lower()
        for token in FORBIDDEN:
            if token == adapter_id:
                continue
            assert token not in text, f"{adapter_id} leaks {token!r}"


def test_projection_is_deterministic() -> None:
    first = get_adapter("claude-code").translate(make_agent("studio-tester"))
    second = get_adapter("claude-code").translate(make_agent("studio-tester"))
    assert first == second


def test_fake_third_party_adapter_needs_no_core_change() -> None:
    """P3.10: a new harness registers against the open registry, receives the
    resolved definition, and projects it — Library, Resolution, contracts
    and skills untouched."""

    from studio_client.adapters import register_adapter

    seen: dict[str, Any] = {}

    class TestHarnessAdapter:
        adapter_id = "test-harness"
        managed_dir = ".test/agents"

        def capabilities(self) -> dict[str, CapabilitySupport]:
            return dict.fromkeys(CAPABILITY_DIMENSIONS, CapabilitySupport.SUPPORTED)

        def translate(
            self, resolved: ResolvedAgentDefinition, *, context: Any | None = None
        ) -> AdapterResult:
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

    register_adapter(TestHarnessAdapter())
    try:
        assert "test-harness" in list_adapters()
        resolved = make_agent(
            "sync-debugger",
            rules=[make_rule(key, "Body.\n") for key in ("contracts", "offline-sync", "testing")],
        )
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

        def translate(
            self, resolved: ResolvedAgentDefinition, *, context: Any | None = None
        ) -> AdapterResult:
            from studio_client.adapters.base import ensure_supported

            ensure_supported(
                self.adapter_id,
                self.capabilities(),
                edit_policy=resolved.agent.content.get("edit_policy"),  # type: ignore[arg-type]
            )
            raise AssertionError("must not reach projection")

    register_adapter(NoPermissionsAdapter())
    try:
        with pytest.raises(AdapterError) as exc_info:
            get_adapter("no-perms").translate(make_agent("studio-tester"))
        assert exc_info.value.code == AdapterErrorCode.UNSUPPORTED
    finally:
        _REGISTRY.pop("no-perms", None)
