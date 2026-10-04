"""« Configurer ce poste »: `setup.plan` / `setup.apply` and the engine behind them."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from studio_client import machine_setup
from studio_client.config import ClientConfig
from studio_client.context.library import LibraryContextItem
from studio_client.daemon import skills_bridge
from studio_client.daemon.local_features import LocalFeatureError
from studio_client.daemon.service import BridgeService, DaemonController
from studio_client.daemon.setup_bridge import SetupBridge
from studio_client.hooks import HARNESSES, MANAGED_MARKER
from studio_client.tokens import MemoryTokenStore
from studio_contracts.local.bridge import BridgeRequest
from studio_contracts.local.handshake import HandshakeRequest
from studio_contracts.local.machine_setup import (
    SetupAdaptersState,
    SetupApplyRequest,
    SetupApplyResult,
    SetupItemOutcome,
    SetupItemState,
    SetupPlan,
    SetupSkillsOutcome,
    SetupSkillsState,
    SetupUnavailableReason,
)

ORIGIN = "https://studio.example"
SPECS = {spec.harness: spec for spec in HARNESSES}


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


def _patch_fetch(monkeypatch: pytest.MonkeyPatch, result) -> None:
    async def fake(config, token_store):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(skills_bridge, "_fetch", fake)


def _bridge(home: Path, *, token: str | None = "tok", roots: tuple[Path, ...] = ()) -> SetupBridge:
    store = MemoryTokenStore()
    if token:
        store.set_token(ORIGIN, token)
    config = ClientConfig(api_base_url=f"{ORIGIN}/api/v1", profile_id="main", machine_id=uuid4())
    return SetupBridge(config, store, home=lambda: home, roots=lambda: roots, path_dirs=lambda: ())


def _home(tmp_path: Path, *harnesses: str) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    for name in harnesses:
        marker = SPECS[name].config_markers[0]
        (home / marker).parent.mkdir(parents=True, exist_ok=True)
        (home / marker).write_text("{}", encoding="utf-8")
    return home


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _request(plan: SetupPlan, **kwargs) -> SetupApplyRequest:
    return SetupApplyRequest(
        plan_id=plan.plan_id, plan_hash=plan.plan_hash, confirmed=True, **kwargs
    )


def _outcomes(result: SetupApplyResult) -> dict[str, SetupItemOutcome]:
    return {item.item_id: item.outcome for item in result.hooks}


def test_plan_is_read_only_and_reports_every_step(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "claude-code")
    _patch_fetch(monkeypatch, [_projection()])
    before = _snapshot(home)
    plan = _bridge(home).plan()
    assert _snapshot(home) == before
    assert {h.harness: h.detected for h in plan.harnesses}["claude-code"] is True
    assert {item.item_id for item in plan.hooks} == {"hook:claude-code", "guard"}
    assert all(item.state is SetupItemState.MISSING for item in plan.hooks)
    assert plan.skills.state is SetupSkillsState.CHECKED and plan.skills.missing == 2
    assert plan.adapters.state is SetupAdaptersState.NOT_APPLICABLE
    hook = next(item for item in plan.hooks if item.item_id == "hook:claude-code")
    assert hook.needs_registration is True


def test_apply_writes_then_second_run_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "claude-code", "opencode")
    _patch_fetch(monkeypatch, [_projection()])
    bridge = _bridge(home)
    plan = bridge.plan()
    first = bridge.apply(_request(plan))
    assert set(_outcomes(first).values()) == {SetupItemOutcome.WRITTEN}
    assert first.skills.outcome is SetupSkillsOutcome.SYNCED and first.skills.written == 2
    assert not first.backups_created

    settled = _snapshot(home)
    again = bridge.plan()
    assert all(item.state is SetupItemState.CURRENT for item in again.hooks)
    second = bridge.apply(_request(again))
    assert set(_outcomes(second).values()) == {SetupItemOutcome.UNCHANGED}
    assert second.skills.outcome is SetupSkillsOutcome.UNCHANGED
    assert _snapshot(home) == settled


def test_foreign_hook_is_never_overwritten_silently(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "codex")
    foreign = home / SPECS["codex"].hook_rel
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("# my own hook\nwrite-host 'mine'\n", encoding="utf-8")
    _patch_fetch(monkeypatch, [])
    bridge = _bridge(home)
    plan = bridge.plan()
    item = next(i for i in plan.hooks if i.item_id == "hook:codex")
    assert item.state is SetupItemState.DIFFERS and item.managed is False
    assert "my own hook" in item.diff and item.lines_added and item.lines_removed

    result = bridge.apply(_request(plan))
    assert _outcomes(result)["hook:codex"] is SetupItemOutcome.SKIPPED
    assert foreign.read_text(encoding="utf-8").startswith("# my own hook")
    assert not (home / ".studio-os" / "backups").exists()


def test_named_overwrite_backs_up_first(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "codex")
    foreign = home / SPECS["codex"].hook_rel
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("# my own hook\n", encoding="utf-8")
    _patch_fetch(monkeypatch, [])
    bridge = _bridge(home)
    plan = bridge.plan()
    result = bridge.apply(_request(plan, overwrite_items=["hook:codex"]))
    assert _outcomes(result)["hook:codex"] is SetupItemOutcome.WRITTEN
    assert result.backups_created
    assert MANAGED_MARKER in foreign.read_text(encoding="utf-8")
    backups = list((home / ".studio-os" / "backups" / "setup").rglob("*.bak"))
    assert [b.read_text(encoding="utf-8") for b in backups] == ["# my own hook\n"]


def test_managed_copy_edited_by_hand_still_needs_confirmation(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "codex")
    _patch_fetch(monkeypatch, [])
    bridge = _bridge(home)
    bridge.apply(_request(bridge.plan()))
    target = home / SPECS["codex"].hook_rel
    target.write_text(target.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    plan = bridge.plan()
    item = next(i for i in plan.hooks if i.item_id == "hook:codex")
    assert item.state is SetupItemState.DIFFERS and item.managed is True
    result = bridge.apply(_request(plan))
    assert _outcomes(result)["hook:codex"] is SetupItemOutcome.SKIPPED
    assert target.read_text(encoding="utf-8").endswith("# edited\n")


def test_file_changed_between_preview_and_apply_is_skipped(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "codex")
    target = home / SPECS["codex"].hook_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# v1\n", encoding="utf-8")
    _patch_fetch(monkeypatch, [])
    bridge = _bridge(home)
    plan = bridge.plan()
    target.unlink()  # the previewed file vanished: the confirmation no longer fits
    result = bridge.apply(_request(plan, overwrite_items=["hook:codex"]))
    assert _outcomes(result)["hook:codex"] is SetupItemOutcome.SKIPPED
    assert not target.exists()


def test_secret_or_path_in_foreign_file_never_reaches_the_diff(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "codex")
    target = home / SPECS["codex"].hook_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "token = sk-ABCDEF0123456789ABCDEF0123456789\nC:/Users/dev/secret/hook.ps1\n",
        encoding="utf-8",
    )
    _patch_fetch(monkeypatch, [])
    plan = _bridge(home).plan()  # the contract refuses the plan if anything leaked
    raw = plan.model_dump_json()
    assert "sk-ABCDEF" not in raw and "C:/Users/dev" not in raw


def test_locally_modified_skill_is_reported_and_left_alone(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "claude-code")
    _patch_fetch(monkeypatch, [_projection()])
    bridge = _bridge(home)
    bridge.apply(_request(bridge.plan()))
    skill = home / ".claude" / "skills" / "studio-git-flow" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nlocal\n", encoding="utf-8")
    edited = skill.read_bytes()
    plan = bridge.plan()
    assert plan.skills.locally_modified == 1
    result = bridge.apply(_request(plan))
    assert result.skills.outcome is SetupSkillsOutcome.UNCHANGED
    assert result.skills.left_modified == 1
    assert skill.read_bytes() == edited


def test_skills_can_be_skipped(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "claude-code")
    _patch_fetch(monkeypatch, [_projection()])
    bridge = _bridge(home)
    result = bridge.apply(_request(bridge.plan(), sync_skills=False))
    assert result.skills.outcome is SetupSkillsOutcome.SKIPPED
    assert not (home / ".claude" / "skills").exists()


@pytest.mark.parametrize(
    ("token", "error", "reason"),
    [
        (None, None, SetupUnavailableReason.NOT_SIGNED_IN),
        ("tok", "auth", SetupUnavailableReason.CREDENTIAL_REJECTED),
        ("tok", "api", SetupUnavailableReason.LIBRARY_UNREACHABLE),
    ],
)
def test_skills_unavailable_states_why_and_hooks_still_work(
    tmp_path: Path, monkeypatch, token, error, reason
) -> None:
    from studio_client.errors import AuthenticationError, StudioApiError

    home = _home(tmp_path, "claude-code")
    exc = {
        "auth": AuthenticationError(401, "unauthorized", "no"),
        "api": StudioApiError(503, "down", "down"),
    }.get(error)
    _patch_fetch(monkeypatch, exc if exc is not None else [])
    bridge = _bridge(home, token=token)
    plan = bridge.plan()
    assert plan.skills.state is SetupSkillsState.UNAVAILABLE and plan.skills.reason is reason
    result = bridge.apply(_request(plan))
    assert result.skills.outcome is SetupSkillsOutcome.UNAVAILABLE
    assert (home / SPECS["claude-code"].hook_rel).is_file()


def test_apply_requires_the_previewed_plan(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "claude-code")
    _patch_fetch(monkeypatch, [])
    bridge = _bridge(home)
    plan = bridge.plan()
    with pytest.raises(LocalFeatureError) as unknown:
        bridge.apply(
            SetupApplyRequest(plan_id="setup-nope", plan_hash=plan.plan_hash, confirmed=True)
        )
    assert unknown.value.error.code.value == "plan_expired"
    with pytest.raises(LocalFeatureError) as wrong_hash:
        bridge.apply(SetupApplyRequest(plan_id=plan.plan_id, plan_hash="0" * 64, confirmed=True))
    assert wrong_hash.value.error.code.value == "invalid_request"
    with pytest.raises(LocalFeatureError):
        bridge.apply(_request(plan, overwrite_items=["hook:claude-code"]))  # missing, not differing
    assert not (home / SPECS["claude-code"].hook_rel).exists()


def test_plan_expires(tmp_path: Path, monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    home = _home(tmp_path, "claude-code")
    _patch_fetch(monkeypatch, [])
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    bridge = _bridge(home)
    bridge._clock = lambda: now[0]
    plan = bridge.plan()
    now[0] += timedelta(minutes=11)
    with pytest.raises(LocalFeatureError) as err:
        bridge.apply(_request(plan))
    assert err.value.error.code.value == "plan_expired"


def test_adapters_drift_is_counted_not_fixed(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path)
    workspace = tmp_path / "ws"
    (workspace / ".agents").mkdir(parents=True)
    _patch_fetch(monkeypatch, [])

    class Report:
        checked = 4
        failures = (
            {"adapter": "a", "key": "k", "error": "drifted"},
            {"adapter": "a", "key": "k", "error": "drifted again"},
        )

    monkeypatch.setattr("studio_client.daemon.setup_bridge.check_adapters", lambda root: Report)
    plan = _bridge(home, roots=(workspace,)).plan()
    assert plan.adapters.state is SetupAdaptersState.CHECKED
    assert (plan.adapters.workspaces, plan.adapters.checked, plan.adapters.drifted) == (1, 4, 1)


def test_adapters_failure_is_reported_unavailable(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path)
    workspace = tmp_path / "ws"
    (workspace / ".agents").mkdir(parents=True)
    _patch_fetch(monkeypatch, [])

    def boom(root):
        raise OSError("disk")

    monkeypatch.setattr("studio_client.daemon.setup_bridge.check_adapters", boom)
    plan = _bridge(home, roots=(workspace,)).plan()
    assert plan.adapters.state is SetupAdaptersState.UNAVAILABLE and plan.adapters.checked == 0


def test_engine_diff_is_bounded(tmp_path: Path) -> None:
    home = _home(tmp_path, "codex")
    target = home / SPECS["codex"].hook_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(f"line {i}" for i in range(500)), encoding="utf-8")
    plan = machine_setup.plan_hooks(home, [SPECS["codex"]])
    item = plan.items[0]
    assert item.diff_truncated and len(item.diff) <= machine_setup.DIFF_MAX_CHARS
    assert len(item.diff.splitlines()) <= machine_setup.DIFF_MAX_LINES


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


def _service(tmp_path: Path, home: Path) -> BridgeService:
    store = MemoryTokenStore()
    store.set_token(ORIGIN, "tok")
    config = ClientConfig(api_base_url=f"{ORIGIN}/api/v1", profile_id="main", machine_id=uuid4())
    controller = DaemonController(
        config, data_root=tmp_path / "data", token_store=store, skills_home=lambda: home
    )
    return BridgeService(controller)


def test_served_over_bridge_without_path_or_content(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "claude-code")
    _patch_fetch(monkeypatch, [_projection()])
    service = _service(tmp_path, home)
    _negotiate(service, ["daemon.control", "setup.plan", "setup.apply"])
    planned = service.handle_line(_line("setup.plan", {}))
    assert planned["kind"] == "response", planned
    plan = SetupPlan.model_validate(planned["payload"])
    raw = json.dumps(planned, default=str)
    assert "SECRET-BODY-MARKER" not in raw and str(tmp_path) not in raw
    applied = service.handle_line(
        _line(
            "setup.apply",
            {"plan_id": plan.plan_id, "plan_hash": plan.plan_hash, "confirmed": True},
        )
    )
    assert applied["kind"] == "response", applied
    result = SetupApplyResult.model_validate(applied["payload"])
    assert _outcomes(result)["hook:claude-code"] is SetupItemOutcome.WRITTEN
    assert str(tmp_path) not in json.dumps(applied, default=str)


def test_unconfirmed_apply_is_rejected_over_bridge(tmp_path: Path, monkeypatch) -> None:
    home = _home(tmp_path, "claude-code")
    _patch_fetch(monkeypatch, [])
    service = _service(tmp_path, home)
    _negotiate(service, ["daemon.control", "setup.plan", "setup.apply"])
    plan = SetupPlan.model_validate(service.handle_line(_line("setup.plan", {}))["payload"])
    # The bridge envelope itself refuses an unconfirmed apply: it never reaches the daemon.
    with pytest.raises(ValidationError):
        _line(
            "setup.apply",
            {"plan_id": plan.plan_id, "plan_hash": plan.plan_hash, "confirmed": False},
        )
    assert not (home / SPECS["claude-code"].hook_rel).exists()


def test_denied_without_capability(tmp_path: Path) -> None:
    service = _service(tmp_path, _home(tmp_path))
    _negotiate(service, ["daemon.control"])
    assert service.handle_line(_line("setup.plan", {}))["kind"] != "response"


def test_handshake_offers_setup_capabilities(tmp_path: Path) -> None:
    service = _service(tmp_path, _home(tmp_path))
    answer = _negotiate(service, ["daemon.control", "setup.plan", "setup.apply"])
    raw = json.dumps(answer)
    assert "setup.plan" in raw and "setup.apply" in raw
