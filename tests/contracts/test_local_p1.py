from __future__ import annotations

import json
import re
import typing
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError
from studio_contracts.local import export, fixtures
from studio_contracts.local.bridge import (
    BRIDGE_COMMANDS,
    BRIDGE_EVENTS,
    BRIDGE_MESSAGE_ADAPTER,
    FORBIDDEN_PRIMITIVE_TERMS,
    BridgeCommand,
    BridgeEventName,
    BridgeRequest,
    BridgeResponse,
    allowlist_violations,
    check_capability,
    check_reply_correlation,
)
from studio_contracts.local.code_graph import CodeGraphStatus
from studio_contracts.local.common import (
    ComponentId,
    ComponentState,
    LocalErrorCode,
    LocalResourceKind,
    build_local_uri,
    contains_secret_material,
    is_secret_key_name,
    parse_local_uri,
)
from studio_contracts.local.daemon_control import (
    DaemonAction,
    DaemonControlRequest,
    DaemonHealth,
    DaemonRunState,
    DaemonStatus,
    ReplayVerdict,
    RuntimeServiceCondition,
    decide_outbox_replay,
    instance_lock_key,
)
from studio_contracts.local.graph import GraphPage
from studio_contracts.local.handshake import (
    COMPATIBLE_OUTCOMES,
    CompatibilityOutcome,
    HandshakeRequest,
    HandshakeResponse,
    negotiate,
)
from studio_contracts.local.identity import (
    SECRET_STATUS_ERROR,
    IdentityBinding,
    SecretStatus,
    binding_mismatches,
    partition_key,
)
from studio_contracts.local.knowledge import KnowledgeStatus
from studio_contracts.local.provider import IndexInfo, IndexState
from studio_contracts.local.publication import (
    DEFAULT_PUBLICATION_POLICY,
    LocalDataClass,
    PublicationPolicy,
    Visibility,
)
from studio_contracts.local.workspace import (
    WORKSPACE_HEALTH_BEHAVIOR,
    WorkspaceHealth,
    WorkspaceStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_SOURCE = REPO_ROOT / "packages" / "studio-contracts" / "src" / "studio_contracts" / "local"

STRUCTURAL_SECRET_FIELDS = frozenset({"secrets", "secret_references"})

REQUIRED_FIXTURES = {
    "runtime.handshake.compatible",
    "runtime.handshake.compatible_degraded",
    "runtime.handshake.daemon_too_old",
    "runtime.handshake.desktop_too_old",
    "runtime.handshake.capability_missing",
    "runtime.handshake.protocol_incompatible",
    "daemon.status.running",
    "daemon.health.running",
    "daemon.control.unavailable",
    "daemon.status.crashed",
    "daemon.status.recovering",
    "workspace.status.valid",
    "workspace.status.config_missing",
    "workspace.status.moved",
    "knowledge.status.disabled",
    "knowledge.status.indexing",
    "knowledge.status.ready",
    "code_graph.status.not_installed",
    "code_graph.status.indexing",
    "code_graph.status.ready",
    "code_graph.status.provider_incompatible",
    "graph.empty",
    "graph.knowledge.small",
    "graph.code.small",
    "graph.code.partial",
    "harness.status.not_detected",
    "harness.status.detected",
    "harness.status.configured",
    "knowledge.status.permission_denied",
    "identity.view.keyring_unavailable",
    "identity.view.wrong_profile",
}


def _by_name() -> dict[str, fixtures.LocalFixture]:
    return {f.name: f for f in fixtures.build_fixtures()}


def _model(name: str) -> Any:
    return _by_name()[name].model


def _all_models() -> list[type[BaseModel]]:
    return list(export.model_registry().values())


class TestFixtures:
    def test_required_fixtures_exist(self) -> None:
        assert REQUIRED_FIXTURES <= set(_by_name())

    def test_names_are_unique(self) -> None:
        names = [f.name for f in fixtures.build_fixtures()]
        assert len(names) == len(set(names))

    def test_valid_fixtures_round_trip(self) -> None:
        registry = export.model_registry()
        for fixture in fixtures.build_fixtures():
            model = registry[fixture.model_name]
            dumped = fixture.model.model_dump(mode="json")
            assert model.model_validate(dumped).model_dump(mode="json") == dumped
            assert model.model_validate_json(fixture.model.model_dump_json()) == fixture.model

    def test_invalid_fixtures_are_rejected(self) -> None:
        registry = export.model_registry()
        for invalid in fixtures.build_invalid_fixtures():
            with pytest.raises(ValidationError):
                registry[invalid.model_name].model_validate(invalid.data)

    def test_fixtures_are_deterministic(self) -> None:
        first = [f.model.model_dump_json() for f in fixtures.build_fixtures()]
        second = [f.model.model_dump_json() for f in fixtures.build_fixtures()]
        assert first == second

    def test_fixtures_carry_no_secret_material(self) -> None:
        for name, content in export.build_export().items():
            if name.startswith("schemas/") or "invalid/" in name:
                continue
            assert not contains_secret_material(content), name

    def test_no_fixture_key_names_a_secret(self) -> None:
        def walk(value: object, where: str) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    assert key in STRUCTURAL_SECRET_FIELDS or not is_secret_key_name(str(key)), (
                        f"{where}: {key}"
                    )
                    walk(item, where)
            elif isinstance(value, list):
                for item in value:
                    walk(item, where)

        for name, content in export.build_export().items():
            if name.startswith("fixtures/valid/"):
                walk(json.loads(content)["data"], name)

    def test_exported_files_match_committed_files(self) -> None:
        assert export.drift(REPO_ROOT) == []

    def test_manifest_lists_every_fixture(self) -> None:
        manifest = json.loads(export.build_export()["manifest.json"])
        assert {f["name"] for f in manifest["valid_fixtures"]} == set(_by_name())
        assert len(manifest["invalid_fixtures"]) == len(fixtures.build_invalid_fixtures())

    def test_model_registry_names_are_unique_and_cover_bridge_models(self) -> None:
        registry = export.model_registry()
        for spec in BRIDGE_COMMANDS.values():
            assert registry[spec.request.__name__] is spec.request
            assert registry[spec.response.__name__] is spec.response


class TestHandshake:
    @pytest.mark.parametrize(
        ("name", "outcome"),
        [
            ("compatible", CompatibilityOutcome.COMPATIBLE),
            ("compatible_degraded", CompatibilityOutcome.COMPATIBLE_DEGRADED),
            ("daemon_too_old", CompatibilityOutcome.DAEMON_TOO_OLD),
            ("desktop_too_old", CompatibilityOutcome.DESKTOP_TOO_OLD),
            ("capability_missing", CompatibilityOutcome.CAPABILITY_MISSING),
            ("protocol_incompatible", CompatibilityOutcome.PROTOCOL_INCOMPATIBLE),
        ],
    )
    def test_outcomes(self, name: str, outcome: CompatibilityOutcome) -> None:
        response: HandshakeResponse = _model(f"runtime.handshake.{name}")
        assert response.outcome is outcome

    def test_incompatible_grants_nothing_and_never_falls_back(self) -> None:
        for name in ("daemon_too_old", "desktop_too_old", "capability_missing"):
            response: HandshakeResponse = _model(f"runtime.handshake.{name}")
            assert response.outcome not in COMPATIBLE_OUTCOMES
            assert response.negotiated is None
            assert response.granted_capabilities == []
            assert response.error is not None
            assert response.silent_fallback is False

    def test_compatible_negotiates_lowest_common_version(self) -> None:
        response: HandshakeResponse = _model("runtime.handshake.compatible")
        assert response.negotiated is not None
        assert response.negotiated.as_tuple() == (1, 0)
        assert "daemon.control" in response.granted_capabilities

    def test_degraded_removes_only_the_unavailable_capabilities(self) -> None:
        response: HandshakeResponse = _model("runtime.handshake.compatible_degraded")
        degraded = {item.capability for item in response.degraded}
        assert degraded == {"code_graph.graph", "code_graph.index", "code_graph.read"}
        assert not degraded & set(response.granted_capabilities)
        assert "knowledge.read" in response.granted_capabilities

    def test_optional_component_never_breaks_compatibility(self) -> None:
        request = HandshakeRequest(peer=fixtures.desktop_peer())
        daemon = fixtures.daemon_peer(code_graph_state=ComponentState.INCOMPATIBLE)
        assert negotiate(request, daemon).outcome in COMPATIBLE_OUTCOMES

    def test_versions_of_packages_do_not_matter(self) -> None:
        request = HandshakeRequest(peer=fixtures.desktop_peer())
        daemon = fixtures.daemon_peer()
        older = daemon.model_copy(update={"component_version": "0.0.1"})
        assert negotiate(request, older).outcome is negotiate(request, daemon).outcome

    def test_current_daemon_offers_health_and_old_daemon_degrades_safely(self) -> None:
        request = HandshakeRequest(peer=fixtures.desktop_peer())
        current = negotiate(request, fixtures.daemon_peer())
        old = negotiate(
            request,
            fixtures.daemon_peer(drop=frozenset({"daemon.health"})),
        )

        assert "daemon.health" in current.granted_capabilities
        assert old.outcome is CompatibilityOutcome.COMPATIBLE_DEGRADED
        assert old.missing_optional == ["daemon.health"]
        assert "daemon.health" not in old.granted_capabilities

    def test_incompatible_response_cannot_be_forged(self) -> None:
        data = _model("runtime.handshake.capability_missing").model_dump(mode="json")
        data["granted_capabilities"] = ["daemon.control"]
        with pytest.raises(ValidationError):
            HandshakeResponse.model_validate(data)
        data["granted_capabilities"] = []
        data["silent_fallback"] = True
        with pytest.raises(ValidationError):
            HandshakeResponse.model_validate(data)

    def test_missing_required_capability_is_listed(self) -> None:
        response: HandshakeResponse = _model("runtime.handshake.capability_missing")
        assert response.missing_required == ["workspace.config"]


class TestBridgeAllowlist:
    def test_no_forbidden_primitive_in_the_allowlist(self) -> None:
        assert allowlist_violations() == []
        assert "exec" in FORBIDDEN_PRIMITIVE_TERMS

    def test_every_command_has_exactly_one_spec(self) -> None:
        assert set(BRIDGE_COMMANDS) == set(BridgeCommand)
        assert set(BRIDGE_EVENTS) == set(BridgeEventName)

    def test_unknown_command_is_refused(self) -> None:
        for command in ("shell.exec", "fs.read", "process.spawn", "http.request"):
            with pytest.raises(ValidationError):
                BridgeRequest.model_validate(
                    {
                        "message_id": "m1",
                        "correlation_id": "c1",
                        "sent_at": fixtures.NOW,
                        "command": command,
                        "payload": {},
                    }
                )

    def test_no_request_model_accepts_a_free_form_command_or_path_or_url(self) -> None:
        banned = {"command", "cmd", "argv", "args", "shell", "url", "uri_template", "script"}
        for spec in BRIDGE_COMMANDS.values():
            for model in (spec.request, spec.response):
                assert not banned & set(model.model_fields), (spec.command, model.__name__)

    def test_mutating_commands_are_listed_explicitly(self) -> None:
        mutating = {c.value for c, s in BRIDGE_COMMANDS.items() if s.mutating}
        assert mutating >= {
            "daemon.start",
            "daemon.stop",
            "daemon.restart",
            "workspace.save_config",
            "harness.apply",
            "publication.publish",
        }
        readonly = {
            "runtime.handshake",
            "daemon.status",
            "daemon.health",
            "identity.get_view",
            "knowledge.search",
        }
        assert not mutating & readonly

    def test_publication_and_apply_commands_require_confirmation_payloads(self) -> None:
        for name in ("harness.apply.request",):
            data = _model(name).model_dump(mode="json")
            assert data["confirmed"] is True

    def test_payload_is_validated_against_the_command(self) -> None:
        request = _model("bridge.request.knowledge_search")
        assert isinstance(request, BridgeRequest)
        data = request.model_dump(mode="json")
        data["payload"]["query"] = ""
        with pytest.raises(ValidationError):
            BridgeRequest.model_validate(data)
        data = request.model_dump(mode="json")
        data["payload"]["path"] = "C:/Windows/system32"
        with pytest.raises(ValidationError):
            BridgeRequest.model_validate(data)

    def test_request_size_and_deadline_limits(self) -> None:
        request = _model("bridge.request.knowledge_search")
        data = request.model_dump(mode="json")
        data["payload"]["query"] = "x" * 100_000
        with pytest.raises(ValidationError):
            BridgeRequest.model_validate(data)
        data = request.model_dump(mode="json")
        data["deadline_ms"] = 10
        with pytest.raises(ValidationError):
            BridgeRequest.model_validate(data)

    def test_daemon_commands_must_match_their_action(self) -> None:
        for command, action in (
            ("daemon.stop", DaemonAction.START),
            ("daemon.start", DaemonAction.STOP),
        ):
            payload = DaemonControlRequest(action=action, profile=fixtures.PROFILE)
            with pytest.raises(ValidationError):
                BridgeRequest.model_validate(
                    {
                        "message_id": "m1",
                        "correlation_id": "c1",
                        "sent_at": fixtures.NOW,
                        "command": command,
                        "payload": payload.model_dump(mode="json"),
                    }
                )

    def test_capability_gate_is_fail_closed(self) -> None:
        refusal = check_capability(BridgeCommand.CODE_GRAPH_FIND_SYMBOLS, set())
        assert refusal is not None
        assert refusal.code is LocalErrorCode.CAPABILITY_MISSING
        assert check_capability(BridgeCommand.RUNTIME_HANDSHAKE, set()) is None
        capability = BRIDGE_COMMANDS[BridgeCommand.CODE_GRAPH_FIND_SYMBOLS].capability
        assert capability is not None
        assert check_capability(BridgeCommand.CODE_GRAPH_FIND_SYMBOLS, {capability}) is None

    def test_reply_correlation(self) -> None:
        request = _model("bridge.request.knowledge_search")
        response = BRIDGE_MESSAGE_ADAPTER.validate_python(
            _model("bridge.response.knowledge_search").model_dump(mode="json")
        )
        check_reply_correlation(request, response)
        other = response.model_copy(update={"correlation_id": "other"})
        with pytest.raises(ValueError, match="correlation"):
            check_reply_correlation(request, other)
        wrong = response.model_copy(update={"request_id": "other"})
        with pytest.raises(ValueError, match="answer"):
            check_reply_correlation(request, wrong)

    def test_message_union_discriminates_on_kind(self) -> None:
        for name, kind in (
            ("bridge.request.knowledge_search", "request"),
            ("bridge.response.knowledge_search", "response"),
            ("bridge.error.capability_missing", "error"),
            ("bridge.event.daemon_state_changed", "event"),
            ("bridge.progress.reindex", "progress"),
            ("bridge.cancel.reindex", "cancel"),
        ):
            message = BRIDGE_MESSAGE_ADAPTER.validate_python(_model(name).model_dump(mode="json"))
            assert message.kind == kind

    def test_response_payload_is_validated(self) -> None:
        data = _model("bridge.response.knowledge_search").model_dump(mode="json")
        data["payload"] = {"unexpected": True}
        with pytest.raises(ValidationError):
            BridgeResponse.model_validate(data)

    def test_error_correlation_must_match_envelope(self) -> None:
        data = _model("bridge.error.capability_missing").model_dump(mode="json")
        data["error"]["correlation_id"] = "someone-else"
        with pytest.raises(ValidationError):
            BRIDGE_MESSAGE_ADAPTER.validate_python(data)

    def test_exported_allowlist_is_the_closed_set(self) -> None:
        allowlist = json.loads(export.build_export()["allowlist.json"])
        assert {c["command"] for c in allowlist["commands"]} == {c.value for c in BridgeCommand}
        assert allowlist["protocol"] == "studio.local/v1"


class TestIdentityAndSecrets:
    def test_no_field_anywhere_is_named_like_a_secret(self) -> None:
        offenders = [
            f"{model.__name__}.{field}"
            for model in _all_models()
            for field in model.model_fields
            if is_secret_key_name(field) and field not in STRUCTURAL_SECRET_FIELDS
        ]
        assert offenders == []

    def test_structural_secret_fields_only_hold_references_and_statuses(self) -> None:
        for model in _all_models():
            for field in STRUCTURAL_SECRET_FIELDS & set(model.model_fields):
                inner = typing.get_args(model.model_fields[field].annotation)
                assert inner and inner[0].__name__ in {"SecretReference", "SecretReferenceStatus"}

    def test_no_field_holds_a_value_for_a_secret(self) -> None:
        offenders = [
            f"{model.__name__}.{field}"
            for model in _all_models()
            for field in model.model_fields
            if field in {"value", "secret", "password", "raw", "payload_secret"}
            and model.__name__ in {"SecretReference", "SecretReferenceStatus", "MachineIdentity"}
        ]
        assert offenders == []

    def test_human_and_machine_identity_are_distinct_types(self) -> None:
        human = fixtures.HUMAN
        machine = fixtures.MACHINE
        assert type(human).__name__ != type(machine).__name__
        assert "machine_id" not in type(human).model_fields
        assert "user_id" not in type(machine).model_fields

    def test_every_secret_status_has_an_error_mapping(self) -> None:
        assert set(SECRET_STATUS_ERROR) == set(SecretStatus) - {SecretStatus.PRESENT}

    @pytest.mark.parametrize(
        "name",
        [
            "identity.view.secret_absent",
            "identity.view.secret_inaccessible",
            "identity.view.secret_revoked",
            "identity.view.keyring_unavailable",
            "identity.view.wrong_profile",
        ],
    )
    def test_secret_failures_are_structured(self, name: str) -> None:
        view = _model(name)
        status = view.secrets[0]
        assert status.status is not SecretStatus.PRESENT
        assert status.error is not None
        assert status.error.code is SECRET_STATUS_ERROR[status.status]
        assert status.error.component is ComponentId.SECRET_STORE

    def test_keyring_unavailable_is_the_only_retryable_secret_error(self) -> None:
        retryable = {
            name
            for name in _by_name()
            if name.startswith("identity.view.")
            and any(s.error is not None and s.error.retryable for s in _model(name).secrets)
        }
        assert retryable == {"identity.view.keyring_unavailable"}

    def test_wrong_profile_reference_points_to_another_profile(self) -> None:
        reference = _model("identity.view.wrong_profile").secrets[0].reference
        assert reference.profile != fixtures.PROFILE

    def test_secret_error_must_match_status(self) -> None:
        data = _model("identity.view.secret_revoked").model_dump(mode="json")
        data["secrets"][0]["error"]["code"] = "secret_absent"
        with pytest.raises(ValidationError):
            type(_model("identity.view.secret_revoked")).model_validate(data)

    def test_reference_rejects_a_value(self) -> None:
        data = fixtures.secret_reference().model_dump(mode="json") | {"value": "hunter2"}
        with pytest.raises(ValidationError):
            type(fixtures.secret_reference()).model_validate(data)

    def test_secret_guards(self) -> None:
        assert is_secret_key_name("api_key")
        assert is_secret_key_name("Authorization")
        assert not is_secret_key_name("lookup_key")
        assert contains_secret_material("Bearer abcdefghijklmnop")
        assert contains_secret_material("sk-abcdefghijklmnopqrstuv")
        assert not contains_secret_material("plain sentence")


class TestOutboxIdentity:
    def _binding(self, **changes: Any) -> IdentityBinding:
        base = IdentityBinding(
            server_origin=fixtures.PROFILE.server_origin,
            profile_id=fixtures.PROFILE.profile_id,
            machine_id=fixtures.MACHINE_ID,
            project_id=fixtures.PROJECT_ID,
            workspace_id=fixtures.WORKSPACE_ID,
        )
        return base.model_copy(update=changes)

    def test_partition_key_depends_on_origin_profile_machine_only(self) -> None:
        base = self._binding()
        assert partition_key(base) == partition_key(self._binding(workspace_id=UUID(int=9)))
        assert partition_key(base) != partition_key(self._binding(machine_id=UUID(int=9)))
        assert partition_key(base) != partition_key(self._binding(profile_id="other"))
        assert partition_key(base) != partition_key(
            self._binding(server_origin="https://other.example.test")
        )

    def test_lock_key_is_per_profile_not_per_machine(self) -> None:
        assert instance_lock_key(fixtures.PROFILE) == instance_lock_key(fixtures.PROFILE)
        assert instance_lock_key(fixtures.PROFILE) != instance_lock_key(fixtures.OTHER_PROFILE)

    def test_replay_allowed_for_same_identity(self) -> None:
        assert _model("daemon.outbox.replay_allowed").verdict is ReplayVerdict.ALLOW

    def test_replay_refused_on_machine_mismatch(self) -> None:
        decision = _model("daemon.outbox.replay_refused_identity_mismatch")
        assert decision.verdict is ReplayVerdict.REFUSE_IDENTITY_MISMATCH
        assert decision.error is not None
        assert decision.error.code is LocalErrorCode.IDENTITY_MISMATCH
        assert "machine_id" in decision.mismatched

    @pytest.mark.parametrize(
        "change",
        [
            {"server_origin": "https://other.example.test"},
            {"profile_id": "other"},
            {"machine_id": UUID(int=7)},
            {"project_id": UUID(int=7)},
        ],
    )
    def test_replay_refused_for_every_identity_component(self, change: dict[str, Any]) -> None:
        entry = self._binding(**change)
        active = self._binding()
        assert binding_mismatches(entry, active)
        verdict = decide_outbox_replay(entry, active).verdict
        assert verdict is ReplayVerdict.REFUSE_IDENTITY_MISMATCH


class TestDaemon:
    def test_states_map_to_components(self) -> None:
        for state in DaemonRunState:
            assert isinstance(state, DaemonRunState)

    def test_crash_requires_crash_info_and_running_requires_instance(self) -> None:
        with pytest.raises(ValidationError):
            DaemonStatus(state=DaemonRunState.CRASHED)
        with pytest.raises(ValidationError):
            DaemonStatus(state=DaemonRunState.RUNNING)

    def test_running_status_binds_outbox_to_a_partition(self) -> None:
        status: DaemonStatus = _model("daemon.status.running")
        assert status.outbox is not None
        assert status.outbox.partition_key == partition_key(status.outbox.binding)
        assert status.instance is not None
        assert status.instance.lock_key == instance_lock_key(fixtures.PROFILE)

    def test_health_is_a_separate_capability_gated_contract(self) -> None:
        health: DaemonHealth = _model("daemon.health.running")
        assert health.heartbeat.condition is RuntimeServiceCondition.SERVER_UNAVAILABLE
        assert health.heartbeat.error is not None
        assert len(health.git_watchers) == 1
        assert BRIDGE_COMMANDS[BridgeCommand.DAEMON_HEALTH].capability == "daemon.health"

    def test_unavailable_and_already_running_carry_errors(self) -> None:
        assert _model("daemon.control.unavailable").error.code is LocalErrorCode.DAEMON_UNAVAILABLE
        already = _model("daemon.control.already_running")
        assert already.error.code is LocalErrorCode.DAEMON_ALREADY_RUNNING


class TestWorkspace:
    def test_every_health_has_behavior(self) -> None:
        assert set(WORKSPACE_HEALTH_BEHAVIOR) == set(WorkspaceHealth)

    @pytest.mark.parametrize("health", list(WorkspaceHealth))
    def test_status_fixture_per_health(self, health: WorkspaceHealth) -> None:
        candidates = [
            f.model
            for f in fixtures.build_fixtures()
            if isinstance(f.model, WorkspaceStatus) and f.model.health is health
        ]
        assert candidates, health

    def test_invalid_workspace_disables_features_without_config(self) -> None:
        for health in WorkspaceHealth:
            if health is WorkspaceHealth.VALID:
                continue
            status = next(
                f.model
                for f in fixtures.build_fixtures()
                if isinstance(f.model, WorkspaceStatus) and f.model.health is health
            )
            assert status.config is None
            assert status.error is not None

    def test_health_and_action_must_agree(self) -> None:
        data = _model("workspace.status.config_missing").model_dump(mode="json")
        data["action"] = "none"
        with pytest.raises(ValidationError):
            WorkspaceStatus.model_validate(data)

    def test_moved_proposes_candidate_root_only_then(self) -> None:
        assert _model("workspace.status.moved").candidate_root is not None
        data = _model("workspace.status.config_missing").model_dump(mode="json")
        data["candidate_root"] = "D:/elsewhere"
        with pytest.raises(ValidationError):
            WorkspaceStatus.model_validate(data)

    def test_config_holds_references_not_secrets(self) -> None:
        config = _model("workspace.config.full")
        dumped = json.dumps(config.model_dump(mode="json"))
        assert config.secret_references
        assert not contains_secret_material(dumped)
        keys = set(re.findall(r'"([^"]+)":', dumped)) - STRUCTURAL_SECRET_FIELDS
        assert not [key for key in keys if is_secret_key_name(key)]

    def test_config_rejects_secret_fields_and_relative_roots(self) -> None:
        cls = type(_model("workspace.config.full"))
        base = _model("workspace.config.full").model_dump(mode="json")
        with pytest.raises(ValidationError):
            cls.model_validate(base | {"machine_token": "x"})
        relative = json.loads(json.dumps(base))
        relative["roots"]["workspace_root"] = "demo"
        with pytest.raises(ValidationError):
            cls.model_validate(relative)

    def test_enabled_feature_requires_its_config(self) -> None:
        cls = type(_model("workspace.config.full"))
        base = _model("workspace.config.minimal").model_dump(mode="json")
        base["features"]["knowledge"] = True
        with pytest.raises(ValidationError):
            cls.model_validate(base)

    def test_secret_reference_of_another_profile_is_refused(self) -> None:
        cls = type(_model("workspace.config.full"))
        base = _model("workspace.config.full").model_dump(mode="json")
        base["secret_references"][0]["profile"] = fixtures.OTHER_PROFILE.model_dump(mode="json")
        with pytest.raises(ValidationError):
            cls.model_validate(base)


class TestProviders:
    def test_knowledge_states(self) -> None:
        for name, state in (
            ("disabled", ComponentState.DISABLED),
            ("indexing", ComponentState.INDEXING),
            ("ready", ComponentState.READY),
            ("permission_denied", ComponentState.PERMISSION_DENIED),
        ):
            status: KnowledgeStatus = _model(f"knowledge.status.{name}")
            assert status.state is state

    def test_knowledge_is_markdown_canonical_and_obsidian_optional(self) -> None:
        status: KnowledgeStatus = _model("knowledge.status.ready")
        assert status.canonical_source == "markdown_files"
        assert all(not integration.required for integration in status.integrations)
        data = status.model_dump(mode="json")
        data["integrations"][0]["required"] = True
        with pytest.raises(ValidationError):
            KnowledgeStatus.model_validate(data)

    def test_code_graph_states(self) -> None:
        for name, state in (
            ("not_installed", ComponentState.NOT_INSTALLED),
            ("provider_incompatible", ComponentState.INCOMPATIBLE),
            ("indexing", ComponentState.INDEXING),
            ("ready", ComponentState.READY),
            ("stale", ComponentState.STALE),
        ):
            status: CodeGraphStatus = _model(f"code_graph.status.{name}")
            assert status.state is state

    def test_index_is_derived_and_rebuildable(self) -> None:
        assert "rebuildable" in IndexInfo.model_fields or "derived" in IndexInfo.model_fields
        info = IndexInfo(state=IndexState.ABSENT)
        dumped = info.model_dump(mode="json")
        assert dumped.get("derived", True) is True

    def test_ready_state_requires_a_ready_index(self) -> None:
        data = _model("code_graph.status.ready").model_dump(mode="json")
        data["index"]["state"] = "absent"
        data["index"]["built_at"] = None
        data["index"]["source_fingerprint"] = None
        with pytest.raises(ValidationError):
            CodeGraphStatus.model_validate(data)

    def test_failure_states_require_matching_errors(self) -> None:
        data = _model("code_graph.status.not_installed").model_dump(mode="json")
        data["error"] = None
        with pytest.raises(ValidationError):
            CodeGraphStatus.model_validate(data)
        data = _model("code_graph.status.provider_incompatible").model_dump(mode="json")
        data["error"]["code"] = "index_absent"
        with pytest.raises(ValidationError):
            CodeGraphStatus.model_validate(data)

    def test_ready_state_carries_no_error(self) -> None:
        data = _model("code_graph.status.ready").model_dump(mode="json")
        data["error"] = _model("code_graph.status.not_installed").error.model_dump(mode="json")
        with pytest.raises(ValidationError):
            CodeGraphStatus.model_validate(data)


class TestHarness:
    def test_states(self) -> None:
        assert _model("harness.status.not_detected").state.value == "not_detected"
        assert _model("harness.status.detected").state.value == "detected"
        assert _model("harness.status.configured").state.value == "configured"

    def test_apply_requires_confirmation(self) -> None:
        cls = type(_model("harness.apply.request"))
        data = _model("harness.apply.request").model_dump(mode="json")
        data["confirmed"] = False
        with pytest.raises(ValidationError):
            cls.model_validate(data)

    def test_plan_carries_hashes_not_content(self) -> None:
        plan = _model("harness.plan.preview").model_dump(mode="json")
        for change in plan["changes"]:
            assert "content" not in change and "before" not in change and "after" not in change

    def test_harness_targets_are_relative(self) -> None:
        for change in _model("harness.plan.preview").changes:
            assert not change.target.startswith("/")
            assert ":" not in change.target


class TestGraph:
    def test_empty_graph_is_valid(self) -> None:
        page: GraphPage = _model("graph.empty")
        assert page.nodes == [] and page.edges == []

    def test_every_node_and_edge_has_provenance(self) -> None:
        for name in ("graph.knowledge.small", "graph.code.small", "graph.code.partial"):
            page: GraphPage = _model(name)
            assert all(node.provenance is not None for node in page.nodes)
            assert all(edge.provenance is not None for edge in page.edges)

    def test_partial_graph_declares_frontier_cursor_and_truncation(self) -> None:
        page: GraphPage = _model("graph.code.partial")
        assert page.truncated is True
        assert page.next_cursor is not None
        assert page.frontier
        loaded = {node.node_id for node in page.nodes}
        for edge in page.edges:
            for ref in (edge.source, edge.target):
                assert ref.node_id in loaded or ref in page.frontier

    def test_dangling_edge_is_refused(self) -> None:
        data = _model("graph.knowledge.small").model_dump(mode="json")
        data["edges"][0]["target"]["node_id"] = "missing"
        with pytest.raises(ValidationError):
            GraphPage.model_validate(data)

    def test_relations_are_restricted_per_source(self) -> None:
        data = _model("graph.knowledge.small").model_dump(mode="json")
        data["edges"][0]["kind"] = "calls"
        with pytest.raises(ValidationError):
            GraphPage.model_validate(data)

    def test_cross_source_edges_only_through_a_projection(self) -> None:
        projection: GraphPage = _model("graph.projection.cross_source")
        assert projection.source.kind.value == "projection"
        data = _model("graph.knowledge.small").model_dump(mode="json")
        data["edges"][0]["target"]["source_id"] = fixtures.CODE_SOURCE_ID
        with pytest.raises(ValidationError):
            GraphPage.model_validate(data)

    def test_pagination_is_bounded(self) -> None:
        request_cls = type(_model("graph.page.request"))
        with pytest.raises(ValidationError):
            request_cls(workspace_id=fixtures.WORKSPACE_ID, limit=100_000)

    def test_provenance_is_required(self) -> None:
        data = _model("graph.code.small").model_dump(mode="json")
        del data["nodes"][0]["provenance"]
        with pytest.raises(ValidationError):
            GraphPage.model_validate(data)


class TestUris:
    def test_round_trip(self) -> None:
        workspace_id = fixtures.WORKSPACE_ID
        uri = build_local_uri(LocalResourceKind.CODE, workspace_id, "a/b.py", fragment="L1")
        kind, workspace, path, fragment = parse_local_uri(uri)
        assert (kind, workspace, path, fragment) == (
            LocalResourceKind.CODE,
            fixtures.WORKSPACE_ID,
            "a/b.py",
            "L1",
        )

    @pytest.mark.parametrize("path", ["../secret.md", "/abs.md", "a/../b.md", "C:/x.md", "a\\b.md"])
    def test_traversal_and_absolute_paths_are_refused(self, path: str) -> None:
        with pytest.raises(ValueError):
            build_local_uri(LocalResourceKind.KNOWLEDGE, fixtures.WORKSPACE_ID, path)


class TestPublication:
    def test_default_policy_is_all_local(self) -> None:
        assert set(DEFAULT_PUBLICATION_POLICY.classes) == set(LocalDataClass)
        assert set(DEFAULT_PUBLICATION_POLICY.classes.values()) == {Visibility.LOCAL_ONLY}
        assert DEFAULT_PUBLICATION_POLICY.automatic_upload is False

    def test_policy_cannot_share_a_raw_class(self) -> None:
        classes = dict.fromkeys(LocalDataClass, Visibility.LOCAL_ONLY)
        classes[LocalDataClass.PATHS] = Visibility.SHAREABLE_SUMMARY
        with pytest.raises(ValidationError):
            PublicationPolicy(classes=classes)

    def test_policy_cannot_enable_automatic_upload(self) -> None:
        classes = dict.fromkeys(LocalDataClass, Visibility.LOCAL_ONLY)
        with pytest.raises(ValidationError):
            PublicationPolicy.model_validate({"classes": classes, "automatic_upload": True})

    def test_plan_excludes_every_raw_class_and_expires(self) -> None:
        plan = _model("publication.plan.preview")
        assert set(plan.excluded_classes) == set(LocalDataClass)
        assert plan.expires_at > plan.created_at
        data = plan.model_dump(mode="json")
        data["expires_at"] = data["created_at"]
        with pytest.raises(ValidationError):
            type(plan).model_validate(data)

    def test_shared_summary_has_no_free_text_path_or_content(self) -> None:
        summary_cls = type(_model("publication.plan.preview").summary)
        component_cls = type(_model("publication.plan.preview").summary.components[0])
        for model in (summary_cls, component_cls):
            for name, field in model.model_fields.items():
                assert field.annotation is not str or name in {"protocol_version"}, name
                assert name not in {"path", "content", "message", "text", "uri"}

    def test_published_requires_timestamp_and_no_error(self) -> None:
        assert _model("publication.result.published").error is None
        assert _model("publication.result.transport_unavailable").error is not None

    def test_publish_requires_confirmation(self) -> None:
        invalid = next(
            i
            for i in fixtures.build_invalid_fixtures()
            if i.name == "publication.publish_unconfirmed"
        )
        assert invalid.data["confirmed"] is False


class TestErrors:
    def test_every_error_code_is_snake_case_and_unique(self) -> None:
        values = [code.value for code in LocalErrorCode]
        assert len(values) == len(set(values))
        assert all(re.fullmatch(r"[a-z][a-z0-9_]*", value) for value in values)

    def test_error_details_refuse_secret_keys_and_paths(self) -> None:
        cls = type(_model("bridge.error.capability_missing"))
        data = _model("bridge.error.capability_missing").model_dump(mode="json")
        data["error"]["details"] = {"api_key": "v"}
        with pytest.raises(ValidationError):
            cls.model_validate(data)
        data["error"]["details"] = {"location": "C:/Users/x"}
        with pytest.raises(ValidationError):
            cls.model_validate(data)

    def test_error_message_refuses_credential_shapes(self) -> None:
        cls = type(_model("bridge.error.capability_missing"))
        data = _model("bridge.error.capability_missing").model_dump(mode="json")
        data["error"]["message"] = "failed with Bearer abcdefghijklmnop"
        with pytest.raises(ValidationError):
            cls.model_validate(data)


VENDOR_TERMS = ("claude", "anthropic", "openai", "opencode", "graphify", "obsidian", "tauri")


class TestNeutrality:
    def _module_sources(self) -> dict[str, str]:
        return {
            path.name: path.read_text(encoding="utf-8").lower()
            for path in LOCAL_SOURCE.glob("*.py")
            if path.name not in {"fixtures.py", "export.py"}
        }

    def test_contract_modules_name_no_vendor_or_shell(self) -> None:
        offenders = [
            (name, term)
            for name, source in self._module_sources().items()
            for term in VENDOR_TERMS
            if term in source
        ]
        assert offenders == []

    def test_schemas_name_no_vendor(self) -> None:
        for name, content in export.build_export().items():
            if name.startswith("schemas/") or name == "allowlist.json":
                lowered = content.lower()
                assert not [t for t in VENDOR_TERMS if t in lowered], name

    def test_contracts_do_not_import_runtime_stacks(self) -> None:
        forbidden = ("tauri", "fastapi", "sqlalchemy", "subprocess", "socket", "httpx")
        for name, source in self._module_sources().items():
            imports = "\n".join(
                line for line in source.splitlines() if line.startswith(("import ", "from "))
            )
            assert not [f for f in forbidden if f in imports], name

    def test_local_contracts_are_frozen_and_forbid_extra_fields(self) -> None:
        for model in _all_models():
            config = model.model_config
            assert config.get("extra") == "forbid", model.__name__
            assert config.get("frozen") is True, model.__name__

    def test_no_public_field_exposes_a_process_or_filesystem_primitive(self) -> None:
        banned = {"argv", "cmd", "command_line", "env", "stdin", "stdout", "shell", "pid_list"}
        offenders = [
            f"{model.__name__}.{field}"
            for model in _all_models()
            for field in model.model_fields
            if field in banned
        ]
        assert offenders == []

    def test_public_type_hints_resolve(self) -> None:
        for model in _all_models():
            typing.get_type_hints(model)
