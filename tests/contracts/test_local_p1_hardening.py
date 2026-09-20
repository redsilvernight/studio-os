from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from studio_contracts.local import fixtures
from studio_contracts.local.bridge import BridgeMessage, BridgeRequest, check_reply_correlation
from studio_contracts.local.common import (
    ComponentId,
    ComponentState,
    LocalError,
    LocalErrorCode,
    LocalResourceKind,
    build_local_uri,
)
from studio_contracts.local.handshake import (
    CompatibilityOutcome,
    HandshakeRequest,
    OptionalComponentStatus,
    PeerInfo,
    PeerRole,
    ProtocolRange,
    ProtocolVersion,
    Remediation,
    negotiate,
)
from studio_contracts.local.harness import ChangeKind, HarnessChange
from studio_contracts.local.identity import SecretKind, SecretReference
from studio_contracts.local.workspace import (
    IndexLocation,
    KnowledgeConfig,
    RepoRoot,
    WorkspaceMigrationPolicy,
    WorkspaceRoots,
    WorkspaceSaveConfigRequest,
)

_SECRET_SHAPED = "ghp_" + "a" * 30


def _daemon_with_knowledge(state: ComponentState) -> PeerInfo:
    daemon = fixtures.daemon_peer()
    components = [
        OptionalComponentStatus(
            component=component.component,
            state=state if component.component is ComponentId.KNOWLEDGE else component.state,
            provider_id=component.provider_id,
            provides=component.provides,
        )
        for component in daemon.optional_components
    ]
    return daemon.model_copy(update={"optional_components": components})


def _fixture(name: str) -> Any:
    return {item.name: item.model for item in fixtures.build_fixtures()}[name]


class TestNegotiationFailClosed:
    @pytest.mark.parametrize(
        "state", [ComponentState.DISABLED, ComponentState.NOT_INSTALLED, ComponentState.ERROR]
    )
    def test_unserved_component_capability_is_never_granted(self, state: ComponentState) -> None:
        request = HandshakeRequest(peer=fixtures.desktop_peer())
        response = negotiate(request, _daemon_with_knowledge(state))
        assert response.outcome is CompatibilityOutcome.COMPATIBLE_DEGRADED
        assert not set(fixtures.KNOWLEDGE_CAPABILITIES) & set(response.granted_capabilities)
        assert {item.capability for item in response.degraded} == set(
            fixtures.KNOWLEDGE_CAPABILITIES
        )

    def test_required_capability_of_unserved_component_is_refused(self) -> None:
        request = HandshakeRequest(peer=fixtures.desktop_peer(required=["knowledge.read"]))
        response = negotiate(request, _daemon_with_knowledge(ComponentState.DISABLED))
        assert response.outcome is CompatibilityOutcome.CAPABILITY_MISSING
        assert response.remediation is Remediation.INSTALL_OPTIONAL_COMPONENT
        assert response.granted_capabilities == []

    def test_same_role_on_both_sides_is_refused(self) -> None:
        daemon = fixtures.daemon_peer()
        response = negotiate(HandshakeRequest(peer=daemon), daemon)
        assert response.outcome is CompatibilityOutcome.PROTOCOL_INCOMPATIBLE

    def test_unimplemented_major_is_refused(self) -> None:
        future = ProtocolRange(
            minimum=ProtocolVersion(major=2, minor=0), maximum=ProtocolVersion(major=2, minor=0)
        )
        desktop = fixtures.desktop_peer(protocol=future)
        daemon = fixtures.daemon_peer(protocol=future)
        response = negotiate(HandshakeRequest(peer=desktop), daemon)
        assert response.outcome is CompatibilityOutcome.PROTOCOL_INCOMPATIBLE

    def test_foreign_protocol_id_is_refused_even_when_both_agree(self) -> None:
        desktop = fixtures.desktop_peer().model_copy(update={"protocol_id": "other.proto"})
        daemon = fixtures.daemon_peer(protocol_id="other.proto")
        response = negotiate(HandshakeRequest(peer=desktop), daemon)
        assert response.outcome is CompatibilityOutcome.PROTOCOL_INCOMPATIBLE

    def test_peer_may_declare_its_server_origin(self) -> None:
        peer = PeerInfo(
            role=PeerRole.DESKTOP,
            protocol=fixtures.desktop_peer().protocol,
            component_version="0.1.0",
            server_origin="https://studio.example.test",
        )
        assert peer.server_origin == "https://studio.example.test"


