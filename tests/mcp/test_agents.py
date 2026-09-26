from __future__ import annotations

from studio_api.db.models.machine import MachineModel
from studio_mcp.tools.agents import studio_register_agent

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
