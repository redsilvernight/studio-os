"""`agents ensure` (workflow W2): the session-start hook finds this machine's
harness agent or registers it (CC-1/DEC-0045, public registration without
authority; DEC-0053 metadata echoed verbatim), so `studio_start_session` and
`studio_log_ai_work` receive a stable `agent_id` instead of null."""

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
from studio_client.tokens import MemoryTokenStore
from studio_contracts.auth import AgentCreate

MACHINE_ID = uuid4()
OTHER_MACHINE_ID = uuid4()
AGENT_ID = uuid4()
NOW = "2026-09-24T20:00:00Z"


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
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _machine_payload(machine_id: Any = MACHINE_ID) -> dict[str, Any]:
    return {
        "id": str(machine_id),
        "owner_user_id": str(uuid4()),
        "display_name": "test-machine",
        "last_seen_at": None,
        "status": "online",
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _client(handler: Any) -> StudioApiClient:
    return StudioApiClient(_config(), _token_store(), transport=httpx.MockTransport(handler))


def _agent_in() -> AgentCreate:
    return AgentCreate(display_name="studio-opencode", harness="opencode")


async def test_ensure_returns_existing_without_post() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/api/v1/machines/me":
            return httpx.Response(200, json=_machine_payload())
        assert request.url.path == "/api/v1/agents"
        assert request.method == "GET"
        return httpx.Response(200, json=[_agent_payload()])

    async with _client(handler) as client:
        agent, created = await client.ensure_agent(_agent_in(), idempotency_key="k1")
    assert created is False
    assert agent.id == AGENT_ID
    assert "POST /api/v1/agents" not in calls


async def test_ensure_registers_when_absent() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/machines/me":
            return httpx.Response(200, json=_machine_payload())
        if request.method == "GET":
            return httpx.Response(200, json=[])
        assert request.url.path == "/api/v1/agents"
        seen["idempotency_key"] = request.headers.get("Idempotency-Key", "")
        body = json.loads(request.content.decode())
        assert body["display_name"] == "studio-opencode"
        assert body["harness"] == "opencode"
        return httpx.Response(201, json=_agent_payload())

    async with _client(handler) as client:
        agent, created = await client.ensure_agent(_agent_in(), idempotency_key="stable-k")
    assert created is True
    assert agent.id == AGENT_ID
    assert seen["idempotency_key"] == "stable-k"


async def test_ensure_ignores_other_machines_agents() -> None:
    posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.url.path == "/api/v1/machines/me":
            return httpx.Response(200, json=_machine_payload())
        if request.method == "GET":
            return httpx.Response(200, json=[_agent_payload(machine_id=OTHER_MACHINE_ID)])
        posts += 1
        return httpx.Response(201, json=_agent_payload())

    async with _client(handler) as client:
        _, created = await client.ensure_agent(_agent_in(), idempotency_key="k2")
    assert created is True
    assert posts == 1


async def test_ensure_ignores_harness_mismatch() -> None:
    posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.url.path == "/api/v1/machines/me":
            return httpx.Response(200, json=_machine_payload())
        if request.method == "GET":
            return httpx.Response(
                200, json=[_agent_payload(harness="claude-code", display_name="studio-x")]
            )
        posts += 1
        return httpx.Response(201, json=_agent_payload())

    async with _client(handler) as client:
        _, created = await client.ensure_agent(_agent_in(), idempotency_key="k3")
    assert created is True
    assert posts == 1


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

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/machines/me":
            return httpx.Response(200, json=_machine_payload())
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json=_agent_payload())

    def fake_run(config: ClientConfig, action: Any) -> Any:
        async def _go() -> Any:
            async with _client(handler) as client:
                return await action(client)

        return asyncio.run(_go())

    monkeypatch.setattr(cli, "_run", fake_run)
    cli.main(["agents", "ensure", "--harness", "opencode"])
    out = capsys.readouterr().out
    assert f"Registered agent {AGENT_ID} (studio-opencode)." in out
