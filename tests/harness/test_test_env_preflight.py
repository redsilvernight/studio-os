from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "nt" or shutil.which("pwsh") is None, reason="Windows PowerShell preflight"
)
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "test-env.ps1"


def _run(prefix: str, arguments: str = "") -> subprocess.CompletedProcess[str]:
    script = str(SCRIPT).replace("'", "''")
    command = f"{prefix}\n& '{script}' {arguments}; exit $LASTEXITCODE"
    return subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_check_does_not_start_docker_when_infrastructure_is_offline() -> None:
    result = _run(
        "function docker { throw 'unexpected-docker' }; "
        "function Start-Process { throw 'unexpected-start' }; "
        "function Invoke-WebRequest { throw 'intentional-offline' }"
    )
    assert result.returncode == 2
    assert "environment_unavailable" in result.stderr
    assert "intentional-offline" in result.stderr
    assert "unexpected" not in result.stderr
    assert "ready:" not in result.stdout


def test_explicit_start_refuses_low_commit_headroom_without_starting_processes() -> None:
    result = _run(
        "function docker { $global:LASTEXITCODE=1 }; "
        "function Get-CimInstance { [pscustomobject]@{CommitLimit=16GB; "
        "CommittedBytes=15GB; AvailableMBytes=8192} }; "
        "function Start-Process { throw 'unexpected-start' }",
        "-StartServices -DatabaseUrl 'postgresql+asyncpg://studio@127.0.0.1:5432/studio_os_test' "
        "-StorageEndpoint 'http://127.0.0.1:9000'",
    )
    assert result.returncode == 2
    assert "Insufficient memory headroom" in result.stderr
    assert "unexpected-start" not in result.stderr


def test_migration_rejects_non_test_remote_database_before_any_probe() -> None:
    result = _run(
        "function Invoke-WebRequest { throw 'unexpected-network' }",
        "-Migrate -DatabaseUrl 'postgresql+asyncpg://studio@example.test/production'",
    )
    assert result.returncode == 2
    assert "local test database" in result.stderr
    assert "unexpected-network" not in result.stderr


def test_database_probe_has_a_real_deadline() -> None:
    result = _run(
        "function Invoke-WebRequest { [pscustomobject]@{StatusCode=200} }",
        "-DatabaseUrl 'postgresql+asyncpg://studio@127.0.0.1:1/studio_os_test' -TimeoutSeconds 1",
    )
    assert result.returncode == 2
    assert "environment_unavailable" in result.stderr
    assert "ready:" not in result.stdout
