from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_workspaces.secret_guard import (
    SecretMaterialError,
    assert_no_secrets,
    find_secret_issues,
    scan_studio_dir,
)

from .factories import PROJECT_ID, make_config

WS_ID = "11111111-1111-4111-8111-111111111111"


def _valid_payload() -> dict[str, object]:
    from uuid import UUID

    return make_config(UUID(WS_ID), "C:/Work/demo").model_dump(mode="json")


def test_valid_config_has_no_secret_issues() -> None:
    assert find_secret_issues(_valid_payload()) == []
    assert_no_secrets(_valid_payload())


def test_secret_reference_shape_is_allowed() -> None:
    payload = _valid_payload()
    payload["secret_references"] = [
        {
            "ref_id": "sr-machine-default",
            "kind": "machine_credential",
            "store": "os_keyring",
            "lookup_key": "studio.machine.default",
            "profile": {
                "profile_id": "default",
                "server_origin": "https://studio.example.test",
            },
        }
    ]
    assert find_secret_issues(payload) == []
    assert_no_secrets(payload)


def test_token_value_is_flagged() -> None:
    payload = _valid_payload()
    payload["project_slug"] = "demo-" + "eyJ" + "A" * 20 + "." + "B" * 20 + "." + "C" * 20
    assert find_secret_issues(payload) != []
    with pytest.raises(SecretMaterialError):
        assert_no_secrets(payload)


def test_secret_key_name_is_flagged() -> None:
    with pytest.raises(SecretMaterialError):
        assert_no_secrets({"api_key": "placeholder-value"})


def test_reference_with_extra_value_field_is_flagged() -> None:
    payload = _valid_payload()
    payload["secret_references"] = [
        {
            "ref_id": "sr-1",
            "kind": "machine_credential",
            "store": "os_keyring",
            "lookup_key": "studio.machine",
            "profile": {"profile_id": "default", "server_origin": "https://studio.example.test"},
            "value": "must-never-be-here",
        }
    ]
    with pytest.raises(SecretMaterialError):
        assert_no_secrets(payload)


def test_scan_studio_dir_flags_secret_file(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    studio = root / ".studio"
    studio.mkdir(parents=True)
    (studio / "workspace.json").write_text(
        json.dumps(
            {"workspace_id": "11111111-1111-4111-8111-111111111111", "project_id": str(PROJECT_ID)}
        ),
        encoding="utf-8",
    )
    (studio / "notes.json").write_text(json.dumps({"password": "hunter2-hunter"}), encoding="utf-8")
    issues = scan_studio_dir(root)
    assert any("notes.json" in issue for issue in issues)
    assert not any("workspace.json" in issue for issue in issues)


def test_scan_missing_studio_dir_is_clean(tmp_path: Path) -> None:
    assert scan_studio_dir(tmp_path / "empty") == []


def test_committed_p5_sources_carry_no_secret_material() -> None:
    here = Path(__file__).resolve()
    repo = here.parents[2]
    targets = [
        repo / "packages" / "studio-workspaces",
        repo / "tests" / "workspaces",
        repo / "dashboard" / "src" / "workspaces",
    ]
    from studio_contracts.local.common import contains_secret_material

    checked = 0
    for base in targets:
        if not base.exists():
            continue
        for child in sorted(base.rglob("*")):
            if not child.is_file() or child.suffix not in {".py", ".ts", ".css", ".md", ".json"}:
                continue
            try:
                text = child.read_text(encoding="utf-8")
            except OSError:
                continue
            assert not contains_secret_material(text), child.name
            checked += 1
    assert checked > 0
