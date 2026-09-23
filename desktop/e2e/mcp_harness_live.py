"""P12 live proof: real MCP HTTP, HarnessService verify, and Claude Code tool call."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import asyncpg
from studio_client.harness.backup import BackupStore
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.registry import HarnessRegistry
from studio_client.harness.service import HarnessService, WorkspaceInfo
from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessPreviewRequest,
    HarnessVerifyRequest,
    VerifyState,
)

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ID = UUID("738e442f-afaa-466f-975e-c5fb6bec61cf")
MCP_PORT = 18100
MCP_URL = f"http://127.0.0.1:{MCP_PORT}/mcp"


def wait_port(port: int, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as client:
            client.settimeout(0.25)
            if client.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.25)
    raise RuntimeError(f"port {port} did not become ready")


async def token_exists(database_url: str, token: str) -> bool:
    connection = await asyncpg.connect(
        database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    try:
        expected = sha256(token.encode()).hexdigest()
        return bool(
            await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM machines WHERE credential_hash = $1 "
                + "AND credential_revoked_at IS NULL)",
                expected,
            )
        )
    finally:
        await connection.close()


def main() -> int:
    gate = subprocess.Popen(
        ["uv", "run", "--all-packages", "python", "desktop/e2e/gate_stack.py"],
        cwd=ROOT,
        env=os.environ,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    mcp: subprocess.Popen[str] | None = None
    try:
        assert gate.stdout is not None
        ready_line = gate.stdout.readline()
        info = json.loads(ready_line)
        database_url = os.environ["STUDIO_GATE_PG_ADMIN_URL"].rsplit("/", 1)[0]
        mcp_env = {
            **os.environ,
            "STUDIO_DATABASE_URL": database_url.replace("postgresql://", "postgresql+asyncpg://")
            + f"/{info['database']}",
            "STUDIO_MCP_TRANSPORT": "streamable-http",
            "STUDIO_MCP_HOST": "127.0.0.1",
            "STUDIO_MCP_PORT": str(MCP_PORT),
        }
        if not __import__("asyncio").run(
            token_exists(mcp_env["STUDIO_DATABASE_URL"], info["machine_token"])
        ):
            raise RuntimeError("gate token is absent from the scratch database")
        api_request = urllib.request.Request(
            f"{info['api']}/api/v1/projects",
            headers={"Authorization": f"Bearer {info['machine_token']}"},
        )
        with urllib.request.urlopen(api_request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"gate API token preflight failed: {response.status}")
        print("PASS scratch database and API accept the machine token", flush=True)
        mcp = subprocess.Popen(
            ["uv", "run", "--all-packages", "python", "-m", "studio_mcp.server"],
            cwd=ROOT,
            env=mcp_env,
            stdout=None,
            stderr=None,
            text=True,
        )
        wait_port(MCP_PORT)
        if mcp.poll() is not None:
            raise RuntimeError(f"MCP server exited early: {mcp.returncode}")

        with tempfile.TemporaryDirectory(prefix="studio-p12-harness-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            harness_env = {
                **os.environ,
                "STUDIO_MCP_MACHINE_TOKEN": info["machine_token"],
            }
            service = HarnessService(
                HarnessRegistry([ClaudeCodeAdapter()]),
                BackupStore(root / "backups"),
                lambda workspace_id: WorkspaceInfo(
                    workspace_id, workspace, MCP_URL, workspace_id == WORKSPACE_ID
                ),
                env=lambda: harness_env,
                probe_cwd=workspace,
            )
            preview = service.preview(
                HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
            )
            applied = service.apply(
                HarnessApplyRequest(
                    plan_id=preview.plan_id,
                    plan_hash=preview.plan_hash,
                    confirmed=True,
                )
            )
            if applied.state.value != "configured":
                raise RuntimeError(f"harness apply state: {applied.state.value}")
            verified = service.verify(
                HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
            )
            if verified.state is not VerifyState.VERIFIED:
                raise RuntimeError(
                    f"harness verify state: {verified.state.value} "
                    f"{verified.details} {verified.error}"
                )
            print("PASS harness.verify VERIFIED against real MCP HTTP", flush=True)

            prompt = (
                "Call the studio-os MCP tool studio_prepare_context exactly once with "
                "project='desktop-gate', objective='P12 live Claude Code validation', "
                "include=['current_state'], and limit=3. Do not use any built-in tool. "
                "Then answer only P12_MCP_OK followed by the project slug returned."
            )
            completed = subprocess.run(
                [
                    "claude",
                    "-p",
                    prompt,
                    "--mcp-config",
                    str(workspace / ".mcp.json"),
                    "--strict-mcp-config",
                    "--allowedTools",
                    "mcp__studio-os__studio_prepare_context",
                    "--permission-mode",
                    "dontAsk",
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--no-session-persistence",
                    "--max-budget-usd",
                    "0.50",
                ],
                cwd=workspace,
                env=harness_env,
                capture_output=True,
                text=True,
                timeout=240,
            )
            transcript = completed.stdout
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Claude Code exited {completed.returncode}: "
                    f"{completed.stderr or transcript[-4000:]}"
                )
            if "studio_prepare_context" not in transcript or "P12_MCP_OK" not in transcript:
                raise RuntimeError("Claude Code transcript lacks the required MCP call/result")
            print("PASS Claude Code invoked studio_prepare_context through MCP", flush=True)
        return 0
    finally:
        if mcp is not None:
            subprocess.run(
                ["taskkill", "/PID", str(mcp.pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )
        if gate.stdin is not None:
            gate.stdin.close()
        try:
            gate.wait(timeout=30)
        except subprocess.TimeoutExpired:
            gate.kill()


if __name__ == "__main__":
    sys.exit(main())
