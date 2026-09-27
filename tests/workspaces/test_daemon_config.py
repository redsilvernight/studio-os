from __future__ import annotations

from uuid import UUID

from studio_contracts.local.workspace import LocalFeatures, LocalWorkspaceConfig, WatcherConfig
from studio_workspaces.daemon_config import daemon_watch_plan

from .factories import make_config

WS_ID = UUID("11111111-1111-4111-8111-111111111111")


def test_git_watching_is_on_by_default() -> None:
    config = make_config(WS_ID, "C:/Work/demo")
    assert config.features.watchers is True
    assert config.watchers == WatcherConfig()
    plan = daemon_watch_plan(config)
    assert plan.enabled is True
    assert plan.repo_paths == ["C:/Work/demo"]


def test_default_is_filled_from_a_stored_payload_without_watcher_config() -> None:
    payload = make_config(WS_ID, "C:/Work/demo").model_dump(mode="json")
    del payload["features"]
    payload["watchers"] = None
    config = LocalWorkspaceConfig.model_validate(payload)
    assert config.watchers == WatcherConfig()


def test_disabled_watchers_yield_no_watch_plan() -> None:
    payload = make_config(WS_ID, "C:/Work/demo").model_dump(mode="json")
    payload["features"]["watchers"] = False
    payload["watchers"] = None
    plan = daemon_watch_plan(LocalWorkspaceConfig.model_validate(payload))
    assert plan.enabled is False
    assert plan.repo_paths == []


def test_enabled_watchers_yield_repo_plan() -> None:
    config = make_config(WS_ID, "C:/Work/demo", [("game", "C:/Work/demo/game")])
    enabled = config.model_copy(
        update={
            "features": LocalFeatures(watchers=True),
            "watchers": WatcherConfig(),
        }
    )
    plan = daemon_watch_plan(enabled)
    assert plan.enabled is True
    assert plan.repo_paths == ["C:/Work/demo/game"]
    assert plan.debounce_ms == 500
    assert ".git/**" in plan.ignore_globs


def test_enabled_feature_without_config_stays_off() -> None:
    config = make_config(WS_ID, "C:/Work/demo")
    broken = config.model_copy(update={"features": LocalFeatures(watchers=True), "watchers": None})
    plan = daemon_watch_plan(broken)
    assert plan.enabled is False
