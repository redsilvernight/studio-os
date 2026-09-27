from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from studio_contracts.bootstrap import (
    BOOTSTRAP_FORMAT,
    MAX_BOOTSTRAP_HARNESSES,
    BootstrapHarnessRef,
    BootstrapManifest,
    BootstrapPolicy,
    BootstrapProblemCode,
    bootstrap_manifest_problems,
)
from studio_contracts.initialization import InitializationProjectSpec

MANIFESTS_FIXTURE = Path(__file__).with_name("bootstrap_manifests.json")
FORBIDDEN_EXTRA_FIELDS = {
    "token",
    "api_key",
    "secret",
    "password",
    "path",
    "repo_path",
    "metadata",
    "provider",
    "model",
    "machine_token",
}
ABSOLUTE_PATHS = [
    "/etc/passwd",
    "/tmp/bootstrap",
    "C:\\Users\\dev\\repo",
    "C:/Users/dev/repo",
    "\\\\server\\share",
    "~/.claude",
    "~/repo",
]


def _load_manifests() -> list[dict[str, Any]]:
    raw = json.loads(MANIFESTS_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    return list(raw)


def _minimal(**overrides: Any) -> BootstrapManifest:
    data: dict[str, Any] = {
        "project": {"slug": "p", "name": "P"},
        "harnesses": [{"id": "claude-code"}],
    }
    data.update(overrides)
    return BootstrapManifest.model_validate(data)


def test_fixtures_are_valid_and_round_trip() -> None:
    manifests = _load_manifests()
    assert len(manifests) == 3
    for raw in manifests:
        manifest = BootstrapManifest.model_validate(raw)
        assert manifest.format == BOOTSTRAP_FORMAT
        assert bootstrap_manifest_problems(manifest) == []
        assert BootstrapManifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_minimal_manifest_uses_refuse_by_default() -> None:
    manifest = _minimal()
    assert manifest.policy.on_modified.value == "refuse"
    assert [ref.id for ref in manifest.harnesses] == ["claude-code"]


def test_format_tag_is_enforced() -> None:
    with pytest.raises(ValidationError):
        _minimal(format="studio.bootstrap/v2")
    with pytest.raises(ValidationError):
        _minimal(format="studio.initialization/v1")


def test_extra_fields_are_rejected() -> None:
    for field in sorted(FORBIDDEN_EXTRA_FIELDS):
        with pytest.raises(ValidationError):
            _minimal(**{field: "smuggled"})
    with pytest.raises(ValidationError):
        BootstrapManifest.model_validate(
            {
                "format": BOOTSTRAP_FORMAT,
                "project": {"slug": "p", "name": "P", "token": "smuggled"},
                "harnesses": [{"id": "claude-code"}],
            }
        )


def test_absolute_paths_are_not_representable() -> None:
    for path in ABSOLUTE_PATHS:
        with pytest.raises(ValidationError):
            _minimal(project={"slug": path, "name": "P"})
        with pytest.raises(ValidationError):
            _minimal(project={"slug": "p", "name": path})
        with pytest.raises(ValidationError):
            _minimal(harnesses=[{"id": path}])


def test_prose_may_mention_a_path_inline() -> None:
    manifest = _minimal(
        project={
            "slug": "p",
            "name": "P",
            "description": "Voir /docs pour la procédure et C:\\outils en dernier recours.",
        }
    )
    assert manifest.project.description is not None


def test_harness_id_vocabulary_is_kebab_case() -> None:
    for bad_id in ["Claude Code", "claude_code", "Claude-Code", "", "a" * 201]:
        with pytest.raises(ValidationError):
            BootstrapHarnessRef.model_validate({"id": bad_id})
    for good_id in ["claude-code", "opencode", "codex", "my-future-harness-2"]:
        assert BootstrapHarnessRef.model_validate({"id": good_id}).id == good_id


def test_at_least_one_harness_and_bounded() -> None:
    with pytest.raises(ValidationError):
        _minimal(harnesses=[])
    with pytest.raises(ValidationError):
        _minimal(harnesses=[{"id": f"harness-{n}"} for n in range(MAX_BOOTSTRAP_HARNESSES + 1)])


def test_unknown_policy_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _minimal(policy={"on_modified": "overwrite"})


def test_exactly_max_harnesses_is_accepted() -> None:
    manifest = _minimal(harnesses=[{"id": f"harness-{n}"} for n in range(MAX_BOOTSTRAP_HARNESSES)])
    assert len(manifest.harnesses) == MAX_BOOTSTRAP_HARNESSES
    assert bootstrap_manifest_problems(manifest) == []


def test_empty_policy_defaults_to_refuse() -> None:
    assert _minimal(policy={}).policy.on_modified.value == "refuse"


def test_no_provider_model_runtime_or_secret_field_exists() -> None:
    forbidden = {
        "provider",
        "model",
        "runtime",
        "runtime_id",
        "machine",
        "capabilities",
        "token",
        "secret",
        "metadata",
    }
    fields = (
        set(BootstrapManifest.model_fields)
        | set(BootstrapHarnessRef.model_fields)
        | set(BootstrapPolicy.model_fields)
    )
    assert forbidden & fields == set()


def test_project_identity_shape_is_locked() -> None:
    assert set(InitializationProjectSpec.model_fields) == {"slug", "name", "description"}


def test_duplicate_harness_is_a_problem_not_a_parse_error() -> None:
    manifest = _minimal(harnesses=[{"id": "opencode"}, {"id": "opencode"}])
    problems = bootstrap_manifest_problems(manifest)
    assert len(problems) == 1
    assert problems[0].code is BootstrapProblemCode.DUPLICATE_HARNESS
    assert problems[0].key == "opencode"
