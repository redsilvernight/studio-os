from __future__ import annotations

from pathlib import Path

import pytest
from studio_client.knowledge.errors import KnowledgeError
from studio_client.knowledge.service import (
    KnowledgeService,
    knowledge_service_from_workspace,
    knowledge_vault_root,
)
from studio_contracts.local.common import ComponentState
from studio_contracts.local.knowledge import KnowledgeReindexRequest

from tests.knowledge.conftest import NO_OBSIDIAN
from tests.knowledge.factories import make_config, make_vault


def _reindex(service: KnowledgeService) -> KnowledgeReindexRequest:
    return KnowledgeReindexRequest(workspace_id=service.workspace_id)


def test_a_disabled_workspace_builds_no_service_and_no_index(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    assert vault.is_dir()
    config = make_config(tmp_path, knowledge=False)
    cache = tmp_path / "cache"
    service = knowledge_service_from_workspace(config, cache_dir=cache)
    assert service is None
    assert not cache.exists()
    assert knowledge_vault_root(config) is None


def test_an_enabled_workspace_is_bound_to_its_vault(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    config = make_config(tmp_path)
    cache = tmp_path / "cache"
    service = knowledge_service_from_workspace(config, cache_dir=cache, obsidian=NO_OBSIDIAN)
    assert service is not None
    assert service.vault_root == vault
    assert service.workspace_id == config.workspace_id
    assert service.provider.status().state is ComponentState.UNAVAILABLE
    service.provider.reindex(_reindex(service))
    assert service.provider.status().state is ComponentState.READY
    assert service.provider.index.path.is_file()
    assert service.provider.index.path.is_relative_to(cache)


def test_a_moved_workspace_reports_an_explicit_state(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    cache = tmp_path / "cache"
    service = knowledge_service_from_workspace(config, cache_dir=cache, obsidian=NO_OBSIDIAN)
    assert service is not None
    status = service.provider.status()
    assert status.state is ComponentState.UNAVAILABLE
    assert status.error is not None
    assert status.error.details.get("reason") == "missing"


def test_detaching_drops_the_index_but_never_the_markdown(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    config = make_config(tmp_path)
    service = knowledge_service_from_workspace(
        config, cache_dir=tmp_path / "cache", obsidian=NO_OBSIDIAN
    )
    assert service is not None
    service.provider.reindex(_reindex(service))
    assert service.provider.index.path.is_file()
    before = {path.relative_to(vault).as_posix(): path.read_bytes() for path in vault.rglob("*.md")}
    assert service.detach() is True
    assert not service.provider.index.path.is_file()
    after = {path.relative_to(vault).as_posix(): path.read_bytes() for path in vault.rglob("*.md")}
    assert after == before


def test_the_agent_adapter_is_closed_by_default(tmp_path: Path) -> None:
    make_vault(tmp_path)
    config = make_config(tmp_path)
    service = knowledge_service_from_workspace(
        config, cache_dir=tmp_path / "cache", obsidian=NO_OBSIDIAN
    )
    assert service is not None
    service.provider.reindex(_reindex(service))
    denied = service.memory_provider()
    assert denied.search("combat").matches == []
    allowed = service.memory_provider(allowed_prefixes=("projects/demo/",))
    matches = allowed.search("combat").matches
    assert matches
    assert all(match.path.startswith("projects/demo/") for match in matches)


def test_the_agent_adapter_reads_only_in_scope(tmp_path: Path) -> None:
    make_vault(tmp_path)
    config = make_config(tmp_path)
    service = knowledge_service_from_workspace(
        config, cache_dir=tmp_path / "cache", obsidian=NO_OBSIDIAN
    )
    assert service is not None
    service.provider.reindex(_reindex(service))
    adapter = service.memory_provider(allowed_prefixes=("projects/demo/",))
    read = adapter.read("projects/demo/intro.md")
    assert "Introduction" in read.title
    with pytest.raises(KnowledgeError) as error:
        adapter.read("conventions/style.md")
    assert error.value.reason == KnowledgeError.OUT_OF_SCOPE


def test_the_agent_adapter_refuses_writes(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    service = knowledge_service_from_workspace(
        config, cache_dir=tmp_path / "cache", obsidian=NO_OBSIDIAN
    )
    assert service is not None
    adapter = service.memory_provider()
    with pytest.raises(KnowledgeError) as error:
        adapter.propose({})
    assert error.value.reason == KnowledgeError.WRITE_UNSUPPORTED
