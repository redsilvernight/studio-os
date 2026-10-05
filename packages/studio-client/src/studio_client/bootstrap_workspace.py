from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessPlan,
    HarnessPreviewRequest,
    HarnessState,
    HarnessStatus,
)
from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import LocalWorkspaceConfig, WorkspaceScope
from studio_workspaces import RootConfirmationService, WorkspaceStore
from studio_workspaces.path_safety import workspace_binding_key

from studio_client.harness.backup import BackupStore
from studio_client.harness.base import MCP_PATH, system_env
from studio_client.harness.credentials import (
    ApiCredentialProvisioner,
    CredentialProvisioner,
    CredentialStore,
)
from studio_client.harness.registry import HarnessRegistry, default_adapters
from studio_client.harness.service import (
    HarnessService,
    HarnessServiceError,
    McpProbe,
    WorkspaceInfo,
)


class WorkspaceBootstrapError(Exception):
    pass


@dataclass(frozen=True)
class McpWiring:
    adapter_id: str
    plan: HarnessPlan
    applied: bool
    state: HarnessState | None = None


def find_workspace(
    registry_dir: Path, profile: ProfileRef, repo_root: Path | str
) -> LocalWorkspaceConfig:
    """The registered workspace whose root is `repo_root`, from the machine-local registry."""
    store = WorkspaceStore(registry_dir, RootConfirmationService())
    wanted = workspace_binding_key(str(Path(repo_root).resolve()))
    for config in store.list_workspaces(profile):
        if workspace_binding_key(config.roots.workspace_root) == wanted:
            return config
    raise WorkspaceBootstrapError(
        "this folder is not a registered workspace; run `workspaces register` first"
    )


def build_harness_service(
    registry_dir: Path,
    config: LocalWorkspaceConfig,
    *,
    registry: HarnessRegistry | None = None,
    provisioner: CredentialProvisioner | None = None,
    env: Callable[[], Mapping[str, str]] = system_env,
    home: Callable[[], Path] = Path.home,
    mcp_probe: McpProbe | None = None,
) -> HarnessService:
    origin = str(config.profile.server_origin).rstrip("/")
    info = WorkspaceInfo(
        workspace_id=config.workspace_id,
        root=Path(config.roots.workspace_root),
        mcp_url=origin + MCP_PATH,
        harness_enabled=True,
        server_origin=origin,
    )

    def lookup(workspace_id: UUID) -> WorkspaceInfo | None:
        return info if workspace_id == info.workspace_id else None

    return HarnessService(
        registry or HarnessRegistry(default_adapters()),
        BackupStore(registry_dir / "harness-backups"),
        lookup,
        credentials=CredentialStore(registry_dir / "harness-credentials.json"),
        provisioner=provisioner or ApiCredentialProvisioner(),
        env=env,
        home=home,
        mcp_probe=mcp_probe,
    )


def detect_harness_ids(service: HarnessService, config: LocalWorkspaceConfig) -> list[str]:
    """Adapter ids of the harnesses present on this machine, sorted."""
    result = service.detect(WorkspaceScope(workspace_id=config.workspace_id))
    return sorted(status.adapter_id for status in result.harnesses if _present(status))


def _present(status: HarnessStatus) -> bool:
    return status.state in (HarnessState.DETECTED, HarnessState.CONFIGURED)


def wire_mcp(
    service: HarnessService,
    config: LocalWorkspaceConfig,
    adapter_ids: list[str],
    *,
    confirm: bool,
) -> list[McpWiring]:
    """Previews the machine-local MCP wiring of each harness and, only with
    `confirm`, applies it. Without `confirm` nothing is written."""
    wirings: list[McpWiring] = []
    for adapter_id in adapter_ids:
        try:
            plan = service.preview(
                HarnessPreviewRequest(workspace_id=config.workspace_id, adapter_id=adapter_id)
            )
            if not confirm or not plan.changes:
                wirings.append(McpWiring(adapter_id, plan, applied=False))
                continue
            result = service.apply(
                HarnessApplyRequest(plan_id=plan.plan_id, plan_hash=plan.plan_hash, confirmed=True)
            )
        except HarnessServiceError as error:
            raise WorkspaceBootstrapError(f"{adapter_id}: {error}") from error
        wirings.append(McpWiring(adapter_id, plan, applied=True, state=result.state))
    return wirings
