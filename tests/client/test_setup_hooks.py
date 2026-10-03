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
    GUARD_REL,
    HARNESSES,
    MANAGED_MARKER,
    deploy_guard,
    deploy_hooks,
    detect_harnesses,
    guard_state,
    is_managed,
    render_guard,
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
        for token in (
            "__HARNESS__",
            "__AGENT_KEY__",
            "__OUTPUT__",
            "__MANAGED_MARKER__",
            "__MODEL_BLOCK__",
        ):
            assert token not in rendered


def test_render_outputs_differ_per_harness() -> None:
    assert "'json'" in render_hook(_SPECS["claude-code"])
    assert "'text'" in render_hook(_SPECS["opencode"])
    assert "'text'" in render_hook(_SPECS["codex"])


def test_hook_scopes_the_agent_cache_by_server_origin() -> None:
    for spec in HARNESSES:
        rendered = render_hook(spec)
        assert "${originKey}" in rendered
        assert f"{spec.agent_key}:${{originKey}}" in rendered


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


def test_render_guard_is_managed_and_has_no_placeholder() -> None:
    """AIB L1 : le guard est versionne, porte le marqueur gere et bloque par
    code 2 (jamais par un code d'erreur PowerShell)."""
    rendered = render_guard()
    assert MANAGED_MARKER in rendered
    assert "__MANAGED_MARKER__" not in rendered
    assert "exit 2" in rendered
    assert "studio-git-guard" in rendered


def test_deploy_guard_idempotent_and_never_overwrites_foreign(tmp_path: Path) -> None:
    assert [r.status for r in deploy_guard(tmp_path).reports] == ["deployed"]
    assert is_managed(tmp_path / GUARD_REL)
    assert guard_state(tmp_path) == "guard-managed"
    assert [r.status for r in deploy_guard(tmp_path).reports] == ["unchanged"]

    (tmp_path / GUARD_REL).write_text("# operator's own guard", encoding="utf-8")
    assert guard_state(tmp_path) == "guard-foreign"
    assert [r.status for r in deploy_guard(tmp_path).reports] == ["needs-overwrite"]
    assert (tmp_path / GUARD_REL).read_text(encoding="utf-8") == "# operator's own guard"
    assert [r.status for r in deploy_guard(tmp_path, overwrite=True).reports] == ["overwritten"]
    assert guard_state(tmp_path) == "guard-managed"


def test_deploy_guard_dry_run_writes_nothing(tmp_path: Path) -> None:
    assert [r.status for r in deploy_guard(tmp_path, dry_run=True).reports] == ["would-deploy"]
    assert not (tmp_path / GUARD_REL).exists()


