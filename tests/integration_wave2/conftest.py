from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.daemon.local_features import LocalFeatureRegistry
from studio_client.daemon.service import BridgeService, DaemonController
from studio_client.knowledge.obsidian import ObsidianProbe
from studio_client.knowledge.service import knowledge_service_from_workspace
from studio_code_graph.service import CodeGraphService
from studio_contracts.local.bridge import BridgeRequest
from studio_contracts.local.common import ComponentState
from studio_contracts.local.handshake import HandshakeRequest
from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import (
    CodeGraphConfig,
    IndexLocation,
    KnowledgeConfig,
    LocalFeatures,
    LocalWorkspaceConfig,
    WorkspaceRoots,
)

from tests.code_graph.support import APP_FILES, FakeProvider, init_repo
from tests.knowledge.factories import make_vault

WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")
PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")
PROFILE = ProfileRef(profile_id="main", server_origin="https://studio.example")
NOW = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
NO_OBSIDIAN = ObsidianProbe(state=ComponentState.NOT_INSTALLED)


@dataclass
class Workspace:
    root: Path
    vault: Path
    repo: Path
    config: LocalWorkspaceConfig


def build_workspace(
    root: Path,
    *,
    knowledge: bool = True,
    code_graph: bool = True,
    files: dict[str, str] | None = APP_FILES,
    workspace_id: UUID = WORKSPACE_ID,
    profile: ProfileRef = PROFILE,
) -> Workspace:
    vault = make_vault(root)
    repo = init_repo(root / "repo", files)
    config = LocalWorkspaceConfig(
        workspace_id=workspace_id,
        profile=profile,
        project_id=PROJECT_ID,
        project_slug="demo-game",
        roots=WorkspaceRoots(
            workspace_root=str(root),
            repo_roots=[{"name": "app", "path": str(repo)}],
        ),
        features=LocalFeatures(knowledge=knowledge, code_graph=code_graph),
        knowledge=KnowledgeConfig(
            provider_id="markdown-files",
            content_root="vault",
            index=IndexLocation(directory_name="knowledge-index"),
        )
        if knowledge
        else None,
        code_graph=CodeGraphConfig(
            provider_id="fake",
            repo_names=["app"],
            index=IndexLocation(directory_name="code"),
        )
        if code_graph
        else None,
        created_at=NOW,
        updated_at=NOW,
    )
    return Workspace(root=root, vault=vault, repo=repo, config=config)


def knowledge_factory(config: LocalWorkspaceConfig, cache_dir: Path):
    return knowledge_service_from_workspace(config, cache_dir=cache_dir, obsidian=NO_OBSIDIAN)


@pytest.fixture
def code_graph(tmp_path: Path) -> tuple[CodeGraphService, FakeProvider]:
    provider = FakeProvider()
    service = CodeGraphService(
        [provider],
        tmp_path / "code-graph-cache",
        debounce_seconds=0.0,
        freshness_ttl_seconds=0.0,
        probe_ttl_seconds=0.0,
    )
    return service, provider


def make_registry(
    configs: list[LocalWorkspaceConfig],
    cache_root: Path,
    *,
    service: CodeGraphService | None,
) -> LocalFeatureRegistry:
    return LocalFeatureRegistry(
        workspace_configs=lambda profile: [c for c in configs if c.profile == profile],
        cache_root=cache_root,
        code_graph_service=service,
        knowledge_factory=knowledge_factory,
        vault_poll_seconds=0.05,
    )


def controller(tmp_path: Path, registry: LocalFeatureRegistry) -> DaemonController:
    return DaemonController(
        ClientConfig(
            api_base_url="https://studio.example/api/v1",
            profile_id="main",
            machine_id=uuid4(),
        ),
        data_root=tmp_path,
        local_features=registry,
    )


def bridge_request(command: str, payload: dict) -> str:
    value = BridgeRequest.model_validate(
        {
            "message_id": f"msg-{uuid4().hex[:16]}",
            "correlation_id": f"corr-{uuid4().hex[:16]}",
            "sent_at": "2026-09-21T00:00:00Z",
            "command": command,
            "payload": payload,
        }
    )
    return value.model_dump_json()


def negotiate(service: BridgeService, capabilities: list[str]) -> dict:
    payload = HandshakeRequest.model_validate(
        {
            "peer": {
                "role": "desktop",
                "protocol": {
                    "minimum": {"major": 1, "minor": 0},
                    "maximum": {"major": 1, "minor": 0},
                },
                "component_version": "0.1.0",
                "capabilities": capabilities,
                "required_capabilities": ["daemon.control"],
                "optional_capabilities": [
                    capability for capability in DESKTOP_CAPABILITIES if capability in capabilities
                ],
            }
        }
    )
    return service.handle_line(bridge_request("runtime.handshake", payload.model_dump(mode="json")))


DESKTOP_CAPABILITIES = [
    "daemon.control",
    "daemon.health",
    "identity.view",
    "knowledge.read",
    "knowledge.graph",
    "knowledge.index",
    "knowledge.init",
    "code_graph.read",
    "code_graph.graph",
    "code_graph.index",
]


def wait_for(predicate, timeout: float = 15.0) -> bool:
    """The vault indexer and the code graph builder run on the daemon's own
    feature loop; a synchronous poll keeps the tests honest about that."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False
