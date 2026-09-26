"""Dogfood chains (§23, §24) on stand-in harnesses and an isolated home: the
configuration a real tool would read, end to end, without touching the
machine running the suite."""

from __future__ import annotations

import json
from pathlib import Path

from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessPreviewRequest,
    HarnessVerifyRequest,
    VerifyState,
)

from tests.harness.support import MCP_URL, WORKSPACE_ID, Rig, make_rig


def _configure(rig: Rig, adapter_id: str) -> None:
    preview = rig.service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter_id)
    )
    result = rig.service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )
    assert result.state.value == "configured"


def test_dogfood_scenario_ia_to_studios_workspace_setup(tmp_path: Path) -> None:
    """§23: an AI tool is given its own Studi'OS machine and calls MCP with it."""
    calls: list[tuple[str, str]] = []

    def probe(url: str, token: str) -> tuple[str | None, int | None]:
        calls.append((url, token))
        return None, 200

    rig = make_rig(tmp_path, mcp_probe=probe)
    _configure(rig, "claude-code")
    entry = rig.user_entry("claude-code")
    assert entry is not None
    assert entry["url"] == MCP_URL
    [machine_id] = rig.provisioner.active
    token = rig.provisioner.tokens[machine_id]
    assert entry["headers"] == {"Authorization": f"Bearer {token}"}

    result = rig.service.verify(
        HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    assert result.state is VerifyState.VERIFIED
    assert calls == [(MCP_URL, token)]
    assert token not in result.model_dump_json()


def test_dogfood_opencode_configuration(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    _configure(rig, "opencode")
    config = json.loads(rig.opencode_config.read_text(encoding="utf-8"))
    entry = config["mcp"]["studio-os"]
    assert entry["url"] == MCP_URL
    assert entry["enabled"] is True
    assert entry["headers"]["Authorization"].startswith("Bearer sk_test_")


def test_dogfood_studios_to_studios_temp_clone(tmp_path: Path) -> None:
    """§24: both tools on a Studi'OS clone, each with its own machine, and the
    clone itself left untouched."""
    rig = make_rig(tmp_path)
    (rig.root / "README.md").write_text("# Studi'OS Clone\n", encoding="utf-8")
    for adapter_id in ("claude-code", "opencode"):
        _configure(rig, adapter_id)
    assert sorted(path.name for path in rig.root.iterdir()) == ["README.md"]
    assert len(rig.provisioner.active) == 2
    names = [name for _, name, _ in rig.provisioner.created]
    assert names == ["TEST-HOST · Claude Code", "TEST-HOST · OpenCode"]
    assert rig.user_entry("claude-code") != rig.user_entry("opencode")
