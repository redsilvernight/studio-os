"""`agents ensure` (workflow W2, AIB-I): the session-start hook finds this
machine's harness agent or registers it through `POST /agents/ensure`
(CC-1/DEC-0045, public registration without authority; DEC-0053 metadata
echoed verbatim), so `studio_start_session` and `studio_log_ai_work` receive
a stable `agent_id` instead of null. The server matches on the local stable
key (`agents-ensure-{harness}` by default), scoped to the calling machine —
never on `(harness, display_name)` — so a retried hook registers no
duplicate."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from studio_client import cli
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.errors import StudioApiError
from studio_client.tokens import MemoryTokenStore
from studio_contracts.auth import AgentCreate

MACHINE_ID = uuid4()
OTHER_MACHINE_ID = uuid4()
AGENT_ID = uuid4()
NOW = "2026-09-24T20:00:00Z"
STABLE_KEY = "agents-ensure-opencode"


def _config() -> ClientConfig:
    return ClientConfig(
        api_base_url="http://test",
        max_attempts=3,
        backoff_initial=0.001,
        backoff_max=0.002,
    )


def _token_store() -> MemoryTokenStore:
    store = MemoryTokenStore()
    store.set_token("http://test", "test-token")
    return store


def _agent_payload(
    agent_id: Any = AGENT_ID,
    machine_id: Any = MACHINE_ID,
    display_name: str = "studio-opencode",
    harness: str | None = "opencode",
    stable_key: str | None = STABLE_KEY,
) -> dict[str, Any]:
    return {
        "id": str(agent_id),
        "machine_id": str(machine_id),
        "display_name": display_name,
        "agent_kind": "",
        "agent_profile": None,
        "harness": harness,
        "provider": None,
        "model": None,
        "stable_key": stable_key,
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _ensure_payload(created: bool, **overrides: Any) -> dict[str, Any]:
    return {"agent": _agent_payload(**overrides), "created": created}


def _client(handler: Any) -> StudioApiClient:
    return StudioApiClient(_config(), _token_store(), transport=httpx.MockTransport(handler))


def _agent_in(**overrides: Any) -> AgentCreate:
    fields: dict[str, Any] = {
        "display_name": "studio-opencode",
        "harness": "opencode",
        "stable_key": STABLE_KEY,
    }
    fields.update(overrides)
    return AgentCreate(**fields)


async def test_ensure_registers_when_absent() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/agents/ensure"
        assert request.method == "POST"
        body = json.loads(request.content.decode())
        assert body["display_name"] == "studio-opencode"
        assert body["harness"] == "opencode"
        assert body["stable_key"] == STABLE_KEY
        seen["idempotency"] = request.headers.get("Idempotency-Key", "")
        return httpx.Response(201, json=_ensure_payload(True))

    async with _client(handler) as client:
        agent, created = await client.ensure_agent(_agent_in())
    assert created is True
    assert agent.id == AGENT_ID
    assert agent.stable_key == STABLE_KEY
    assert seen["idempotency"] == ""


async def test_ensure_returns_found_agent() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        assert request.url.path == "/api/v1/agents/ensure"
        return httpx.Response(200, json=_ensure_payload(False))

    async with _client(handler) as client:
        agent, created = await client.ensure_agent(_agent_in())
    assert created is False
    assert agent.id == AGENT_ID
    assert calls == ["POST /api/v1/agents/ensure"]


async def test_ensure_mismatch_raises_explicit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409, json={"detail": {"error_code": "idempotency_key_payload_mismatch"}}
        )

    async with _client(handler) as client:
        with pytest.raises(StudioApiError) as exc:
            await client.ensure_agent(_agent_in(display_name="renamed"))
    assert exc.value.error_code == "idempotency_key_payload_mismatch"


async def test_ensure_without_stable_key_registers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["stable_key"] is None
        return httpx.Response(201, json=_ensure_payload(True, stable_key=None))

    async with _client(handler) as client:
        agent, created = await client.ensure_agent(
            AgentCreate(display_name="studio-opencode", harness="opencode")
        )
    assert created is True
    assert agent.stable_key is None


async def test_list_and_register_agents() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/agents" and request.method == "GET":
            return httpx.Response(200, json=[_agent_payload()])
        assert request.headers.get("Idempotency-Key") == "k4"
        return httpx.Response(201, json=_agent_payload(agent_id=uuid4()))

    async with _client(handler) as client:
        agents = await client.list_agents()
        assert [a.id for a in agents] == [AGENT_ID]
        agent = await client.register_agent(_agent_in(), idempotency_key="k4")
        assert agent.display_name == "studio-opencode"


def test_cli_agents_ensure_registers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "http://test")
    monkeypatch.setenv("STUDIO_CLIENT_MACHINE_TOKEN", "test-token")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/agents/ensure"
        seen.update(json.loads(request.content.decode()))
        return httpx.Response(201, json=_ensure_payload(True))

    def fake_run(config: ClientConfig, action: Any) -> Any:
        async def _go() -> Any:
            async with _client(handler) as client:
                return await action(client)

        return asyncio.run(_go())

    monkeypatch.setattr(cli, "_run", fake_run)
    cli.main(["agents", "ensure", "--harness", "opencode"])
    out = capsys.readouterr().out
    assert f"Registered agent {AGENT_ID} (studio-opencode)." in out
    assert seen["stable_key"] == "agents-ensure-opencode"


def test_cli_agents_ensure_finds_existing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "http://test")
    monkeypatch.setenv("STUDIO_CLIENT_MACHINE_TOKEN", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ensure_payload(False))

    def fake_run(config: ClientConfig, action: Any) -> Any:
        async def _go() -> Any:
            async with _client(handler) as client:
                return await action(client)

        return asyncio.run(_go())

    monkeypatch.setattr(cli, "_run", fake_run)
    cli.main(["agents", "ensure", "--harness", "opencode", "--stable-key", "custom-key"])
    out = capsys.readouterr().out
    assert f"Found agent {AGENT_ID} (studio-opencode)." in out
