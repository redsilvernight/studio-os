"""Parse actual projections, including the apostrophe case missed by snapshots."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

import pytest
from studio_client import bootstrap
from studio_client.adapters import get_adapter
from studio_client.adapters.codex import _toml_string
from studio_client.adapters_check import check_adapters
from studio_client.bootstrap import make_manifest

from tests.library_bundle import sample_bundle


@pytest.mark.parametrize(
    "value",
    [
        "Studio OS's contracts",
        'quoted "description"',
        "C:\\Users\\example",
        "line\nnext\r\ntab\t",
        "é — UTF-8",
        "",
    ],
)
def test_codex_basic_string_roundtrips(value: str) -> None:
    assert tomllib.loads("description = " + _toml_string(value))["description"] == value


@pytest.mark.parametrize("key", sorted(sample_bundle().agents))
def test_codex_projection_parses_and_preserves_requirements(key: str) -> None:
    resolved = sample_bundle().agents[key]
    result = get_adapter("codex").translate(resolved)
    data = tomllib.loads(result.artifacts[0].content)
    assert data["name"] == key
    assert data["description"] == resolved.agent.content["summary"]
    assert data["model_reasoning_effort"] == resolved.requirements.reasoning
    assert "model" not in data
    assert "adapter='codex'" in data["developer_instructions"]


def test_two_complete_generations_are_identical(tmp_path: Path) -> None:
    bundle = sample_bundle()
    manifest = make_manifest("demo", "Demo", ["claude-code", "codex", "opencode"])
    snapshots = []
    for _ in range(2):
        bootstrap.sync(tmp_path, manifest, bundle, confirm=True)
        result = check_adapters(tmp_path, bundle)
        assert result.checked > 0 and not result.failures
        snapshots.append(
            {
                p.relative_to(tmp_path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in tmp_path.rglob("*")
                if p.is_file() and ".studio-os" not in p.parts
            }
        )
    assert snapshots[0] == snapshots[1]
