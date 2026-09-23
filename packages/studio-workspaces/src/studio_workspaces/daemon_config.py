from __future__ import annotations

from dataclasses import dataclass, field

from studio_contracts.local.workspace import LocalWorkspaceConfig


@dataclass(frozen=True)
class WatchPlan:
    enabled: bool
    repo_paths: list[str] = field(default_factory=list)
    debounce_ms: int = 500
    ignore_globs: list[str] = field(default_factory=list)
    max_events_per_second: int = 200


def daemon_watch_plan(config: LocalWorkspaceConfig) -> WatchPlan:
    if not config.features.watchers:
        return WatchPlan(enabled=False)
    watchers = config.watchers
    if watchers is None:
        return WatchPlan(enabled=False)
    repos = [repo.path for repo in config.roots.repo_roots] or [config.roots.workspace_root]
    return WatchPlan(
        enabled=True,
        repo_paths=repos,
        debounce_ms=watchers.debounce_ms,
        ignore_globs=list(watchers.ignore_globs),
        max_events_per_second=watchers.max_events_per_second,
    )
