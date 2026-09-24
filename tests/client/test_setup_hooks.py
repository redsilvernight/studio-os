"""`setup-hooks` (workflow W2b): versioned session-start hooks deployable on
a fresh machine — pure local deployment, no server, no secret written, user
account configs never touched (DEC-0096 boundary). No DB needed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_client import cli
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


def test_render_carries_no_secret() -> None:
    for spec in HARNESSES:
        rendered = render_hook(spec).lower()
        assert "bearer" not in rendered
        assert "token" not in rendered or "credential" in rendered
        assert "BEGIN PRIVATE KEY" not in rendered


def test_deploy_creates_hooks_idempotently(tmp_path: Path) -> None:
    first = deploy_hooks(tmp_path, list(HARNESSES))
    assert [r.status for r in first.reports] == ["deployed", "deployed"]
    for spec in HARNESSES:
        target = tmp_path / spec.hook_rel
        assert target.is_file()
        assert is_managed(target)
    second = deploy_hooks(tmp_path, list(HARNESSES))
    assert [r.status for r in second.reports] == ["unchanged", "unchanged"]


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
    assert [r.status for r in result.reports] == ["would-deploy", "would-deploy"]
    assert not any(tmp_path.rglob("*.ps1"))


def test_detect_by_config_marker(tmp_path: Path) -> None:
    marker = tmp_path / ".claude.json"
    marker.write_text("{}", encoding="utf-8")
    found = {spec.harness for spec in detect_harnesses(tmp_path, ())}
    assert found == {"claude-code"}


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


def test_cli_setup_hooks_dry_run_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli.setup_hooks(["--home", str(tmp_path), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["skipped"] == ["claude-code", "opencode"]
    assert payload["deployed"] == []
    assert not any(tmp_path.rglob("*.ps1"))


def test_agent_store_path_is_user_level() -> None:
    assert AGENT_STORE_REL.parts[:1] == (".claude",)
    assert AGENT_STORE_REL.name == "studio-agent.json"
