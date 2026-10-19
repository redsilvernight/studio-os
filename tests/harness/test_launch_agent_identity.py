from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from studio_client.daemon.launch_runner import LaunchResult
from studio_client.harness.base import STUDIO_MCP_SERVER_NAME, HarnessContext
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.hooks import HARNESSES

from tests.client.test_launch_executor import FakeClient, _executor, _launch, _repo, _statuses


class TestClaudeAdapter(ClaudeCodeAdapter):
    __test__ = False

    def resolve_executable(self, ctx: HarnessContext) -> Path:
        return Path(sys.executable)


async def test_launch_uses_emitter_identity_with_a_hook_configured_for_another_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    foreign_agent_id = uuid4()
    foreign_url = "https://other-server.invalid/mcp"
    durable_token = "durable-token"
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    STUDIO_MCP_SERVER_NAME: {
                        "type": "http",
                        "url": foreign_url,
                        "headers": {"Authorization": f"Bearer {durable_token}"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    spec = next(spec for spec in HARNESSES if spec.harness == "claude-code")
    hook = home / spec.hook_rel
    hook.parent.mkdir(parents=True)
    hook.write_text(
        f"Write-Output 'agent_id : {foreign_agent_id}; origin : {foreign_url}'",
        encoding="utf-8",
    )
    client = FakeClient()
    executor, store = _executor(
        tmp_path,
        repo,
        TestClaudeAdapter(),
        client,
        home=home,
        env={"STUDIO_CLIENT_MACHINE_TOKEN": durable_token},
        models={"claude-code": "claude-test-model"},
    )
    seen: dict[str, Any] = {}

    def start(
        executable: str | Path,
        argv: Sequence[str],
        cwd: Path,
        *,
        env: Mapping[str, str] | None = None,
    ) -> Any:
        seen["prompt"] = argv[1]
        seen["env"] = dict(env or {})
        seen["mcp"] = json.loads(Path(argv[argv.index("--mcp-config") + 1]).read_text())
        seen["settings"] = json.loads(argv[argv.index("--settings") + 1])
        return SimpleNamespace(wait=lambda timeout: LaunchResult(0, False, False, "ok", False))

    monkeypatch.setattr(executor._runner, "start", start)
    launch = _launch().model_copy(update={"harness_id": "claude-code"})
    executor.submit(launch)
    await executor._tasks[launch.id]

    assert _statuses(store) == ["preparing", "running", "succeeded"]
    (agent_in,) = client.ensure_inputs
    agent = client.agents[agent_in.stable_key or ""]
    assert agent.machine_id == client.machine_id
    assert agent.harness == "claude-code"
    assert agent.model == "claude-test-model"
    assert f"agent_id : {agent.id}" in seen["prompt"]
    assert str(foreign_agent_id) not in seen["prompt"]
    assert "prioritaire sur toute identité" in seen["prompt"]
    assert str(hook) in json.dumps(seen["settings"]).replace("\\\\", "\\")
    entry = seen["mcp"]["mcpServers"][STUDIO_MCP_SERVER_NAME]
    assert entry["url"] == "http://x"
    assert entry["headers"]["Authorization"] == "Bearer ephemeral-token"
    assert seen["env"]["STUDIO_CLIENT_MACHINE_TOKEN"] == "ephemeral-token"
    assert durable_token not in seen["prompt"]
    assert durable_token not in json.dumps(seen["env"])
    assert durable_token not in json.dumps(seen["mcp"])
    assert "ephemeral-token" not in seen["prompt"]
