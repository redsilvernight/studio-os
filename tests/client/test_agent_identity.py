"""DEC-0225 : une fiche agent par (poste, provider, modele), tous harnais."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest
from studio_client import cli
from studio_client.agent_identity import (
    is_legacy_model_key,
    model_agent_create,
    normalize_model_ref,
    observed_identity_request,
)
from studio_contracts.agent_identity import AgentIdentityResult


def test_same_model_from_two_harnesses_yields_identical_registration() -> None:
    from_claude = model_agent_create("anthropic/claude-opus-5-5")
    from_codex = model_agent_create(" Claude-Opus-5-5 ", provider="Anthropic")
    assert from_claude is not None
    assert from_claude == from_codex
    assert from_claude.stable_key == "agent-model:anthropic/claude-opus-5-5"
    assert from_claude.display_name == "claude-opus-5-5"
    assert from_claude.harness is None


def test_different_models_and_variants_stay_distinct() -> None:
    keys = {
        model_agent_create(m).stable_key  # type: ignore[union-attr]
        for m in (
            "anthropic/claude-opus-5-5",
            "anthropic/claude-sonnet-5-5",
            "anthropic/claude-opus-5-5-20261001",
            "openrouter/claude-opus-5-5",
        )
    }
    assert len(keys) == 4


@pytest.mark.parametrize("model", [None, "", "   ", "anthropic/"])
def test_unknown_model_has_no_model_identity(model: str | None) -> None:
    assert normalize_model_ref(model) is None
    assert model_agent_create(model) is None


def test_model_without_provider_is_explicitly_unknown_provider() -> None:
    agent = model_agent_create("gpt-6")
    assert agent is not None
    assert agent.stable_key == "agent-model:unknown/gpt-6"
    assert agent.provider is None


def test_legacy_keys_are_recognized_not_rewritten() -> None:
    assert is_legacy_model_key("agents-ensure-opencode:opencode-go/deepseek")
    assert is_legacy_model_key("launch-agent-" + "a" * 64)
    assert not is_legacy_model_key("agents-ensure-opencode")
    assert is_legacy_model_key("agent-model:anthropic/claude-opus-5-5")
    assert not is_legacy_model_key("canonical-model-v1:" + "a" * 64)
    assert not is_legacy_model_key(None)


def test_cli_resolves_observed_model_with_its_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fake_run(config, action):  # noqa: ANN001
        class Client:
            async def resolve_agent_identity(self, request):  # noqa: ANN001
                seen.append(request)
                from uuid import uuid4

                from studio_contracts.auth import Agent

                return AgentIdentityResult(
                    state="resolved",
                    logical_harness=request.harness,
                    agent=Agent(
                        id=uuid4(),
                        display_name="model",
                        agent_kind="model",
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                        version=1,
                    ),
                )

        import asyncio

        return asyncio.run(action(Client()))

    monkeypatch.setattr(cli, "_run", fake_run)
    monkeypatch.setattr(cli, "_print_model", lambda *a, **k: None)
    for harness in ("claude-code", "codex"):
        args = argparse.Namespace(
            harness=harness,
            display_name=None,
            agent_kind="",
            agent_profile=None,
            provider="anthropic",
            model="claude-opus-5-5",
            stable_key=None,
            model_identity=True,
            json=True,
        )
        cli._agents_ensure(args, None)  # type: ignore[arg-type]
    assert [request.harness for request in seen] == ["claude-code", "codex"]
    assert all(request.effective_model == "claude-opus-5-5" for request in seen)
    assert all(request.provider == "anthropic" for request in seen)


def test_observation_preserves_case_and_does_not_infer_a_provider() -> None:
    result = observed_identity_request("opencode", "Vendor/CaseSensitiveModel")
    assert result.provider == "Vendor"
    assert result.effective_model == "CaseSensitiveModel"
    assert observed_identity_request("codex", "gpt-6.1-sol").provider is None
