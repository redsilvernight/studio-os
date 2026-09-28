"""Versioned OpenCode plugin (L1 follow-up of setup-hooks/Codex): the
`studio-os.js` template is rendered per home (paths interpolated, no
machine-specific absolute path baked in) and deployed managed alongside
the session script — idempotent, never overwriting a foreign file
silently, dry-run writing nothing. Pure local, no DB."""

from __future__ import annotations

from pathlib import Path

import pytest
from studio_client import cli
from studio_client.hooks import MANAGED_MARKER, is_managed
from studio_client.opencode_plugin import (
    GUARD_REL,
    PLUGIN_REL,
    deploy_plugin,
    guard_state,
    plugin_target,
    render_plugin,
)


def test_render_has_no_placeholder_no_machine_path_no_secret() -> None:
    home = Path("/home/opencode-test")
    rendered = render_plugin(home)
    assert MANAGED_MARKER in rendered
    for token in ("__MANAGED_MARKER__", "__GUARD_SCRIPT__", "__SESSION_SCRIPT__"):
        assert token not in rendered
    assert "redsi" not in rendered
    assert "C:/Users" not in rendered
    lowered = rendered.lower()
    assert "bearer" not in lowered
    assert "BEGIN PRIVATE KEY" not in rendered


def test_render_points_at_deploy_targets(tmp_path: Path) -> None:
    rendered = render_plugin(tmp_path)
    assert (tmp_path / PLUGIN_REL).as_posix() not in rendered  # plugin never self-references
    assert (tmp_path / ".config" / "opencode" / "scripts").as_posix() in rendered
    assert (tmp_path / GUARD_REL).as_posix() in rendered


def test_deploy_creates_plugin_idempotently(tmp_path: Path) -> None:
    first = deploy_plugin(tmp_path)
    assert [r.status for r in first.reports] == ["deployed"]
    target = plugin_target(tmp_path)
    assert target.is_file()
    assert is_managed(target)
    second = deploy_plugin(tmp_path)
    assert [r.status for r in second.reports] == ["unchanged"]


def test_deploy_never_overwrites_foreign_plugin(tmp_path: Path) -> None:
    target = plugin_target(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("// operator's own plugin", encoding="utf-8")
    result = deploy_plugin(tmp_path)
    assert [r.status for r in result.reports] == ["needs-overwrite"]
    assert target.read_text(encoding="utf-8") == "// operator's own plugin"
    forced = deploy_plugin(tmp_path, overwrite=True)
    assert [r.status for r in forced.reports] == ["overwritten"]
    assert is_managed(target)


def test_deploy_dry_run_writes_nothing(tmp_path: Path) -> None:
    result = deploy_plugin(tmp_path, dry_run=True)
    assert [r.status for r in result.reports] == ["would-deploy"]
    assert not any(tmp_path.rglob("*.js"))


def test_guard_state_reports_without_writing(tmp_path: Path) -> None:
    assert guard_state(tmp_path) == "guard-missing"
    guard = tmp_path / GUARD_REL
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text("// operator's own guard", encoding="utf-8")
    assert guard_state(tmp_path) == "guard-foreign"
    guard.write_text(f"// {MANAGED_MARKER}\n", encoding="utf-8")
    assert guard_state(tmp_path) == "guard-managed"


def test_cli_deploys_plugin_with_opencode_script(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.setup_hooks(["--home", str(tmp_path), "--harness", "opencode"]) == 0
    out = capsys.readouterr().out
    assert "opencode: deployed" in out
    assert "opencode-plugin: deployed" in out
    assert (tmp_path / PLUGIN_REL).is_file()


def test_cli_skips_plugin_for_other_harnesses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.setup_hooks(["--home", str(tmp_path), "--harness", "claude-code"]) == 0
    out = capsys.readouterr().out
    assert "opencode-plugin" not in out
    assert not (tmp_path / PLUGIN_REL).exists()