class TestTextAndIdentifierGuards:
    @pytest.mark.parametrize(
        "message",
        [
            r"Cannot read C:\Users\bob\.ssh\id_rsa",
            "failed to open /home/bob/notes.md",
            "path (/etc/passwd) refused",
            "password=hunter2hunter2",
            "key AKIAABCDEFGHIJKLMNOP leaked",
            "slack xoxb-1234567890-abcdefghij",
            "path=C:" + chr(92) + "Users" + chr(92) + "a",
            "file:///C:/Users/bob",
            "see ~/.ssh/config",
            "at /Volumes/data/x",
        ],
    )
    def test_error_message_rejects_paths_and_secrets(self, message: str) -> None:
        with pytest.raises(ValidationError):
            LocalError(
                code=LocalErrorCode.INTERNAL_ERROR,
                message=message,
                component=ComponentId.DAEMON,
                retryable=False,
            )

    @pytest.mark.parametrize(
        "value", ["failed at C:/Users/bob/x", "x see /home/bob/x", "at ~/.ssh", "p:/etc/passwd"]
    )
    def test_error_details_reject_embedded_absolute_paths(self, value: str) -> None:
        with pytest.raises(ValidationError):
            LocalError(
                code=LocalErrorCode.INTERNAL_ERROR,
                message="failed",
                component=ComponentId.DAEMON,
                retryable=False,
                details={"where": value},
            )

    def test_secret_reference_handles_reject_credential_shapes(self) -> None:
        good = fixtures.secret_reference()
        for field in ("ref_id", "lookup_key"):
            with pytest.raises(ValidationError):
                SecretReference(**{**good.model_dump(), field: _SECRET_SHAPED})

    def test_only_machine_credentials_are_referenceable(self) -> None:
        assert [kind.value for kind in SecretKind] == ["machine_credential"]


class TestPathConfinement:
    @pytest.mark.parametrize("root", ["/", "C:\\", "C:/", "//host/share", "\\\\host\\share"])
    def test_workspace_root_rejects_system_and_network_roots(self, root: str) -> None:
        with pytest.raises(ValidationError):
            WorkspaceRoots(workspace_root=root)

    def test_repo_root_rejects_drive_root(self) -> None:
        with pytest.raises(ValidationError):
            RepoRoot(name="game", path="D:\\")

    @pytest.mark.parametrize(
        "glob",
        [
            "../../**",
            "C:/**",
            "/etc/**",
            "a/../b",
            "a\\b",
            "{..,x}/**",
            "[.][.]/x",
            "~/**",
            "$HOME/**",
        ],
    )
    def test_globs_stay_relative_and_inside(self, glob: str) -> None:
        with pytest.raises(ValidationError):
            KnowledgeConfig(
                provider_id="markdown",
                content_root="vault",
                index=IndexLocation(directory_name="idx"),
                include_globs=[glob],
            )

    @pytest.mark.parametrize(
        "path",
        [
            "notes/a.md:stream",
            "CON",
            "notes/nul.txt",
            "a/.. /b",
            "notes/end.",
            "notes/ lead",
            "a\u202eb",
            "a|b",
        ],
    )
    def test_relative_path_rejects_windows_traps(self, path: str) -> None:
        with pytest.raises(ValueError):
            build_local_uri(LocalResourceKind.KNOWLEDGE, fixtures.WORKSPACE_ID, path)

    def test_relative_path_accepts_normal_and_dotfile_names(self) -> None:
        for path in ("notes/a.md", ".github/workflows/ci.yml", "a b/c.md"):
            build_local_uri(LocalResourceKind.KNOWLEDGE, fixtures.WORKSPACE_ID, path)

    @pytest.mark.parametrize(
        "target",
        [".git/hooks/pre-commit", "sub/.ssh/authorized_keys", ".env", ".env.local", ".aws/config"],
    )
    def test_harness_change_never_targets_protected_locations(self, target: str) -> None:
        with pytest.raises(ValidationError):
            HarnessChange(
                change_id="c1",
                kind=ChangeKind.CREATE,
                target=target,
                summary="x",
                after_hash="a" * 64,
            )

    def test_root_change_carries_a_confirmation_handle(self) -> None:
        request = WorkspaceSaveConfigRequest(
            config=fixtures.workspace_config(), root_confirmation_id="rc-1"
        )
        assert request.root_confirmation_id == "rc-1"

    def test_migration_policy_invariants_cannot_be_disabled(self) -> None:
        for field in ("keeps_backup", "refuses_newer"):
            with pytest.raises(ValidationError):
                WorkspaceMigrationPolicy.model_validate({field: False})


class TestReplyCorrelation:
    def test_cancel_and_request_are_not_replies(self) -> None:
        request = _fixture("bridge.request.knowledge_search")
        assert isinstance(request, BridgeRequest)
        for name in ("bridge.cancel.reindex", "bridge.request.knowledge_search"):
            reply: BridgeMessage = _fixture(name)
            with pytest.raises(ValueError):
                check_reply_correlation(request, reply)
