from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from studio_client import cli
from studio_client.hook_sync import (
    HookProjection,
    HookSyncError,
    apply_hook_sync,
    diff_hook_plan,
    fetch_hook_projections,
    plan_hook_sync,
)
from studio_contracts.library import HookContent, HookOs


@dataclass
class _Resource:
    id: UUID
    stable_key: str
    scope: str = "studio"
    project_id: UUID | None = None
    kind: str = "hook"
    status: str = "active"
    active_version: int = 1


@dataclass
class _Version:
    resource_id: UUID
    version: int
    title: str
    content: dict[str, Any] = field(default_factory=dict)


class _FakeApi:
    def __init__(self, resources: list[_Resource], versions: list[_Version]) -> None:
        self.resources = resources
        self.versions = versions

    async def list_library_resources(self, *, limit: int) -> list[_Resource]:
        return self.resources[:limit]

    async def list_library_locks(self, *, project_id: UUID | None) -> list[Any]:
        return []

    async def list_library_versions(self, resource_id: UUID) -> list[_Version]:
        return [row for row in self.versions if row.resource_id == resource_id]


def _content(body: str = "echo guard\n", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content_schema": "studio.library.hook/v1",
        "event": "pre_tool",
        "matcher": "Bash",
        "mode": "blocking",
        "timeout_seconds": 15,
        "scripts": [{"os": "any", "shell": "bash", "body": body}],
    }
    payload.update(overrides)
    return payload


class _Provider:
    """Fake library: one active hook per key, versions held in memory."""

    def __init__(self) -> None:
        self.resources: dict[str, _Resource] = {}
        self.versions: list[_Version] = []

    def publish(self, key: str, version: int, content: dict[str, Any]) -> None:
        resource = self.resources.setdefault(key, _Resource(id=uuid4(), stable_key=key))
        resource.active_version = version
        if not any(
            row.resource_id == resource.id and row.version == version for row in self.versions
        ):
            self.versions.append(_Version(resource.id, version, f"Hook {key}", content))

    def deprecate(self, key: str) -> None:
        self.resources[key].status = "deprecated"

    def projections(self) -> tuple[HookProjection, ...]:
        api = _FakeApi(list(self.resources.values()), self.versions)
        return asyncio.run(fetch_hook_projections(api, None))


def _settings(home: Path) -> dict[str, Any]:
    return json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))


def _script(home: Path, key: str = "guard") -> Path:
    return home / ".claude" / "studio-hooks" / f"{key}.sh"


def _sync(home: Path, provider: _Provider, **kwargs: Any) -> Any:
    plan = plan_hook_sync(home, provider.projections(), os_name=HookOs.LINUX, **kwargs)
    return plan, apply_hook_sync(plan)


_UNMANAGED = {
    "matcher": "Write",
    "hooks": [{"type": "command", "command": "my-own-guard", "timeout": 5}],
}


def _seed_settings(home: Path) -> None:
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"model": "opus", "hooks": {"PreToolUse": [_UNMANAGED]}}, indent=2) + "\n",
        encoding="utf-8",
    )


def test_needs_consent_then_installs_after_consent(tmp_path: Path) -> None:
    provider = _Provider()
    provider.publish("guard", 1, _content())

    plan, result = _sync(tmp_path, provider)

    assert [entry.status for entry in plan.entries] == ["needs_consent"]
    assert result.written == ()
    assert not _script(tmp_path).exists()
    assert not (tmp_path / ".claude" / "settings.json").exists()

    plan, _ = _sync(tmp_path, provider, consent=["guard"])

    assert [entry.status for entry in plan.entries] == ["installed"]
    assert _script(tmp_path).read_text(encoding="utf-8") == "echo guard\n"
    consent = json.loads((tmp_path / ".studio" / "hook-consent.json").read_text("utf-8"))
    assert consent == {"guard": plan.entries[0].projection.fingerprint}
    groups = _settings(tmp_path)["hooks"]["PreToolUse"]
    assert groups == [
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": plan.entries[0].command, "timeout": 15}],
        }
    ]
    assert "studio-hooks/guard.sh" in plan.entries[0].command
    assert "codex:not_supported" in plan.entries[0].reports
    plugin = tmp_path / ".config" / "opencode" / "plugin" / "studio-hooks.js"
    assert '"tool.execute.before"' in plugin.read_text(encoding="utf-8")


def test_merge_preserves_unmanaged_hook_and_other_settings(tmp_path: Path) -> None:
    _seed_settings(tmp_path)
    provider = _Provider()
    provider.publish("guard", 1, _content())

    _, result = _sync(tmp_path, provider, consent=["guard"])

    settings = _settings(tmp_path)
    assert settings["model"] == "opus"
    assert settings["hooks"]["PreToolUse"][0] == _UNMANAGED
    assert len(settings["hooks"]["PreToolUse"]) == 2
    assert len(result.backups) == 1


