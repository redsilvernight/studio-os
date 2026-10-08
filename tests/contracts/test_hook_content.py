"""Kind `hook` de la bibliothèque (DEC-0194) : schéma, validation statique, bindings."""

from __future__ import annotations

import pytest

from studio_contracts.library import (
    BindingRelation,
    HookValidationReason,
    LibraryKind,
    binding_relation_for,
    content_validation_errors,
    hook_validation_errors,
)


def _hook(**overrides: object) -> dict[str, object]:
    content: dict[str, object] = {
        "content_schema": "studio.library.hook/v1",
        "event": "pre_tool",
        "matcher": "Bash",
        "mode": "blocking",
        "scripts": [{"os": "windows", "shell": "pwsh", "body": "Write-Host ok"}],
    }
    content.update(overrides)
    return content


def test_valid_hook_passes_both_validators() -> None:
    assert content_validation_errors(LibraryKind.HOOK, _hook()) == []
    assert hook_validation_errors(_hook()) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"event": "on_save"},
        {"scripts": []},
        {"timeout_seconds": 0},
        {"timeout_seconds": 601},
        {"provider": "anthropic"},
        {"scripts": [{"shell": "cmd", "body": "echo"}]},
        {"scripts": [{"shell": "bash", "body": ""}]},
    ],
)
def test_schema_rejects_invalid_shapes(overrides: dict[str, object]) -> None:
    assert content_validation_errors(LibraryKind.HOOK, _hook(**overrides))


@pytest.mark.parametrize(
    ("overrides", "reason", "field"),
    [
        (
            {"scripts": [{"shell": "bash", "body": "a"}, {"shell": "bash", "body": "b"}]},
            HookValidationReason.DUPLICATE_SCRIPT_TARGET,
            "scripts.1",
        ),
        (
            {"scripts": [{"shell": "bash", "body": "export API_KEY=abcd1234efgh"}]},
            HookValidationReason.SECRET_MATERIAL,
            "scripts.0.body",
        ),
        ({"event": "stop", "mode": "advisory"}, HookValidationReason.MATCHER_NOT_SUPPORTED, "matcher"),
        (
            {"event": "notification", "matcher": None},
            HookValidationReason.BLOCKING_NOT_SUPPORTED,
            "mode",
        ),
    ],
)
def test_static_validation_reasons(
    overrides: dict[str, object], reason: HookValidationReason, field: str
) -> None:
    assert hook_validation_errors(_hook(**overrides)) == [{"field": field, "reason": reason.value}]


def test_same_shell_on_distinct_os_is_allowed() -> None:
    scripts = [{"os": "windows", "shell": "pwsh", "body": "a"}, {"os": "linux", "shell": "pwsh", "body": "b"}]
    assert hook_validation_errors(_hook(scripts=scripts)) == []


def test_binding_matrix_for_hook() -> None:
    assert binding_relation_for(LibraryKind.AGENT_DEFINITION, LibraryKind.HOOK) is BindingRelation.USES_HOOK
    assert binding_relation_for(LibraryKind.WORKFLOW, LibraryKind.HOOK) is BindingRelation.USES_HOOK
    for target in LibraryKind:
        assert binding_relation_for(LibraryKind.HOOK, target) is None
    assert binding_relation_for(LibraryKind.SKILL, LibraryKind.HOOK) is None
