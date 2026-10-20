"""`skills.check`: read-only Library skill state over the daemon bridge."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.context.library import LibraryContextItem
from studio_client.daemon import skills_bridge
from studio_client.daemon.local_features import LocalFeatureError
from studio_client.daemon.service import BridgeService, DaemonController
from studio_client.errors import AuthenticationError, StudioApiError
from studio_client.skill_sync import apply_skill_sync, plan_skill_sync
from studio_client.tokens import MemoryTokenStore
from studio_contracts.local.bridge import BridgeRequest
from studio_contracts.local.handshake import HandshakeRequest
from studio_contracts.local.skills import (
    SkillResolution,
    SkillsApplyRequest,
    SkillsCheckResult,
    SkillsConfigureRequest,
)


def test_targeted_choices_preserve_other_skills_and_their_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    projections = [_projection(key) for key in ("delegate", "graphify", "studio-task")]
    apply_skill_sync(plan_skill_sync(home, projections))
    for key in ("delegate", "graphify", "studio-task"):
        (home / ".agents" / "skills" / key / "SKILL.md").write_text(
            f"Local {key}\n", encoding="utf-8"
        )
    _patch_fetch(monkeypatch, projections)
    controller = _controller(tmp_path / "data", home)
    preview = controller.skills_preview()
    assert all(entry.preview_hash and entry.diff for entry in preview.skills)
    tokens = {entry.stable_key: entry.preview_hash for entry in preview.skills}
    before = _snapshot(home)
    manifest_before = json.loads((home / ".studio-os" / "library-skills-manifest.json").read_text())
    result = controller.skills_apply(
        SkillsApplyRequest(
            confirm=True,
            resolutions=[
                SkillResolution(
                    stable_key="delegate", choice="library", preview_hash=tokens["delegate"]
                ),
                SkillResolution(
                    stable_key="graphify", choice="local", preview_hash=tokens["graphify"]
                ),
            ],
        )
    )
    assert len(result.backups) == 1
    assert Path(result.backups[0]).read_text() == "Local delegate\n"
    assert all("delegate" in path for path in result.written)
    assert set(result.conflicts) == {
        ".agents/skills/graphify/SKILL.md",
        ".agents/skills/studio-task/SKILL.md",
    }
    after = _snapshot(home)
    for name, content in before.items():
        if "graphify" in name or "studio-task" in name:
            assert after[name] == content
    manifest_after = json.loads((home / ".studio-os" / "library-skills-manifest.json").read_text())
    assert [row for row in manifest_after["skills"] if row["stable_key"] != "delegate"] == [
        row for row in manifest_before["skills"] if row["stable_key"] != "delegate"
    ]
    status = controller.skills_status()
    assert status.state == "conflicts"
    assert status.last_successful_sync is None


def test_keep_only_does_not_write_skills_or_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    apply_skill_sync(plan_skill_sync(home, [_projection("delegate")]))
    (home / ".agents" / "skills" / "delegate" / "SKILL.md").write_text("Local\n", encoding="utf-8")
    _patch_fetch(monkeypatch, [_projection("delegate")])
    controller = _controller(tmp_path / "data", home)
    token = controller.skills_preview().skills[0].preview_hash
    before = _snapshot(home)
    result = controller.skills_apply(
        SkillsApplyRequest(
            confirm=True,
            resolutions=[
                SkillResolution(stable_key="delegate", choice="local", preview_hash=token)
            ],
        )
    )
    assert result.written == result.backups == []
    assert _snapshot(home) == before
    assert result.conflicts == [".agents/skills/delegate/SKILL.md"]
    assert controller.skills_status().last_successful_sync is None


@pytest.mark.parametrize("change", ["local", "library", "unknown"])
def test_targeted_apply_rejects_stale_or_unknown_choices_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    home = tmp_path / "home"
    _patch_fetch(monkeypatch, [_projection("delegate")])
    controller = _controller(tmp_path / "data", home)
    token = controller.skills_preview().skills[0].preview_hash
    if change == "local":
        target = home / ".agents" / "skills" / "delegate" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("Edited after preview", encoding="utf-8")
    elif change == "library":
        _patch_fetch(monkeypatch, [_projection("delegate", version=4)])
    before = _snapshot(home)
    with pytest.raises(LocalFeatureError) as exc:
        controller.skills_apply(
            SkillsApplyRequest(
                confirm=True,
                resolutions=[
                    SkillResolution(
                        stable_key="unknown" if change == "unknown" else "delegate",
                        choice="library",
                        preview_hash=token,
                    )
                ],
            )
        )
    assert exc.value.error.code.value == "invalid_request"
    assert _snapshot(home) == before


def test_resolution_request_rejects_empty_duplicates_and_global_overwrite() -> None:
    resolution = SkillResolution(stable_key="delegate", choice="library", preview_hash="a" * 64)
    for payload in (
        {"resolutions": []},
        {"resolutions": [resolution, resolution]},
        {"overwrite": True, "resolutions": [resolution]},
    ):
        with pytest.raises(ValueError):
            SkillsApplyRequest(confirm=True, **payload)


def test_resolution_preview_is_gated_for_older_desktop_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_fetch(monkeypatch, [_projection("delegate")])
    controller = _controller(tmp_path / "data", tmp_path / "home")
    controller.skills_configure(SkillsConfigureRequest(auto_sync=False))
    service = BridgeService(controller)
    _negotiate(service, ["daemon.control", "skills.read", "skills.apply"])
    legacy = service.handle_line(_line("skills.preview", {}))
    assert "preview_hash" not in legacy["payload"]["skills"][0]
    token = controller.skills_preview().skills[0].preview_hash
    request = {
        "confirm": True,
        "resolutions": [{"stable_key": "delegate", "choice": "library", "preview_hash": token}],
    }
    denied = service.handle_line(_line("skills.apply", request))
    assert denied["error"]["code"] == "capability_missing"
    _negotiate(service, ["daemon.control", "skills.read", "skills.apply", "skills.resolve"])
    modern = service.handle_line(_line("skills.preview", {}))
    assert modern["payload"]["skills"][0]["preview_hash"] == token
    assert service.handle_line(_line("skills.apply", request))["kind"] == "response"


ORIGIN = "https://studio.example"


def _projection(key: str = "studio-git-flow", version: int = 3) -> LibraryContextItem:
    return LibraryContextItem(
        library_kind="skill",
        stable_key=key,
        version=version,
        version_origin="active",
        scope="studio",
        title="Studio Git Flow",
        text="# Git flow\n\nSECRET-BODY-MARKER",
        content_schema="studio.library.skill/v1",
    )


def _controller(tmp_path: Path, home: Path, token: str | None = "tok") -> DaemonController:
    store = MemoryTokenStore()
    if token:
        store.set_token(ORIGIN, token)
    config = ClientConfig(api_base_url=f"{ORIGIN}/api/v1", profile_id="main", machine_id=uuid4())
    return DaemonController(config, data_root=tmp_path, token_store=store, skills_home=lambda: home)


def _patch_fetch(monkeypatch: pytest.MonkeyPatch, result) -> None:
    async def fake(config, token_store):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(skills_bridge, "_fetch_skills_only", fake)
    monkeypatch.setattr(skills_bridge, "_fetch", fake)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _line(command: str, payload: dict) -> str:
    return BridgeRequest.model_validate(
        {
            "message_id": f"msg-{uuid4().hex[:16]}",
            "correlation_id": f"corr-{uuid4().hex[:16]}",
            "sent_at": "2026-09-21T00:00:00Z",
            "command": command,
            "payload": payload,
        }
    ).model_dump_json()


def _negotiate(service: BridgeService, capabilities: list[str]) -> dict:
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
            }
        }
    )
    return service.handle_line(_line("runtime.handshake", payload.model_dump(mode="json")))


def test_all_missing_then_in_sync_after_apply(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    projections = [_projection()]
    _patch_fetch(monkeypatch, projections)
    controller = _controller(tmp_path, home)

    before = controller.skills_check()
    assert (before.missing, before.current, before.in_sync) == (2, 0, False)
    assert _snapshot(home) == {}

    apply_skill_sync(plan_skill_sync(home, projections))
    written = _snapshot(home)
    after = controller.skills_check()
    assert (after.missing, after.current, after.in_sync) == (0, 2, True)
    assert _snapshot(home) == written


def test_locally_modified_and_outdated_reported(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    apply_skill_sync(plan_skill_sync(home, [_projection(version=3)]))
    target = home / ".claude" / "skills" / "studio-git-flow" / "SKILL.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
    _patch_fetch(monkeypatch, [_projection(version=3)])
    result = _controller(tmp_path, home).skills_check()
    assert result.locally_modified == 1 and not result.in_sync

    _patch_fetch(monkeypatch, [_projection(version=4)])
    result = _controller(tmp_path, home).skills_check()
    assert result.outdated + result.locally_modified >= 1 and not result.in_sync


def test_served_over_bridge_without_path_or_content(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _patch_fetch(monkeypatch, [_projection()])
    service = BridgeService(_controller(tmp_path, home))
    _negotiate(service, ["daemon.control", "skills.read"])
    answer = service.handle_line(_line("skills.check", {}))
    assert answer["kind"] == "response", answer
    raw = json.dumps(answer, default=str)
    assert "SECRET-BODY-MARKER" not in raw
    assert str(tmp_path) not in raw and "SKILL.md" not in raw
    SkillsCheckResult.model_validate(answer["payload"])


def test_denied_without_capability(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _patch_fetch(monkeypatch, [_projection()])
    service = BridgeService(_controller(tmp_path, home))
    _negotiate(service, ["daemon.control"])
    answer = service.handle_line(_line("skills.check", {}))
    assert answer["kind"] != "response", answer


def test_handshake_offers_skills_read(tmp_path: Path) -> None:
    service = BridgeService(_controller(tmp_path, tmp_path))
    answer = _negotiate(service, ["daemon.control", "skills.read"])
    assert "skills.read" in json.dumps(answer)


def test_token_absent(tmp_path: Path) -> None:
    with pytest.raises(LocalFeatureError) as err:
        _controller(tmp_path, tmp_path, token=None).skills_check()
    assert err.value.error.code.value == "secret_absent"


@pytest.mark.parametrize(
    ("exc", "code", "retryable"),
    [
        (AuthenticationError(401, "unauthorized", "no"), "secret_revoked", False),
        (StudioApiError(503, "down", "down"), "internal_error", True),
    ],
)
def test_upstream_errors_are_mapped(tmp_path: Path, monkeypatch, exc, code, retryable) -> None:
    _patch_fetch(monkeypatch, exc)
    with pytest.raises(LocalFeatureError) as err:
        _controller(tmp_path, tmp_path).skills_check()
    assert err.value.error.code.value == code
    assert err.value.error.retryable is retryable
    assert str(tmp_path) not in err.value.error.message


def test_skills_check_does_not_use_definition_endpoint(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()

    async def skills_only(_api, _project_id, limit: int = 100):
        return (_projection(),)

    async def definitions_fail(*_args, **_kwargs):
        raise RuntimeError("agent_definition endpoint unavailable")

    monkeypatch.setattr(skills_bridge, "fetch_skill_projections", skills_only)
    monkeypatch.setattr(skills_bridge, "fetch_library_projections", definitions_fail)
    checked = _controller(tmp_path, home).skills_check()

    assert [entry.stable_key for entry in checked.skills] == ["studio-git-flow"]


def _definition(
    key: str = "studio-protocol", kind: str = "rule", text: str = "# Rule\n\nLibrary body\n"
) -> LibraryContextItem:
    return LibraryContextItem(
        library_kind=kind,
        stable_key=key,
        version=2,
        version_origin="active",
        scope="studio",
        title=key,
        text=text,
        content_schema=f"studio.library.{kind}/v1",
    )


def _definitions_home(tmp_path: Path) -> tuple[Path, list[LibraryContextItem]]:
    home = tmp_path / "home"
    projections = [_projection(), _definition(), _definition("reviewer", "agent_definition")]
    skill_plan, definition_plan = skills_bridge.plan_library_sync(home, projections)
    apply_skill_sync(skill_plan)
    skills_bridge.apply_definition_sync(definition_plan)
    for relative in (".agents/rules/studio-protocol.md", ".claude/agents/reviewer.md"):
        (home / relative).write_text("Local edit\n", encoding="utf-8")
    return home, projections


def test_preview_lists_rule_and_agent_conflicts_with_diff(tmp_path: Path, monkeypatch) -> None:
    home, projections = _definitions_home(tmp_path)
    _patch_fetch(monkeypatch, projections)
    preview = _controller(tmp_path / "data", home).skills_preview()

    by_kind = {(entry.kind.value, entry.stable_key): entry for entry in preview.skills}
    assert set(by_kind) == {
        ("skill", "studio-git-flow"),
        ("rule", "studio-protocol"),
        ("agent", "reviewer"),
    }
    rule = by_kind[("rule", "studio-protocol")]
    assert "locally_modified" in {target.state for target in rule.targets}
    assert "-Local edit" in rule.diff and ".agents/rules/studio-protocol.md" in rule.diff
    assert preview.locally_modified == 0


def test_targeted_rule_choice_backs_up_and_keeps_other_definitions(
    tmp_path: Path, monkeypatch
) -> None:
    home, projections = _definitions_home(tmp_path)
    _patch_fetch(monkeypatch, projections)
    controller = _controller(tmp_path / "data", home)
    preview = controller.skills_preview()
    tokens = {(entry.kind.value, entry.stable_key): entry.preview_hash for entry in preview.skills}
    manifest_path = home / ".studio-os" / "library-definitions-manifest.json"
    manifest_before = json.loads(manifest_path.read_text())

    result = controller.skills_apply(
        SkillsApplyRequest(
            confirm=True,
            resolutions=[
                SkillResolution(
                    kind="rule",
                    stable_key="studio-protocol",
                    choice="library",
                    preview_hash=tokens[("rule", "studio-protocol")],
                ),
            ],
        )
    )

    rule_path = home / ".agents" / "rules" / "studio-protocol.md"
    assert "Library body" in rule_path.read_text(encoding="utf-8")
    assert [Path(p).read_text() for p in result.backups] == ["Local edit\n"]
    assert (home / ".claude" / "agents" / "reviewer.md").read_text() == "Local edit\n"
    assert result.conflicts == [".claude/agents/reviewer.md"]
    manifest_after = json.loads(manifest_path.read_text())
    assert [row for row in manifest_after["items"] if row["kind"] == "agent"] == [
        row for row in manifest_before["items"] if row["kind"] == "agent"
    ]
    assert controller.skills_status().state == "conflicts"


def test_definition_resolutions_require_capability(tmp_path: Path, monkeypatch) -> None:
    home, projections = _definitions_home(tmp_path)
    _patch_fetch(monkeypatch, projections)
    controller = _controller(tmp_path / "data", home)
    controller.skills_configure(SkillsConfigureRequest(auto_sync=False))
    service = BridgeService(controller)
    base = ["daemon.control", "skills.read", "skills.apply", "skills.resolve"]
    _negotiate(service, base)
    legacy = service.handle_line(_line("skills.preview", {}))["payload"]["skills"]
    assert [entry["stable_key"] for entry in legacy] == ["studio-git-flow"]
    assert all("kind" not in entry for entry in legacy)
    token = next(
        entry.preview_hash
        for entry in controller.skills_preview().skills
        if entry.stable_key == "studio-protocol"
    )
    request = {
        "confirm": True,
        "resolutions": [
            {
                "kind": "rule",
                "stable_key": "studio-protocol",
                "choice": "library",
                "preview_hash": token,
            }
        ],
    }
    denied = service.handle_line(_line("skills.apply", request))
    assert denied["error"]["code"] == "capability_missing"
    _negotiate(service, [*base, "skills.definitions"])
    modern = service.handle_line(_line("skills.preview", {}))["payload"]["skills"]
    assert {entry["kind"] for entry in modern} == {"skill", "rule", "agent"}
    assert service.handle_line(_line("skills.apply", request))["kind"] == "response"


def _modified_home(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    apply_skill_sync(plan_skill_sync(home, [_projection()]))
    target = home / ".claude" / "skills" / "studio-git-flow" / "SKILL.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
    return home, target


def test_apply_refuses_conflicts_without_overwrite(tmp_path: Path, monkeypatch) -> None:
    home, target = _modified_home(tmp_path)
    _patch_fetch(monkeypatch, [_projection()])
    controller = _controller(tmp_path, home)
    with pytest.raises(LocalFeatureError):
        controller.skills_apply(SkillsApplyRequest(confirm=True))
    assert "local edit" in target.read_text(encoding="utf-8")


def test_apply_overwrite_backs_up_and_resolves_conflicts(tmp_path: Path, monkeypatch) -> None:
    home, target = _modified_home(tmp_path)
    _patch_fetch(monkeypatch, [_projection()])
    controller = _controller(tmp_path, home)
    result = controller.skills_apply(SkillsApplyRequest(confirm=True, overwrite=True))
    assert result.conflicts == [] and result.backups
    assert "local edit" not in target.read_text(encoding="utf-8")
    assert controller.skills_status().state.value == "updated"


def test_configure_disables_and_persists_the_setting(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _patch_fetch(monkeypatch, [_projection()])
    controller = _controller(tmp_path, home)
    status = controller.skills_configure(SkillsConfigureRequest(auto_sync=False))
    assert status.state.value == "disabled" and not status.auto_sync_enabled
    assert controller.skills_status().state.value == "disabled"
    assert not skills_bridge.auto_sync_enabled(controller.config, tmp_path)
    skills_bridge.start_auto_sync(controller.config, controller._token_store, home, tmp_path)
    assert _snapshot(home) == {}
    runner = skills_bridge._AutoSyncRunner(
        controller.config, controller._token_store, home, tmp_path
    )

    def start(*_args: object) -> skills_bridge._AutoSyncRunner:
        runner.start()
        return runner

    monkeypatch.setattr(skills_bridge, "start_auto_sync", start)
    status = controller.skills_configure(SkillsConfigureRequest(auto_sync=True))
    assert status.state.value == "in_progress"
    assert skills_bridge.auto_sync_enabled(controller.config, tmp_path)
    assert runner._thread is not None
    runner._thread.join(timeout=5)
    assert not runner._thread.is_alive()
