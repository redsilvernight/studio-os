"""`setup-hooks` (workflow W2b): versioned session-start hooks deployable on
a fresh machine — pure local deployment, no server, no secret written, user
account configs never touched (DEC-0096 boundary). No DB needed."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from studio_client import cli
from studio_client.config import default_config_path
from studio_client.hooks import (
    AGENT_STORE_REL,
    HARNESSES,
    MANAGED_MARKER,
    deploy_hooks,
    detect_harnesses,
    is_managed,
    render_hook,
)

_SPECS = {spec.harness: spec for spec in HARNESSES}
_PS = shutil.which("pwsh") or shutil.which("powershell")


def test_render_has_no_unsubstituted_placeholder() -> None:
    for spec in HARNESSES:
        rendered = render_hook(spec)
        assert MANAGED_MARKER in rendered
        assert spec.harness in rendered
        assert spec.agent_key in rendered
        for token in ("__HARNESS__", "__AGENT_KEY__", "__OUTPUT__", "__MANAGED_MARKER__"):
            assert token not in rendered


def test_render_outputs_differ_per_harness() -> None:
    assert "'json'" in render_hook(_SPECS["claude-code"])
    assert "'text'" in render_hook(_SPECS["opencode"])
    assert "'text'" in render_hook(_SPECS["codex"])


def test_codex_spec() -> None:
    spec = _SPECS["codex"]
    assert spec.agent_key == "codex"
    assert spec.hook_rel == Path(".codex") / "studio-session-start-codex.ps1"
    assert ".codex/config.toml" in spec.config_markers
    assert "codex" in spec.binaries
    assert "hooks.json" in spec.register_hint
    assert "{target}" in spec.register_hint


def test_render_carries_no_secret() -> None:
    for spec in HARNESSES:
        rendered = render_hook(spec).lower()
        assert "bearer" not in rendered
        assert "token" not in rendered or "credential" in rendered
        assert "BEGIN PRIVATE KEY" not in rendered


def test_deploy_creates_hooks_idempotently(tmp_path: Path) -> None:
    first = deploy_hooks(tmp_path, list(HARNESSES))
    assert [r.status for r in first.reports] == ["deployed"] * len(HARNESSES)
    for spec in HARNESSES:
        target = tmp_path / spec.hook_rel
        assert target.is_file()
        assert is_managed(target)
    second = deploy_hooks(tmp_path, list(HARNESSES))
    assert [r.status for r in second.reports] == ["unchanged"] * len(HARNESSES)


def test_deploy_never_overwrites_foreign_file(tmp_path: Path) -> None:
    spec = _SPECS["opencode"]
    target = tmp_path / spec.hook_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# operator's own hook", encoding="utf-8")
    result = deploy_hooks(tmp_path, [spec])
    assert [r.status for r in result.reports] == ["needs-overwrite"]
    assert target.read_text(encoding="utf-8") == "# operator's own hook"
    forced = deploy_hooks(tmp_path, [spec], overwrite=True)
    assert [r.status for r in forced.reports] == ["overwritten"]
    assert is_managed(target)


def test_deploy_dry_run_writes_nothing(tmp_path: Path) -> None:
    result = deploy_hooks(tmp_path, list(HARNESSES), dry_run=True)
    assert [r.status for r in result.reports] == ["would-deploy"] * len(HARNESSES)
    assert not any(tmp_path.rglob("*.ps1"))


def test_detect_by_config_marker(tmp_path: Path) -> None:
    marker = tmp_path / ".claude.json"
    marker.write_text("{}", encoding="utf-8")
    found = {spec.harness for spec in detect_harnesses(tmp_path, ())}
    assert found == {"claude-code"}


def test_detect_codex_by_config_marker(tmp_path: Path) -> None:
    marker_dir = tmp_path / ".codex"
    marker_dir.mkdir()
    (marker_dir / "config.toml").write_text("", encoding="utf-8")
    found = {spec.harness for spec in detect_harnesses(tmp_path, ())}
    assert found == {"codex"}


def test_detect_by_binary(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "opencode.exe").write_text("stub", encoding="utf-8")
    found = {spec.harness for spec in detect_harnesses(tmp_path / "home", (str(bindir),))}
    assert found == {"opencode"}


def test_detect_empty_home(tmp_path: Path) -> None:
    assert detect_harnesses(tmp_path, ()) == []


def test_cli_setup_hooks_deploys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.setup_hooks(["--home", str(tmp_path), "--harness", "opencode"]) == 0
    assert (tmp_path / _SPECS["opencode"].hook_rel).is_file()
    assert "opencode: deployed" in capsys.readouterr().out


def test_cli_setup_hooks_deploys_codex_with_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.setup_hooks(["--home", str(tmp_path), "--harness", "codex"]) == 0
    out = capsys.readouterr().out
    assert "codex: deployed" in out
    assert "Next (codex):" in out
    assert "hooks.json" in out
    assert str(tmp_path / _SPECS["codex"].hook_rel) in out
    assert "{target}" not in out


def test_cli_setup_hooks_dry_run_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli.setup_hooks(["--home", str(tmp_path), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["skipped"] == ["claude-code", "opencode", "codex"]
    assert payload["deployed"] == []
    assert not any(tmp_path.rglob("*.ps1"))


def test_setup_hooks_visible_in_top_level_help(capsys: pytest.CaptureFixture[str]) -> None:
    """`setup-hooks` is no longer a hidden command: it shows in `--help`."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "setup-hooks" in capsys.readouterr().out


