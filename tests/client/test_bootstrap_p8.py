"""P8 multi-machine rebuild: A publishes a clean manifest, B rebuilds from it.

Two temporary checkouts simulate machines A and B; each has its own registry
directory (the machine-local project<->path mapping). The committed files must
stay clean of absolute paths and secrets, and a rebuild is idempotent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client import cli
from studio_client.bootstrap import BootstrapError
from studio_client.team_rebuild import rebuild, scan_committed_files
from studio_contracts.local.identity import ProfileRef

REPO = Path(__file__).resolve().parents[2]
PROFILE = ProfileRef(profile_id="dev-profile", server_origin="https://studio.example")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _machine_a(tmp_path: Path) -> Path:
    repo = tmp_path / "machine-a" / "demo"
    repo.mkdir(parents=True)
    shutil.copytree(REPO / ".agents", repo / ".agents")
    cli.main(
        [
            "bootstrap",
            "init",
            "--project-slug",
            "demo",
            "--project-name",
            "Demo",
            "--harness",
            "claude-code",
            "--repo-root",
            str(repo),
        ]
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    return repo


def _clone_b(a: Path, tmp_path: Path) -> Path:
    b = tmp_path / "machine-b" / "other-location" / "demo"
    b.mkdir(parents=True)
    shutil.copytree(a / ".agents", b / ".agents")
    _git(b, "init", "-q")
    _git(b, "add", "-A")
    return b


def test_scan_clean_on_committed_bundle(tmp_path: Path) -> None:
    assert scan_committed_files(_machine_a(tmp_path)) == []


def test_scan_flags_absolute_path_and_secret_without_echo(tmp_path: Path) -> None:
    repo = _machine_a(tmp_path)
    (repo / ".agents" / "leak.md").write_text(
        "see C:\\Users\\alice\\proj\nand /home/bob/x\n", encoding="utf-8"
    )
    (repo / ".agents" / "tok.md").write_text("sk-ant-api03-" + "a" * 40 + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    kinds = {(i.path, i.kind) for i in scan_committed_files(repo)}
    assert (".agents/leak.md", "absolute_path") in kinds
    assert (".agents/tok.md", "secret") in kinds


def test_b_rebuilds_from_manifest_with_local_mapping(tmp_path: Path) -> None:
    a = _machine_a(tmp_path)
    b = _clone_b(a, tmp_path)
    registry = tmp_path / "registry-b"
    project_id = uuid4()
    result = rebuild(b, registry, PROFILE, project_id)
    assert result.registration.action.value == "created"
    assert (b / "CLAUDE.md").is_file()
    assert result.written
    stored = json.loads(next(registry.glob("workspaces/*.json")).read_text(encoding="utf-8"))
    assert stored["roots"]["workspace_root"].replace("\\", "/").endswith("other-location/demo")
    # the mapping lives in the registry, never in the repository
    _git(b, "add", "-A")
    assert scan_committed_files(b) == []
    again = rebuild(b, registry, PROFILE, project_id)
    assert again.written == []
    assert again.registration.action.value == "unchanged"


def test_rebuild_refuses_unclean_shared_files(tmp_path: Path) -> None:
    a = _machine_a(tmp_path)
    (a / ".agents" / "leak.md").write_text("C:\\Users\\alice\\x\n", encoding="utf-8")
    _git(a, "add", "-A")
    with pytest.raises(BootstrapError, match="not clean"):
        rebuild(a, tmp_path / "registry", PROFILE, uuid4())
    assert not (tmp_path / "registry").exists()


def test_scan_cli_exit_code(tmp_path: Path) -> None:
    repo = _machine_a(tmp_path)
    cli.main(["bootstrap", "scan", "--repo-root", str(repo)])
    (repo / "AGENTS.md").write_text("/home/bob/x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    with pytest.raises(SystemExit) as exc:
        cli.main(["bootstrap", "scan", "--repo-root", str(repo)])
    assert exc.value.code == 1


def test_shared_repository_config_is_clean() -> None:
    """The real committed AI config never carries an absolute path or a secret."""
    assert scan_committed_files(REPO) == []
