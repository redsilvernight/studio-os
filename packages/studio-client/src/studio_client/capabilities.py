from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from studio_contracts.auth import HarnessReport, MachineCapabilities

from studio_client.config import ClientConfig
from studio_client.harness.base import DetectionState, HarnessContext
from studio_client.harness.registry import HarnessRegistry, default_adapters

CapabilitiesProvider = Callable[[], MachineCapabilities | None]


def neutral_context(config: ClientConfig) -> HarnessContext:
    """Probing context for harness detection. Paths stay machine-local —
    only IDs and stable tokens ever leave in the report."""
    cwd = Path.cwd()
    return HarnessContext(
        workspace_root=cwd,
        mcp_url=config.api_base_url,
        env=dict(os.environ),
        probe_cwd=cwd,
    )


def registered_project_ids(config: ClientConfig) -> list[UUID]:
    """Registered project UUIDs from watcher configuration — IDs only,
    never a repository path."""
    seen: set[UUID] = set()
    ordered: list[UUID] = []
    candidates = [watch.project_id for watch in config.git_watches]
    if config.godot_watch_project_id is not None:
        candidates.append(config.godot_watch_project_id)
    for project_id in candidates:
        if project_id not in seen:
            seen.add(project_id)
            ordered.append(project_id)
    return sorted(ordered)


def build_capabilities(
    config: ClientConfig,
    *,
    registry: HarnessRegistry | None = None,
    ctx: HarnessContext | None = None,
    running_launches: int = 0,
) -> MachineCapabilities:
    """Pure report builder: detected harnesses (IDs + state + version),
    registered project IDs, launch opt-in and occupancy."""
    active_registry = registry if registry is not None else HarnessRegistry(default_adapters())
    active_ctx = ctx if ctx is not None else neutral_context(config)
    harnesses = [
        HarnessReport(
            harness_id=adapter.harness_id,
            detected=detection.state is not DetectionState.NOT_INSTALLED
            and detection.state is not DetectionState.UNAVAILABLE,
            configured=detection.state is DetectionState.CONFIGURED,
            version=detection.version,
        )
        for adapter, detection in active_registry.detect_all(active_ctx)
    ]
    harnesses.sort(key=lambda entry: entry.harness_id)
    return MachineCapabilities(
        harnesses=harnesses,
        project_ids=registered_project_ids(config),
        accepts_launches=config.launch_opt_in,
        running_launches=running_launches,
        max_launches=config.max_concurrent_launches,
    )
