"""Parse actual projections, including the apostrophe case missed by snapshots."""

from __future__ import annotations

import hashlib
import shutil
import tomllib
from pathlib import Path

import pytest
from studio_client import cli
from studio_client.adapters import get_adapter
from studio_client.adapters.codex import _toml_string
from studio_client.adapters_check import check_adapters
from studio_client.canonical import build_offline_resolved, canonical_agent_keys


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


@pytest.mark.parametrize("key", canonical_agent_keys(Path(__file__).resolve().parents[2]))
def test_actual_codex_projection_parses_and_preserves_requirements(key: str) -> None:
    root = Path(__file__).resolve().parents[2]
    resolved = build_offline_resolved(root, key)
    result = get_adapter("codex").translate(resolved)
    data = tomllib.loads(result.artifacts[0].content)
    assert data["name"] == key
    assert data["description"] == resolved.agent.content["summary"]
    assert data["model_reasoning_effort"] == resolved.requirements.reasoning
    assert "model" not in data
    assert "adapter='codex'" in data["developer_instructions"]


def test_two_complete_generations_are_identical(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / ".agents", tmp_path / ".agents")
    snapshots = []
    for _ in range(2):
        for adapter_id in ("claude-code", "codex", "opencode"):
            for key in canonical_agent_keys(tmp_path):
                for artifact in (
                    get_adapter(adapter_id)
                    .translate(build_offline_resolved(tmp_path, key))
                    .artifacts
                ):
                    target = tmp_path / artifact.path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(artifact.content, encoding="utf-8")
        cli.main(["adapters", "sync", "--repo-root", str(tmp_path), "--overwrite"])
        result = check_adapters(tmp_path)
        assert result.checked == 84 and not result.failures
        snapshots.append(
            {
                p.relative_to(tmp_path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in tmp_path.rglob("*")
                if p.is_file() and ".studio-os" not in p.parts
            }
        )
    assert snapshots[0] == snapshots[1]
