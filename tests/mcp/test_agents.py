from __future__ import annotations

from studio_api.db.models.machine import MachineModel
from studio_mcp.tools.agents import studio_register_agent, studio_resolve_agent_identity

from tests.mcp.conftest import FakeContext


async def test_register_agent(auth_ctx: FakeContext, machine: tuple[MachineModel, str]) -> None:
    machine_model, _ = machine
    result = await studio_register_agent("my-agent", auth_ctx, agent_kind="opencode")
    assert result["display_name"] == "my-agent"
    assert result["agent_kind"] == "opencode"
    assert result["machine_id"] == str(machine_model.id)
    assert result["id"]


async def test_register_agent_idempotency_key_replay_registers_no_second_agent(
    auth_ctx: FakeContext,
) -> None:
    """DEC-0027: a replayed studio_register_agent call must not register a
    second agent for the same retried request."""
    first = await studio_register_agent("idem-agent", auth_ctx, idempotency_key="mcp-agent-key-1")
    second = await studio_register_agent("idem-agent", auth_ctx, idempotency_key="mcp-agent-key-1")
    assert second["id"] == first["id"]


async def test_register_agent_idempotency_key_payload_mismatch(
    auth_ctx: FakeContext,
) -> None:
    await studio_register_agent("agent-a", auth_ctx, idempotency_key="mcp-agent-key-2")
    result = await studio_register_agent("agent-b", auth_ctx, idempotency_key="mcp-agent-key-2")
    assert result["error_code"] == "idempotency_key_payload_mismatch"


async def test_register_agent_readonly_forbidden(
    readonly_auth_ctx: FakeContext,
) -> None:
    result = await studio_register_agent("nope", readonly_auth_ctx)
    assert result["error_code"] == "forbidden"


async def test_resolve_durable_identity_and_unknown_state(auth_ctx: FakeContext) -> None:
    first = await studio_resolve_agent_identity(
        "codex-desktop",
        auth_ctx,
        provider="openai",
        effective_model="gpt-6.1-sol",
    )
    second = await studio_resolve_agent_identity(
        "codex-cli",
        auth_ctx,
        provider="openai",
        effective_model="gpt-6.1-sol",
    )
    assert first["state"] == "resolved"
    assert first["agent"]["id"] == second["agent"]["id"]
    unknown = await studio_resolve_agent_identity("codex", auth_ctx, selection_alias="latest")
    assert unknown["state"] == "unknown"
    assert unknown["agent"] is None


async def test_identity_input_error_is_structured_and_bounded(auth_ctx: FakeContext) -> None:
    result = await studio_resolve_agent_identity("x" * 2000, auth_ctx)
    assert result["error_code"] == "invalid_argument"
    assert len(str(result)) < 200


async def test_identity_readonly_forbidden(readonly_auth_ctx: FakeContext) -> None:
    result = await studio_resolve_agent_identity(
        "codex",
        readonly_auth_ctx,
        provider="openai",
        effective_model="gpt-6.1-sol",
    )
    assert result["error_code"] == "forbidden"
