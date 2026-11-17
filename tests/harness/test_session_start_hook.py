"""Hook `session-start` (DEC-0099) : le harnais détecté ne doit jamais venir
d'une variable de credential ou d'une variable Studio OS.

Studio OS exporte `OPENCODE_STUDIO_OS_TOKEN` / `OPENCODE_STUDIO_OS_DEV_TOKEN`
au niveau utilisateur, donc présentes dans toute session : un match `OPENCODE*`
brut faisait passer une session Claude Code pour OpenCode et demandait
`agents ensure --harness opencode`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "nt" or shutil.which("pwsh") is None,
    reason="hook PowerShell (pwsh) exécuté sous Windows uniquement",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "library" / "studio" / "hooks" / "session-start.ps1"

# Variables héritées du poste qui pourraient fausser la détection.
_HARNESS_PREFIXES = ("OPENCODE", "CODEX_", "CLAUDECODE")
_DROPPED = {
    "STUDIO_CLIENT_CHANNEL",
    "STUDIO_CLIENT_API_BASE_URL",
    "STUDIO_MCP_MACHINE_TOKEN",
}


def _install_studio_client(bin_dir: Path) -> Path:
    """Un `studio-client` factice : enregistre ses arguments, rend un agent."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    record = "%STUDIO_TEST_RECORD%"
    lines = [
        "@echo off",
        f'echo %*>>"{record}"',
        'echo {"id":"agent-test","severity":"info"}',
        "exit /b 0",
    ]
    path = bin_dir / "studio-client.cmd"
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return path


def _write_workspace(appdata: Path, workspace_root: Path) -> None:
    workspaces = appdata / "StudioOS" / "workspaces"
    workspaces.mkdir(parents=True)
    (workspaces / "ws.json").write_text(
        json.dumps(
            {
                "project_id": "prj_test",
                "roots": {"workspace_root": str(workspace_root), "repo_roots": []},
                "profile": {"server_origin": "https://studio.example"},
            }
        ),
        encoding="utf-8",
    )


def _run_hook(
    tmp_path: Path, extra_env: dict[str, str]
) -> tuple[str, subprocess.CompletedProcess[str]]:
    bin_dir = tmp_path / "bin"
    _install_studio_client(bin_dir)
    appdata = tmp_path / "appdata"
    _write_workspace(appdata, REPO_ROOT)
    record = tmp_path / "studio-client.log"

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(_HARNESS_PREFIXES) and key.upper() not in _DROPPED
    }
    env["PATH"] = os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
    env["APPDATA"] = str(appdata)
    env["STUDIO_TEST_RECORD"] = str(record)
    env.update(extra_env)

    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(SCRIPT)],
        input=json.dumps({"cwd": str(REPO_ROOT)}),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    calls = record.read_text(encoding="utf-8") if record.exists() else ""
    return calls, result


@pytest.mark.parametrize(
    "extra_env",
    [
        {"OPENCODE_STUDIO_OS_TOKEN": "tok-a", "OPENCODE_STUDIO_OS_DEV_TOKEN": "tok-b"},
        {
            "OPENCODE_STUDIO_OS_TOKEN": "tok-a",
            "OPENCODE_STUDIO_OS_DEV_TOKEN": "tok-b",
            "OPENCODE_STUDIO_OS": "1",
        },
    ],
    ids=["only-tokens", "only-studio-os-vars"],
)
def test_opencode_credential_vars_do_not_imply_opencode(
    tmp_path: Path, extra_env: dict[str, str]
) -> None:
    calls, result = _run_hook(tmp_path, extra_env)
    assert result.returncode == 0, result.stderr
    assert "--harness claude-code" in calls
    assert "--harness opencode" not in calls
    assert "agent_id=agent-test" in result.stdout


def test_real_opencode_marker_selects_opencode(tmp_path: Path) -> None:
    calls, result = _run_hook(
        tmp_path,
        {
            "OPENCODE_STUDIO_OS_TOKEN": "tok-a",
            "OPENCODE_STUDIO_OS_DEV_TOKEN": "tok-b",
            "OPENCODE": "1",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "--harness opencode" in calls
    assert "--harness claude-code" not in calls


def test_codex_markers_still_win_and_tokens_are_ignored(tmp_path: Path) -> None:
    calls, result = _run_hook(tmp_path, {"CODEX_HOME": str(tmp_path / "codex")})
    assert result.returncode == 0, result.stderr
    assert "--harness codex" in calls

    other = tmp_path / "other"
    other.mkdir()
    calls, result = _run_hook(other, {"CODEX_STUDIO_OS_TOKEN": "tok-c"})
    assert result.returncode == 0, result.stderr
    assert "--harness claude-code" in calls
