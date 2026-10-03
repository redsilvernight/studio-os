from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from studio_contracts.bootstrap import (
    BOOTSTRAP_FORMAT,
    BOOTSTRAP_VERSION_REPAIR_ACTION,
    MAX_BOOTSTRAP_FILES,
    MAX_BOOTSTRAP_HARNESSES,
    BootstrapConflict,
    BootstrapConflictCode,
    BootstrapDryRunReport,
    BootstrapFileReport,
    BootstrapHarnessRef,
    BootstrapManifest,
    BootstrapPolicy,
    BootstrapProblemCode,
    BootstrapVersionError,
    bootstrap_dry_run_conflicts,
    bootstrap_manifest_problems,
    bootstrap_version_gate,
    build_dry_run_report,
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


def test_version_gate_accepts_supported_format() -> None:
    data = {
        "format": BOOTSTRAP_FORMAT,
        "project": {"slug": "p", "name": "P"},
        "harnesses": [{"id": "claude-code"}],
    }
    bootstrap_version_gate(data)


@pytest.mark.parametrize(
    "received",
    [
        "studio.bootstrap/v0",
        "studio.bootstrap/v2",
        "studio.initialization/v1",
        "Studio.Bootstrap/v1",
        "v1",
        "",
        1,
        ["studio.bootstrap/v1"],
        {"format": "studio.bootstrap/v1"},
        True,
    ],
    ids=[
        "v0",
        "v2",
        "wrong-family",
        "capitalised",
        "short",
        "empty",
        "int",
        "list",
        "dict",
        "bool",
    ],
)
def test_version_gate_rejects_unsupported_format(received: object) -> None:
    data = {
        "format": received,
        "project": {"slug": "p", "name": "P"},
        "harnesses": [{"id": "claude-code"}],
    }
    with pytest.raises(BootstrapVersionError) as excinfo:
        bootstrap_version_gate(data)
    exc = excinfo.value
    assert exc.code == "unsupported_bootstrap_manifest_version"
    assert exc.received == received
    assert exc.expected == BOOTSTRAP_FORMAT
    assert exc.action == BOOTSTRAP_VERSION_REPAIR_ACTION


def test_version_gate_accepts_missing_format_as_implicit_v1() -> None:
    data = {
        "project": {"slug": "p", "name": "P"},
        "harnesses": [{"id": "claude-code"}],
    }
    bootstrap_version_gate(data)
    assert BootstrapManifest.model_validate(data).format == BOOTSTRAP_FORMAT


@pytest.mark.parametrize("raw", [None, [], "studio.bootstrap/v1", 1])
def test_version_gate_rejects_non_object_documents(raw: object) -> None:
    with pytest.raises(BootstrapVersionError) as excinfo:
        bootstrap_version_gate(raw)
    assert excinfo.value.code == "unsupported_bootstrap_manifest_version"
    assert excinfo.value.received == f"<non-object:{type(raw).__name__}>"


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


GOOD_HASH = "sha256:" + "0" * 64


def _file(path: str, state: str, **overrides: Any) -> BootstrapFileReport:
    data: dict[str, Any] = {"path": path, "state": state}
    data.update(overrides)
    return BootstrapFileReport.model_validate(data)


def test_all_five_states_parse() -> None:
    for state in ["absent", "obsolete", "modified", "incompatible", "up_to_date"]:
        assert _file("docs/x.md", state).state.value == state
    with pytest.raises(ValidationError):
        _file("docs/x.md", "drifted")


def test_file_paths_are_repo_relative_and_portable() -> None:
    for bad in [
        "/etc/passwd",
        "C:\\repo\\x.md",
        "\\\\server\\x.md",
        "../escape.md",
        "docs/../escape.md",
        "docs\\x.md",
        "",
        ".",
        "./x.md",
        "docs//x.md",
        "docs/x.md/",
    ]:
        with pytest.raises(ValidationError):
            _file(bad, "absent")
    for good in ["CLAUDE.md", "docs/decisions/x.md", ".agents/rules/x.md"]:
        assert _file(good, "absent").path == good


def test_absent_carries_no_origin_nor_hash() -> None:
    with pytest.raises(ValidationError):
        _file("docs/x.md", "absent", origin_version=3)
    with pytest.raises(ValidationError):
        _file("docs/x.md", "absent", content_hash=GOOD_HASH)
    assert _file("docs/x.md", "absent").content_hash is None


def test_content_hash_shape_is_enforced() -> None:
    assert _file("docs/x.md", "up_to_date", content_hash=GOOD_HASH).content_hash == GOOD_HASH
    for bad in ["sha256:xyz", "md5:" + "0" * 32, GOOD_HASH.upper(), ""]:
        with pytest.raises(ValidationError):
            _file("docs/x.md", "up_to_date", content_hash=bad)


def test_modified_under_refuse_blocks_sync() -> None:
    manifest = _minimal()
    files = [_file("CLAUDE.md", "modified", origin_version=1, content_hash=GOOD_HASH)]
    conflicts = bootstrap_dry_run_conflicts(manifest, files)
    assert len(conflicts) == 1
    assert conflicts[0].code is BootstrapConflictCode.MODIFIED_NEEDS_CONFIRMATION
    assert conflicts[0].blocking is True
    report = build_dry_run_report(manifest, files)
    assert report.sync_allowed is False
    assert report.summary.modified == 1


def test_modified_under_ask_needs_confirmation_and_blocks_sync() -> None:
    manifest = _minimal(policy={"on_modified": "ask"})
    files = [_file("CLAUDE.md", "modified", origin_version=1, content_hash=GOOD_HASH)]
    assert bootstrap_dry_run_conflicts(manifest, files) == []
    report = build_dry_run_report(manifest, files)
    assert report.needs_confirmation is True
    assert report.sync_allowed is False


def test_ask_without_modified_allows_sync() -> None:
    manifest = _minimal(policy={"on_modified": "ask"})
    report = build_dry_run_report(manifest, [_file("CLAUDE.md", "up_to_date")])
    assert report.needs_confirmation is False
    assert report.sync_allowed is True


def test_non_blocking_conflict_does_not_block_sync() -> None:
    manifest = _minimal()
    report = BootstrapDryRunReport(
        manifest=manifest,
        files=[],
        conflicts=[
            BootstrapConflict(code=BootstrapConflictCode.INCOMPATIBLE_TARGET, blocking=False)
        ],
        sync_allowed=True,
    )
    assert report.sync_allowed is True


def test_field_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        _file("docs/x.md", "up_to_date", message="m" * 501)
    with pytest.raises(ValidationError):
        _file("docs/x.md", "up_to_date", origin_version=0)
    report = build_dry_run_report(_minimal(), [])
    assert report.sync_allowed is True
    assert report.needs_confirmation is False


def test_report_is_deterministic_across_input_orders() -> None:
    manifest = _minimal()
    first = [
        _file("b.md", "absent"),
        _file("a.md", "modified", origin_version=1, content_hash=GOOD_HASH),
    ]
    second = list(reversed(first))
    assert build_dry_run_report(manifest, first) == build_dry_run_report(manifest, second)


def test_incompatible_always_blocks() -> None:
    for policy in ({}, {"on_modified": "ask"}):
        manifest = _minimal(policy=policy)
        files = [_file(".codex/agents/x.toml", "incompatible")]
        conflicts = bootstrap_dry_run_conflicts(manifest, files)
        assert [c.code for c in conflicts] == [BootstrapConflictCode.INCOMPATIBLE_TARGET]
        assert build_dry_run_report(manifest, files).sync_allowed is False


def test_clean_states_allow_sync_and_count() -> None:
    manifest = _minimal()
    files = [
        _file("a.md", "absent"),
        _file("b.md", "obsolete", origin_version=1, content_hash=GOOD_HASH),
        _file("c.md", "up_to_date", origin_version=2, content_hash=GOOD_HASH),
    ]
    report = build_dry_run_report(manifest, files)
    assert report.conflicts == []
    assert report.sync_allowed is True
    assert (report.summary.absent, report.summary.obsolete, report.summary.up_to_date) == (1, 1, 1)
    assert BootstrapDryRunReport.model_validate_json(report.model_dump_json()) == report
    assert build_dry_run_report(manifest, files) == report


def test_report_is_bounded() -> None:
    manifest = _minimal()
    files = [_file(f"f{n}.md", "absent") for n in range(MAX_BOOTSTRAP_FILES + 1)]
    with pytest.raises(ValidationError):
        build_dry_run_report(manifest, files)


def test_dry_run_models_carry_no_secret_or_runtime_field() -> None:
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
        set(BootstrapFileReport.model_fields)
        | set(BootstrapConflict.model_fields)
        | set(BootstrapDryRunReport.model_fields)
    )
    assert forbidden & fields == set()
