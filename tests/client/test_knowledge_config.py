"""8.2 config tests: vault/graph paths and closed-by-default scope."""

from __future__ import annotations

from pathlib import Path

import pytest
from studio_client.config import ClientConfig


def test_knowledge_defaults_are_unset_and_deny_all() -> None:
    config = ClientConfig(api_base_url="https://vps.example.com")
    assert config.knowledge_vault_path is None
    assert config.knowledge_graph_dir is None
    assert config.knowledge_source_root is None
    assert config.knowledge_scope_allow == ()


def test_knowledge_init_values(tmp_path: Path) -> None:
    config = ClientConfig(
        api_base_url="https://vps.example.com",
        knowledge_vault_path=tmp_path / "vault",
        knowledge_graph_dir=tmp_path / "graph-out",
        knowledge_scope_allow=("projects/demo/", "conventions/"),
    )
    assert config.knowledge_vault_path == tmp_path / "vault"
    assert config.knowledge_graph_dir == tmp_path / "graph-out"
    assert config.knowledge_scope_allow == ("projects/demo/", "conventions/")


def test_knowledge_env_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_KNOWLEDGE_VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("STUDIO_CLIENT_KNOWLEDGE_GRAPH_DIR", str(tmp_path / "graph-out"))
    monkeypatch.setenv("STUDIO_CLIENT_KNOWLEDGE_SCOPE_ALLOW", '["projects/demo/", "global/"]')
    config = ClientConfig(api_base_url="https://vps.example.com")
    assert config.knowledge_vault_path == tmp_path / "vault"
    assert config.knowledge_graph_dir == tmp_path / "graph-out"
    assert config.knowledge_scope_allow == ("projects/demo/", "global/")


def test_knowledge_toml_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        'api_base_url = "https://from-toml.example.com"\n'
        f'knowledge_vault_path = "{(tmp_path / "vault").as_posix()}"\n'
        'knowledge_scope_allow = ["projects/demo/"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(toml_path))
    config = ClientConfig()
    assert config.api_base_url == "https://from-toml.example.com"
    assert config.knowledge_vault_path == tmp_path / "vault"
    assert config.knowledge_scope_allow == ("projects/demo/",)