def test_cli_setup_hooks_deploys_guard(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.setup_hooks(["--home", str(tmp_path), "--harness", "opencode"]) == 0
    out = capsys.readouterr().out
    assert "git-guard: deployed" in out
    assert is_managed(tmp_path / GUARD_REL)


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


def test_opencode_render_carries_the_model_protocol() -> None:
    """AIB L1 : le template de hook OpenCode porte le bloc modele, resolu via
    POST /agents/ensure avec une stable_key dediee par couple harness+modele."""
    rendered = render_hook(_SPECS["opencode"])
    assert "harness/modele" in rendered
    assert "agents-ensure-opencode:" in rendered
    assert "'--harness', 'opencode'" in rendered
    assert "$modelRef = $payload.model" in rendered


def test_all_harnesses_carry_the_model_protocol() -> None:
    """AIB L2 : l'identite agent est le couple (harness, modele) sur tous les
    harnais — le bloc modele est present quelle que soit la sortie (texte ou
    JSON), avec une stable_key dediee par couple harness+modele."""
    for spec in HARNESSES:
        rendered = render_hook(spec)
        assert "harness/modele" in rendered
        assert f"agents-ensure-{spec.harness}:" in rendered
        assert f"'--harness', '{spec.harness}'" in rendered
        assert "$modelRef = $payload.model" in rendered


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


@pytest.mark.skipif(_PS is None, reason="PowerShell absent de cette machine")
def test_hook_emits_model_agent_line_from_ensured_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AIB L1 : un poste suivi dont le `studio-client` du PATH rend un agent
    idempotent voit le hook resoudre l'agent du couple (harness, modele),
    emettre la ligne `harness/modele` et cacher la cle scope modele dans
    studio-agent.json (fail-open, aucun secret)."""
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
                "profile": {"server_origin": "http://example.invalid"},
            }
        ),
        encoding="utf-8",
    )

    agent_id = "11111111-1111-1111-1111-111111111111"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if os.name == "nt":
        (bindir / "studio-client.cmd").write_text(
            f'@echo {{"id": "{agent_id}"}}\r\n', encoding="utf-8"
        )
    else:
        stub = bindir / "studio-client"
        stub.write_text(f'#!/bin/sh\necho \'{{"id": "{agent_id}"}}\'\n', encoding="utf-8")
        stub.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["HOME"] = str(tmp_path)
    if os.name == "nt":
        env["USERPROFILE"] = str(tmp_path)

    hook = tmp_path / "hook-model.ps1"
    hook.write_text(render_hook(_SPECS["opencode"]), encoding="utf-8")

    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)

    args = [_PS, "-NoProfile"]
    if os.name == "nt":
        args += ["-ExecutionPolicy", "Bypass"]
    args += ["-File", str(hook)]
    result = subprocess.run(
        args,
        input=json.dumps({"cwd": str(repo), "model": "opencode-go/deepseek-v4.1-flash"}),
        capture_output=True,
        text=True,
        cwd=str(repo),
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "harness/modele" in result.stdout
    assert "opencode-go/deepseek-v4.1-flash" in result.stdout
    assert agent_id in result.stdout

    store = json.loads((tmp_path / ".claude" / "studio-agent.json").read_text(encoding="utf-8"))
    assert store["opencode:http://example.invalid:opencode-go/deepseek-v4.1-flash"] == agent_id
    # Pas de doublon : l'agent du harnais n'est pas cree quand le modele est connu.
    assert "opencode:http://example.invalid" not in store


@pytest.mark.skipif(_PS is None, reason="PowerShell absent de cette machine")
def test_claude_json_hook_emits_model_agent_in_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AIB L2 : la sortie JSON de Claude Code porte elle aussi l'agent du
    couple (harness, modele) dans `additionalContext`, sans creer l'agent du
    harnais en plus."""
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
                "profile": {"server_origin": "http://example.invalid"},
            }
        ),
        encoding="utf-8",
    )

    agent_id = "22222222-2222-2222-2222-222222222222"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if os.name == "nt":
        (bindir / "studio-client.cmd").write_text(
            f'@echo {{"id": "{agent_id}"}}\r\n', encoding="utf-8"
        )
    else:
        stub = bindir / "studio-client"
        stub.write_text(f'#!/bin/sh\necho \'{{"id": "{agent_id}"}}\'\n', encoding="utf-8")
        stub.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["HOME"] = str(tmp_path)
    if os.name == "nt":
        env["USERPROFILE"] = str(tmp_path)

    hook = tmp_path / "hook-claude-model.ps1"
    hook.write_text(render_hook(_SPECS["claude-code"]), encoding="utf-8")
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)

    args = [_PS, "-NoProfile"]
    if os.name == "nt":
        args += ["-ExecutionPolicy", "Bypass"]
    args += ["-File", str(hook)]
    result = subprocess.run(
        args,
        input=json.dumps({"cwd": str(repo), "model": "anthropic/claude-opus-5-5"}),
        capture_output=True,
        text=True,
        cwd=str(repo),
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    context = envelope["hookSpecificOutput"]["additionalContext"]
    assert "harness/modele" in context
    assert "anthropic/claude-opus-5-5" in context
    assert agent_id in context

    store = json.loads((tmp_path / ".claude" / "studio-agent.json").read_text(encoding="utf-8"))
    assert store["claude-code:http://example.invalid:anthropic/claude-opus-5-5"] == agent_id
    assert "claude-code:http://example.invalid" not in store


@pytest.mark.skipif(_PS is None, reason="PowerShell absent de cette machine")
def test_guard_blocks_commit_on_protected_branch(tmp_path: Path) -> None:
    """AIB L1 : le guard versionne bloque (code 2) un `git commit` direct sur
    une branche protegee et autorise (code 0) une branche task/*."""
    guard = tmp_path / "guard.ps1"
    guard.write_text(render_guard(), encoding="utf-8")

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "phase/protected"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)

    def run(command: str) -> int:
        args = [_PS, "-NoProfile"]
        if os.name == "nt":
            args += ["-ExecutionPolicy", "Bypass"]
        args += ["-File", str(guard)]
        result = subprocess.run(
            args,
            input=json.dumps({"tool_input": {"command": command}, "cwd": str(repo)}),
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=60,
            env=os.environ.copy(),
        )
        return result.returncode

    assert run("git commit -m wip") == 2
    assert run("git status") == 0
    subprocess.run(["git", "checkout", "-q", "-b", "task/abc"], cwd=repo, check=True)
    assert run("git commit -m wip") == 0
