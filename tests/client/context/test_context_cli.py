from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from studio_client import cli
from studio_client.config import ClientConfig


@pytest.fixture
def config(tmp_path: Path) -> ClientConfig:
    return ClientConfig(
        api_base_url="https://example.com",
        machine_id=uuid4(),
        knowledge_vault_path=tmp_path / "vault",
        knowledge_graph_dir=tmp_path / "graph",
    )


def test_context_generate_parser_accepts_project_and_task(config: ClientConfig) -> None:
    parser = cli._build_parser()
    project_id = uuid4()
    task_id = uuid4()
    args = parser.parse_args(
        [
            "context",
            "generate",
            "--project-id",
            str(project_id),
            "--task-id",
            str(task_id),
            "--with-memory",
            "--memory-query",
            "test",
            "--budget-bytes",
            "1024",
        ]
    )
    assert args.command == "context"
    assert args.context_command == "generate"
    assert args.project_id == str(project_id)
    assert args.task_id == str(task_id)
    assert args.with_memory is True
    assert args.memory_query == "test"
    assert args.budget_bytes == 1024


def test_context_generate_parser_defaults(config: ClientConfig) -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["context", "generate", "--project-id", str(uuid4())])
    assert args.with_memory is False
    assert args.with_graph is False
    assert args.with_git is False
    assert args.budget_bytes == 256 * 1024
    assert args.events_limit == 50


def test_context_providers_build_from_config(config: ClientConfig, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    graph = tmp_path / "graph"
    graph.mkdir()
    config = ClientConfig(
        api_base_url="https://example.com",
        knowledge_vault_path=vault,
        knowledge_graph_dir=graph,
        knowledge_scope_allow=("projects/slug/",),
    )
    memory, graph_provider = cli._context_providers(config)
    assert memory is not None
    assert graph_provider is not None


def test_context_providers_none_when_not_configured(config: ClientConfig) -> None:
    bare = ClientConfig(api_base_url="https://example.com")
    memory, graph = cli._context_providers(bare)
    assert memory is None
    assert graph is None
