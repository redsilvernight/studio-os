"""B2 — compatibility matrix validated against the code (DU-0/D).

The matrix in ``studio_contracts.compatibility`` is the reference; this test
fails if the code constants drift (contract bump without matrix update) or if
the Desktop bundle carriers drift (``version.mjs --check`` equivalent).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from studio_contracts import API_CONTRACT_VERSION, EVENT_SCHEMA_VERSION
from studio_contracts.compatibility import (
    CURRENT_VERSIONS,
    ChangeKind,
    ClientVerdict,
    classify,
)
from studio_contracts.local.common import (
    LOCAL_PROTOCOL_MAJOR,
    LOCAL_PROTOCOL_MINOR,
)

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "desktop" / "package.json").is_file():
            return parent
    raise AssertionError("repo root (desktop/package.json) not found")


def test_current_versions_match_code_constants() -> None:
    assert CURRENT_VERSIONS == {
        "api_contract_version": API_CONTRACT_VERSION,
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "local_protocol_major": LOCAL_PROTOCOL_MAJOR,
        "local_protocol_minor": LOCAL_PROTOCOL_MINOR,
    }
    assert API_CONTRACT_VERSION == 2
    assert EVENT_SCHEMA_VERSION == 1
    assert (LOCAL_PROTOCOL_MAJOR, LOCAL_PROTOCOL_MINOR) == (1, 0)


def test_desktop_bundle_versions_synced() -> None:
    root = _repo_root()
    package_json = root / "desktop" / "package.json"
    canonical = json.loads(package_json.read_text(encoding="utf-8"))["version"]
    assert SEMVER.match(canonical), canonical
    cargo = (root / "desktop" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    assert re.search(r'(?m)^version\s*=\s*"' + re.escape(canonical) + r'"', cargo)
    daemon_py = (
        root / "packages" / "studio-client" / "src" / "studio_client" / "daemon" / "service.py"
    )
    daemon = daemon_py.read_text(encoding="utf-8")
    assert f'DAEMON_VERSION = "{canonical}"' in daemon


def test_matrix_covers_every_change_and_lag_band() -> None:
    from studio_contracts.compatibility import COMPATIBILITY_MATRIX

    bands = {"N", "N-1", "<N-1"}
    assert {(c, b) for c in ChangeKind for b in bands} == set(COMPATIBILITY_MATRIX)
    for change in ChangeKind:
        assert classify(change, 0) is COMPATIBILITY_MATRIX[(change, "N")]
        assert classify(change, 1) is COMPATIBILITY_MATRIX[(change, "N-1")]
        assert classify(change, 2) is COMPATIBILITY_MATRIX[(change, "<N-1")]
        assert classify(change, 5) is COMPATIBILITY_MATRIX[(change, "<N-1")]


def test_n_is_always_compatible() -> None:
    for change in ChangeKind:
        assert classify(change, 0) is ClientVerdict.COMPATIBLE


def test_n_minus_1_policy() -> None:
    assert classify(ChangeKind.ADDITIVE, 1) is ClientVerdict.UPGRADE_RECOMMENDED
    assert classify(ChangeKind.API_BREAKING, 1) is ClientVerdict.UPGRADE_REQUIRED
    assert classify(ChangeKind.EVENT_BREAKING, 1) is ClientVerdict.UPGRADE_REQUIRED
    assert classify(ChangeKind.LOCAL_BREAKING, 1) is ClientVerdict.PROTOCOL_INCOMPATIBLE
    assert classify(ChangeKind.AUTH_BREAKING, 1) is ClientVerdict.UPGRADE_REQUIRED


def test_older_than_n_minus_1_fails_closed() -> None:
    for change in ChangeKind:
        assert classify(change, 2) in (
            ClientVerdict.UPGRADE_REQUIRED,
            ClientVerdict.PROTOCOL_INCOMPATIBLE,
        )


def test_rebuilt_artifact_never_trusted() -> None:
    for change in ChangeKind:
        for lag in (0, 1, 3):
            assert classify(change, lag, same_artifact=False) is ClientVerdict.PROTOCOL_INCOMPATIBLE
