from __future__ import annotations

from pathlib import Path

import pytest
from studio_contracts.agent_identity import HARNESS_IDENTITY_ALIASES

from tests.core_neutrality import core_neutrality_source


@pytest.fixture
def identity_module(tmp_path: Path) -> Path:
    path = tmp_path / "packages/studio-contracts/src/studio_contracts/agent_identity.py"
    path.parent.mkdir(parents=True)
    return path


def test_masks_only_identity_table_preserving_other_literals(
    tmp_path: Path, identity_module: Path
) -> None:
    outside = '\nif harness == "opencode":\n    provider = "anthropic"\n'
    source = f"HARNESS_IDENTITY_ALIASES = {HARNESS_IDENTITY_ALIASES!r}" + outside
    identity_module.write_text(source, encoding="utf-8")
    result = core_neutrality_source(identity_module, tmp_path)
    assert result.strip() == outside.strip()
    assert result.count("\n") == source.count("\n")


@pytest.mark.parametrize("alteration", ["value", "extra", "duplicate", "shared"])
def test_rejects_changed_or_ambiguous_identity_tables(
    tmp_path: Path, identity_module: Path, alteration: str
) -> None:
    aliases = dict(HARNESS_IDENTITY_ALIASES)
    if alteration == "value":
        aliases["codex-cli"] = "custom"
    elif alteration == "extra":
        aliases["custom-cli"] = "custom"
    assignment = f"HARNESS_IDENTITY_ALIASES = {aliases!r}\n"
    if alteration == "duplicate":
        assignment += assignment
    elif alteration == "shared":
        assignment = assignment.replace(" = ", " = OTHER_TABLE = ", 1)
    identity_module.write_text(assignment, encoding="utf-8")
    with pytest.raises(AssertionError):
        core_neutrality_source(identity_module, tmp_path)


def test_does_not_mask_tables_in_another_module(tmp_path: Path) -> None:
    path = tmp_path / "other.py"
    source = f"HARNESS_IDENTITY_ALIASES = {HARNESS_IDENTITY_ALIASES!r}\n"
    path.write_text(source, encoding="utf-8")
    assert core_neutrality_source(path, tmp_path) == source
