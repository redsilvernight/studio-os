from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.opencode import OpenCodeAdapter
from studio_client.tokens import (
    EnvTokenStore,
    MissingMachineToken,
    resolve_token,
)
from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessPreviewRequest,
    HarnessVerifyRequest,
    VerifyState,
)

from tests.harness.support import MCP_URL, WORKSPACE_ID, Rig, make_rig


def test_env_token_store_is_read_only_and_fails_on_write():
    """EnvTokenStore must not allow writes - it's a CI/headless override only."""
    store = EnvTokenStore()
    with pytest.raises(NotImplementedError):
        store.set_token("https://example.com", "token")
    with pytest.raises(NotImplementedError):
        store.clear_token("https://example.com")


def test_token_missing_is_a_distinct_state_without_error():
    """TOKEN_MISSING is neither CONFIGURED nor VERIFIED and, like CONFIGURED,
    reports a condition rather than a failure: it carries no error."""
    from pydantic import ValidationError
    from studio_contracts.local.common import ComponentId, LocalError, LocalErrorCode
    from studio_contracts.local.harness import HarnessVerifyResult

    result = HarnessVerifyResult(
        adapter_id="claude-code",
        state=VerifyState.TOKEN_MISSING,
        mcp_url=MCP_URL,
        details={"reason": "token_missing"},
    )
    assert result.state.value == "token_missing"
    assert result.state not in (VerifyState.CONFIGURED, VerifyState.VERIFIED)
    with pytest.raises(ValidationError):
        HarnessVerifyResult(
            adapter_id="claude-code",
            state=VerifyState.TOKEN_MISSING,
            mcp_url=MCP_URL,
            error=LocalError(
                code=LocalErrorCode.INTERNAL_ERROR,
                message="x",
                component=ComponentId.HARNESS,
                retryable=False,
            ),
        )


def test_env_token_store_respects_origin_binding():
    """EnvTokenStore with ORIGIN_VAR only returns token for matching origin."""
    os.environ["STUDIO_CLIENT_MACHINE_TOKEN"] = "test-token"
    os.environ["STUDIO_CLIENT_MACHINE_TOKEN_ORIGIN"] = "https://studio.example.com"
    try:
        store = EnvTokenStore()
        assert store.get_token("https://studio.example.com") == "test-token"
        assert store.get_token("https://other.example.com") is None
    finally:
        os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN", None)
        os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN_ORIGIN", None)


def test_env_token_store_without_origin_var_returns_for_all():
    """EnvTokenStore without ORIGIN_VAR returns token for any origin."""
    os.environ["STUDIO_CLIENT_MACHINE_TOKEN"] = "test-token"
    try:
        store = EnvTokenStore()
        assert store.get_token("https://studio.example.com") == "test-token"
        assert store.get_token("https://other.example.com") == "test-token"
    finally:
        os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN", None)


def test_resolve_token_prefers_env_override():
    """resolve_token checks EnvTokenStore first, then KeyringTokenStore."""
    os.environ["STUDIO_CLIENT_MACHINE_TOKEN"] = "env-token"
    try:

        class FakeKeyring:
            def get_token(self, origin: str) -> str | None:
                return "keyring-token"

        token = resolve_token("https://example.com", stores=[FakeKeyring()])
        assert token == "env-token"
    finally:
        os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN", None)


def test_resolve_token_falls_back_to_keyring():
    """resolve_token falls back to keyring when env not set."""
    os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN", None)

    class FakeKeyring:
        def get_token(self, origin: str) -> str | None:
            return "keyring-token"

    token = resolve_token("https://example.com", stores=[FakeKeyring()])
    assert token == "keyring-token"


def test_resolve_token_raises_when_missing():
    """resolve_token raises MissingMachineToken when no store has token."""
    os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN", None)

    class EmptyStore:
        def get_token(self, origin: str) -> str | None:
            return None

    with pytest.raises(MissingMachineToken):
        resolve_token("https://example.com", stores=[EmptyStore()])


def _configure(rig: Rig, adapter_id: str) -> None:
    preview = rig.service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter_id)
    )
    rig.service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )


def _verify(rig: Rig, adapter_id: str):
    return rig.service.verify(
        HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter_id)
    )