def test_second_sync_is_idempotent(tmp_path: Path) -> None:
    _seed_settings(tmp_path)
    provider = _Provider()
    provider.publish("guard", 1, _content())
    _sync(tmp_path, provider, consent=["guard"])
    before = (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")

    plan, result = _sync(tmp_path, provider)

    assert plan.is_current
    assert plan.pending == ()
    assert result.written == () and result.deleted == () and result.backups == ()
    assert (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8") == before


def test_new_version_requires_new_consent(tmp_path: Path) -> None:
    _seed_settings(tmp_path)
    provider = _Provider()
    provider.publish("guard", 1, _content())
    _sync(tmp_path, provider, consent=["guard"])

    provider.publish("guard", 2, _content("echo guard v2\n"))
    plan, result = _sync(tmp_path, provider)

    assert [entry.status for entry in plan.entries] == ["needs_consent"]
    assert plan.removed == ("guard",)
    assert _script(tmp_path) in result.deleted
    assert _settings(tmp_path)["hooks"]["PreToolUse"] == [_UNMANAGED]

    _sync(tmp_path, provider, consent=["guard"])

    assert _script(tmp_path).read_text(encoding="utf-8") == "echo guard v2\n"


def test_deprecated_hook_is_removed_cleanly(tmp_path: Path) -> None:
    _seed_settings(tmp_path)
    provider = _Provider()
    provider.publish("guard", 1, _content())
    _sync(tmp_path, provider, consent=["guard"])

    provider.deprecate("guard")
    plan, _ = _sync(tmp_path, provider)

    assert plan.entries == ()
    assert plan.removed == ("guard",)
    assert not _script(tmp_path).exists()
    assert not (tmp_path / ".config" / "opencode" / "plugin" / "studio-hooks.js").exists()
    assert _settings(tmp_path)["hooks"] == {"PreToolUse": [_UNMANAGED]}
    manifest = json.loads(plan.manifest_path.read_text(encoding="utf-8"))
    assert manifest["hooks"] == []


def test_version_rollback_reinstalls_previous_body(tmp_path: Path) -> None:
    provider = _Provider()
    provider.publish("guard", 1, _content("echo v1\n"))
    _sync(tmp_path, provider, consent=["guard"])
    provider.publish("guard", 2, _content("echo v2\n"))
    _sync(tmp_path, provider, consent=["guard"])
    assert _script(tmp_path).read_text(encoding="utf-8") == "echo v2\n"

    provider.publish("guard", 1, _content("echo v1\n"))
    plan, _ = _sync(tmp_path, provider)
    assert [entry.status for entry in plan.entries] == ["needs_consent"]

    plan, _ = _sync(tmp_path, provider, consent=["guard"])

    assert plan.entries[0].projection.version == 1
    assert _script(tmp_path).read_text(encoding="utf-8") == "echo v1\n"
    manifest = json.loads(plan.manifest_path.read_text(encoding="utf-8"))
    assert manifest["hooks"][0]["version"] == 1


def test_disable_removes_installation(tmp_path: Path) -> None:
    provider = _Provider()
    provider.publish("guard", 1, _content())
    _sync(tmp_path, provider, consent=["guard"])

    plan, _ = _sync(tmp_path, provider, disable=["guard"])

    assert [entry.status for entry in plan.entries] == ["disabled"]
    assert not _script(tmp_path).exists()
    assert _settings(tmp_path)["hooks"] == {}
    disabled = json.loads((tmp_path / ".studio" / "hook-disabled.json").read_text("utf-8"))
    assert disabled == ["guard"]


def test_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = _Provider()
    provider.publish("guard", 1, _content())
    monkeypatch.setattr(cli, "_load_config", lambda: object())
    monkeypatch.setattr(cli, "_run", lambda _config, _action: provider.projections())

    cli.main(
        [
            "hooks-library",
            "sync",
            "--home",
            str(tmp_path),
            "--consent",
            "guard",
            "--dry-run",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["hooks"][0]["status"] == "installed"
    assert payload["failures"] > 0
    assert list(tmp_path.iterdir()) == []


def test_cli_sync_then_check_is_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = _Provider()
    provider.publish("guard", 1, _content())
    monkeypatch.setattr(cli, "_load_config", lambda: object())
    monkeypatch.setattr(cli, "_run", lambda _config, _action: provider.projections())

    with pytest.raises(SystemExit, match="1"):
        cli.main(["hooks-library", "check", "--home", str(tmp_path), "--json"])
    cli.main(["hooks-library", "sync", "--home", str(tmp_path), "--consent", "guard", "--json"])
    capsys.readouterr()

    cli.main(["hooks-library", "check", "--home", str(tmp_path), "--json"])
    assert json.loads(capsys.readouterr().out)["failures"] == 0


def test_os_variant_selection_and_unsupported_harness_events(tmp_path: Path) -> None:
    provider = _Provider()
    provider.publish(
        "notify",
        1,
        _content(
            event="notification",
            matcher=None,
            mode="advisory",
            scripts=[{"os": "windows", "shell": "pwsh", "body": "Write-Host hi"}],
        ),
    )
    projections = provider.projections()

    linux = plan_hook_sync(tmp_path, projections, consent=["notify"], os_name=HookOs.LINUX)
    assert linux.entries[0].status == "no_variant"
    assert "no_variant:linux" in linux.entries[0].reports

    windows = plan_hook_sync(tmp_path, projections, consent=["notify"], os_name=HookOs.WINDOWS)
    entry = windows.entries[0]
    assert entry.status == "installed"
    assert entry.claude_event == "Notification"
    assert entry.opencode_event is None
    assert "opencode:event_not_expressible:notification" in entry.reports
    assert entry.command is not None and entry.command.startswith("pwsh -NoProfile -File ")
    assert "studio-hooks.js" not in diff_hook_plan(windows)


def test_consent_to_unknown_hook_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(HookSyncError, match="unknown"):
        plan_hook_sync(tmp_path, (), consent=["ghost"])


def test_fingerprint_is_canonical() -> None:
    first = HookProjection("k", 1, "active", "studio", "t", HookContent.model_validate(_content()))
    reordered = dict(reversed(list(_content().items())))
    second = HookProjection("k", 2, "active", "studio", "t", HookContent.model_validate(reordered))
    assert first.fingerprint == second.fingerprint
