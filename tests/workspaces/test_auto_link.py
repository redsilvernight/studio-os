from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client import auto_link as al
from studio_client import cli
from studio_client.auto_link import AutoLinkStatus, auto_link

ORIGIN = "https://studio.example.test"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    registry, home, repo = tmp_path / "reg", tmp_path / "home", tmp_path / "repo"
    for folder in (registry, home, repo):
        folder.mkdir()
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(registry / "config.toml"))
    monkeypatch.delenv("STUDIO_CLIENT_API_BASE_URL", raising=False)
    return {"registry": registry, "home": home, "repo": repo}


def _declare(repo: Path, project_id: object) -> None:
    (repo / "AGENTS.md").write_text(
        f"# X\n\nProjet Studio OS : {project_id}.\nRoadmap : {uuid4()}.\n", encoding="utf-8"
    )


def _mcp(home: Path, url: str = ORIGIN + "/mcp") -> None:
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"studio-os": {"url": url, "headers": {"Authorization": "x"}}}}),
        encoding="utf-8",
    )


def _run(env: dict[str, Path]) -> al.AutoLinkResult:
    return auto_link(env["repo"], env["registry"], home=env["home"])


def test_links_and_writes_config_once(env: dict[str, Path]) -> None:
    pid = uuid4()
    _declare(env["repo"], pid)
    _mcp(env["home"])
    al.grant_consent(env["registry"], ORIGIN)

    first = _run(env)
    assert (first.status, first.project_id, first.config_written) == (
        AutoLinkStatus.LINKED,
        pid,
        True,
    )
    assert (env["registry"] / "config.toml").read_text() == f'api_base_url = "{ORIGIN}"\n'
    second = _run(env)
    assert (second.status, second.config_written) == (AutoLinkStatus.ALREADY_LINKED, False)


def test_project_id_absent(env: dict[str, Path]) -> None:
    (env["repo"] / "AGENTS.md").write_text("Roadmap : " + str(uuid4()), encoding="utf-8")
    al.grant_consent(env["registry"], ORIGIN)
    assert _run(env).status is AutoLinkStatus.NO_PROJECT_ID


def test_without_consent_nothing_is_written(env: dict[str, Path]) -> None:
    _declare(env["repo"], uuid4())
    _mcp(env["home"])
    assert _run(env).status is AutoLinkStatus.NO_CONSENT
    assert not (env["registry"] / "config.toml").exists()


def test_revoked_consent_stops_linking(env: dict[str, Path]) -> None:
    _declare(env["repo"], uuid4())
    _mcp(env["home"])
    al.grant_consent(env["registry"], ORIGIN)
    assert al.revoke_consent(env["registry"]) is True
    assert _run(env).status is AutoLinkStatus.NO_CONSENT


def test_folder_linked_to_another_project(env: dict[str, Path]) -> None:
    _mcp(env["home"])
    al.grant_consent(env["registry"], ORIGIN)
    _declare(env["repo"], uuid4())
    assert _run(env).status is AutoLinkStatus.LINKED
    _declare(env["repo"], uuid4())
    assert _run(env).status is AutoLinkStatus.CONFLICT


def test_config_missing_and_no_mcp_url(env: dict[str, Path]) -> None:
    _declare(env["repo"], uuid4())
    al.grant_consent(env["registry"], ORIGIN)
    assert _run(env).status is AutoLinkStatus.CONFIG_UNAVAILABLE


def test_mcp_origin_must_match_consent(env: dict[str, Path]) -> None:
    _declare(env["repo"], uuid4())
    _mcp(env["home"], "https://other.example.test/mcp")
    al.grant_consent(env["registry"], ORIGIN)
    assert _run(env).status is AutoLinkStatus.CONFIG_MISMATCH
    assert not (env["registry"] / "config.toml").exists()


def test_existing_config_is_kept(env: dict[str, Path]) -> None:
    (env["registry"] / "config.toml").write_text('api_base_url = "https://mine.example.test"\n')
    _declare(env["repo"], uuid4())
    al.grant_consent(env["registry"], ORIGIN)
    result = _run(env)
    assert (result.status, result.server_origin) == (
        AutoLinkStatus.LINKED,
        "https://mine.example.test",
    )


def test_consent_cli_refused_without_yes_when_not_interactive(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(""))
    argv = ["workspaces", "auto-link-consent", "grant", "--api-base-url", ORIGIN]
    with pytest.raises(SystemExit):
        cli.main([*argv, "--registry-dir", str(env["registry"])])
    assert al.read_consent(env["registry"]) is None
    cli.main([*argv, "--yes", "--registry-dir", str(env["registry"])])
    assert al.read_consent(env["registry"]) == ORIGIN