def test_agent_store_path_is_user_level() -> None:
    assert AGENT_STORE_REL.parts[:1] == (".claude",)
    assert AGENT_STORE_REL.name == "studio-agent.json"


@pytest.mark.parametrize("channel", ["dev", "prod"])
def test_hook_reads_the_clients_profile_directory(
    channel: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_CHANNEL", channel)
    profile_dir = default_config_path().parent.name
    rendered = render_hook(_SPECS["opencode"])
    assert f"'{profile_dir}'" in rendered
    assert "STUDIO_CLIENT_CHANNEL" in rendered
    assert "STUDIO_CLIENT_CONFIG_FILE" in rendered
    assert "XDG_CONFIG_HOME" in rendered


def test_hook_matches_task_worktrees() -> None:
    rendered = render_hook(_SPECS["opencode"])
    assert "-wt-" in rendered
    assert "^[0-9a-fA-F]{8}$" in rendered


def _run_hook(hook: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    args = [_PS, "-NoProfile"]
    if os.name == "nt":
        args += ["-ExecutionPolicy", "Bypass"]
    args += ["-File", str(hook)]
    return subprocess.run(
        args,
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=120,
        env=os.environ.copy(),
    )


@pytest.mark.skipif(_PS is None, reason="PowerShell absent de cette machine")
def test_hook_injects_identity_from_dev_profile_and_task_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le hook rend l'identité du projet depuis le profil dev et un worktree
    `<repo>-wt-<id8>` ; un suffixe hors convention ne rend rien, et le canal
    absent avec les deux profils présents retient le profil prod (fail-open :
    code 0, sortie vide)."""
    repo = tmp_path / "Studi'os"
    worktree = tmp_path / "Studi'os-wt-c1aa7c34"
    deep = worktree / "packages" / "studio-client"
    foreign = tmp_path / "Studi'os-wt-zzzzzzzz"
    for directory in (repo, deep, foreign):
        directory.mkdir(parents=True)

    if os.name == "nt":
        monkeypatch.setenv("APPDATA", str(tmp_path))
        dev_profile = tmp_path / "StudioOS-Dev"
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        dev_profile = tmp_path / "studio-os-dev"
    monkeypatch.setenv("STUDIO_CLIENT_CHANNEL", "dev")
    monkeypatch.delenv("STUDIO_CLIENT_CONFIG_FILE", raising=False)

    project_id = "2a836038-153c-41cf-879a-73bd794760b0"
    ws_dir = dev_profile / "workspaces"
    ws_dir.mkdir(parents=True)
    (ws_dir / f"{project_id}.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "project_slug": "studio-os",
                "roots": {
                    "workspace_root": str(repo),
                    "repo_roots": [{"name": "Studi'os", "path": str(repo)}],
                },
            }
        ),
        encoding="utf-8",
    )

    hook = tmp_path / "hook.ps1"
    hook.write_text(render_hook(_SPECS["opencode"]), encoding="utf-8")

    for tracked_dir in (worktree, deep):
        result = _run_hook(hook, tracked_dir)
        assert result.returncode == 0, result.stderr
        assert project_id in result.stdout
        assert "slug studio-os" in result.stdout

    foreign_result = _run_hook(hook, foreign)
    assert foreign_result.returncode == 0
    assert foreign_result.stdout.strip() == ""

    if os.name == "nt":
        (tmp_path / "StudioOS").mkdir()
    else:
        (tmp_path / "studio-os").mkdir()
    monkeypatch.delenv("STUDIO_CLIENT_CHANNEL")
    prod_result = _run_hook(hook, worktree)
    assert prod_result.returncode == 0
    assert prod_result.stdout.strip() == ""


@pytest.mark.skipif(_PS is None, reason="PowerShell absent de cette machine")
def test_hook_falls_back_to_the_profile_that_exists_without_a_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans STUDIO_CLIENT_CHANNEL le profil existant fait foi : un poste dev
    dont seul `StudioOS-Dev` existe rend bien l'identité du projet, alors que
    la valeur par défaut `StudioOS` ne contiendrait aucun workspace."""
    rendered = render_hook(_SPECS["opencode"])
    assert "Test-Path -LiteralPath $prodDir" in rendered

    repo = tmp_path / "Studi'os"
    repo.mkdir()
    monkeypatch.delenv("STUDIO_CLIENT_CHANNEL", raising=False)
    monkeypatch.delenv("STUDIO_CLIENT_CONFIG_FILE", raising=False)
    if os.name == "nt":
        monkeypatch.setenv("APPDATA", str(tmp_path))
        profile = tmp_path / "StudioOS-Dev"
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        profile = tmp_path / "studio-os-dev"

    project_id = "2a836038-153c-41cf-879a-73bd794760b0"
    ws_dir = profile / "workspaces"
    ws_dir.mkdir(parents=True)
    (ws_dir / f"{project_id}.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "project_slug": "studio-os",
                "roots": {
                    "workspace_root": str(repo),
                    "repo_roots": [{"name": "Studi'os", "path": str(repo)}],
                },
            }
        ),
        encoding="utf-8",
    )

    hook = tmp_path / "hook-fallback.ps1"
    hook.write_text(render_hook(_SPECS["opencode"]), encoding="utf-8")

    result = _run_hook(hook, repo)
    assert result.returncode == 0, result.stderr
    assert project_id in result.stdout
    assert "slug studio-os" in result.stdout