@pytest.mark.parametrize("adapter_id", ["claude-code", "opencode"], ids=["claude", "opencode"])
def test_an_env_reference_left_by_an_older_setup_is_token_missing(
    adapter_id: str, tmp_path: Path
) -> None:
    """Scenario B: an entry that still relies on an environment variable the
    tool may not have is TOKEN_MISSING — neither CONFIGURED nor VERIFIED."""
    rig = make_rig(tmp_path, mcp_probe=lambda url, token: pytest.fail("never probed"))
    if adapter_id == "claude-code":
        path, container = rig.claude_config, "mcpServers"
        reference = "Bearer ${STUDIO_MCP_MACHINE_TOKEN}"
    else:
        path, container = rig.opencode_config, "mcp"
        reference = "Bearer {env:STUDIO_MCP_MACHINE_TOKEN}"
        path.parent.mkdir(parents=True)
    entry = {"type": "http", "url": MCP_URL, "headers": {"Authorization": reference}}
    path.write_text(json.dumps({container: {"studio-os": entry}}), encoding="utf-8")
    result = _verify(rig, adapter_id)
    assert result.state is VerifyState.TOKEN_MISSING
    assert result.error is None
    assert result.details.get("reason") == "token_reference"
    assert result.mcp_url == MCP_URL


@pytest.mark.parametrize("adapter_id", ["claude-code", "opencode"], ids=["claude", "opencode"])
def test_configured_is_not_verified_without_a_backend(adapter_id: str, tmp_path: Path) -> None:
    """CONFIGURED != VERIFIED: VERIFIED means an MCP call succeeded."""
    rig = make_rig(tmp_path, mcp_probe=lambda url, token: ("mcp_unreachable", None))
    _configure(rig, adapter_id)
    result = _verify(rig, adapter_id)
    assert result.state is VerifyState.FAILED
    assert result.mcp_url == MCP_URL
    assert result.error is not None
    assert result.details == {"reason": "mcp_unreachable"}


@pytest.mark.parametrize("adapter_id", ["claude-code", "opencode"], ids=["claude", "opencode"])
def test_a_refused_credential_is_reported_without_the_credential(
    adapter_id: str, tmp_path: Path
) -> None:
    rig = make_rig(tmp_path, mcp_probe=lambda url, token: ("mcp_unauthorized", 401))
    _configure(rig, adapter_id)
    [machine_id] = rig.provisioner.active
    result = _verify(rig, adapter_id)
    assert result.state is VerifyState.FAILED
    assert result.details == {"reason": "mcp_unauthorized", "http_status": "401"}
    assert rig.provisioner.tokens[machine_id] not in result.model_dump_json()


def test_the_entry_carries_the_dedicated_credential_itself():
    """DEC-0104 §2: a tool launched on its own must authenticate, so its entry
    holds its own credential rather than a reference to an environment variable."""
    for adapter in (ClaudeCodeAdapter(), OpenCodeAdapter()):
        entry = adapter.build_entry(MCP_URL, "sk_dedicated")
        assert entry["headers"] == {"Authorization": "Bearer sk_dedicated"}
        assert "STUDIO_MCP_MACHINE_TOKEN" not in json.dumps(entry)


def test_daemon_identity_view_reports_token_status(tmp_path: Path):
    """The daemon's identity_view reports whether machine token is in keyring."""
    from studio_client.config import ClientConfig
    from studio_client.daemon.service import DaemonController
    from studio_contracts.local.identity import SecretStatus

    controller = DaemonController(
        ClientConfig(
            api_base_url="https://studio.example/api/v1",
            profile_id="test",
            machine_id=WORKSPACE_ID,
        ),
        data_root=tmp_path,
    )
    view = controller.identity_view()
    # Should report ABSENT or KEYRING_UNAVAILABLE (no token set in test)
    assert len(view.secrets) == 1
    assert view.secrets[0].reference.kind.value == "machine_credential"
    assert view.secrets[0].status in (SecretStatus.ABSENT, SecretStatus.KEYRING_UNAVAILABLE)


def test_token_only_ever_lives_in_the_tool_config(tmp_path: Path):
    """The dedicated credential is in the target file and nowhere else: not in
    the workspace, backups, ledger, plan, apply or verify results."""
    rig = make_rig(tmp_path, mcp_probe=lambda url, token: (None, 200))
    rig.env["STUDIO_MCP_MACHINE_TOKEN"] = "SECRET-TOKEN-VALUE-12345"
    preview = rig.service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    applied = rig.service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )
    verified = _verify(rig, "claude-code")
    [machine_id] = rig.provisioner.active
    token = rig.provisioner.tokens[machine_id]

    assert token in rig.claude_config.read_text(encoding="utf-8")
    assert "SECRET-TOKEN" not in rig.claude_config.read_text(encoding="utf-8")
    for result in (preview, applied, verified):
        assert token not in result.model_dump_json()
    for root in (rig.root, rig.backups_root, tmp_path / "state"):
        for path in root.rglob("*"):
            if path.is_file():
                assert token not in path.read_text(encoding="utf-8", errors="replace"), path
    assert all(token not in " ".join(call) for call in rig.cli.calls)
